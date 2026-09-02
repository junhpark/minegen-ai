from __future__ import annotations

import numpy as np
import pytest

from minegen.core.models import FaultConfig, Point3D, RockQualityConfig
from minegen.world.field_grid import FieldGrid
from minegen.world.geology import (
    FaultPlane,
    FaultZone,
    compute_fault_fields,
    correlated_standard_field,
    generate_grade_field,
    generate_rock_quality,
)

GRID = FieldGrid(origin=(-300, -300, -300), spacing=(10, 10, 10), shape=(60, 60, 40))


def _lag_correlation(f: np.ndarray, axis: int, lag: int) -> float:  # type: ignore[type-arg]
    a = np.take(f, range(0, f.shape[axis] - lag), axis=axis).ravel()
    b = np.take(f, range(lag, f.shape[axis]), axis=axis).ravel()
    return float(np.corrcoef(a, b)[0, 1])


# -- correlated field ------------------------------------------------------ #


def test_standard_field_is_standardized() -> None:
    f = correlated_standard_field(np.random.default_rng(1), GRID.shape, GRID.spacing, 80, 40)
    assert f.mean() == pytest.approx(0.0, abs=1e-9)
    assert f.std() == pytest.approx(1.0, abs=1e-9)


def test_field_is_spatially_correlated_not_white_noise() -> None:
    f = correlated_standard_field(np.random.default_rng(1), GRID.shape, GRID.spacing, 80, 40)
    assert _lag_correlation(f, 0, 1) > 0.9  # adjacent blocks (10 m) nearly identical
    assert _lag_correlation(f, 0, 8) < _lag_correlation(f, 0, 1)  # decays with lag
    white = np.random.default_rng(1).standard_normal(GRID.shape)
    assert abs(_lag_correlation(white, 0, 1)) < 0.05


def test_field_anisotropy_follows_correlation_lengths() -> None:
    """With L_xy = 80 m and L_z = 20 m the field must decorrelate faster in z."""
    f = correlated_standard_field(np.random.default_rng(2), GRID.shape, GRID.spacing, 80, 20)
    lag = 3  # 30 m
    assert _lag_correlation(f, 0, lag) > _lag_correlation(f, 2, lag) + 0.15
    # at the correlation length itself the correlation is near 1/e
    assert _lag_correlation(f, 0, 8) == pytest.approx(np.exp(-1), abs=0.15)


# -- rock quality ---------------------------------------------------------- #


def test_rock_quality_statistics_and_clipping() -> None:
    cfg = RockQualityConfig(mean=65, std=12, minimum=20, maximum=90)
    rq, _ = generate_rock_quality(GRID, cfg, seed=42)
    assert rq.dtype == np.float32
    assert rq.min() >= 20 and rq.max() <= 90
    assert float(rq.mean()) == pytest.approx(65, abs=1.5)
    assert float(rq.std()) == pytest.approx(12, abs=1.5)  # mild clipping only


def test_rock_quality_deterministic_and_seed_sensitive() -> None:  # gates A, B
    cfg = RockQualityConfig()
    a, _ = generate_rock_quality(GRID, cfg, seed=42)
    b, _ = generate_rock_quality(GRID, cfg, seed=42)
    c, _ = generate_rock_quality(GRID, cfg, seed=43)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)
    assert float(c.mean()) == pytest.approx(float(a.mean()), abs=2.0)


# -- grade ----------------------------------------------------------------- #


def test_grade_field_is_positive_lognormal_with_preserved_mean() -> None:
    g = generate_grade_field(GRID, 4.2, 0.3, 80, 40, seed=42)
    assert g.dtype == np.float32
    assert g.min() > 0
    assert float(g.mean()) == pytest.approx(4.2, rel=0.05)
    g2 = generate_grade_field(GRID, 4.2, 0.3, 80, 40, seed=43)
    assert not np.array_equal(g, g2)
    assert np.array_equal(g, generate_grade_field(GRID, 4.2, 0.3, 80, 40, seed=42))


def test_grade_zero_variability_is_constant() -> None:
    g = generate_grade_field(GRID, 4.2, 0.0, 80, 40, seed=42)
    np.testing.assert_allclose(g, 4.2, rtol=1e-6)


# -- gate E: faults -------------------------------------------------------- #


def fault() -> FaultPlane:
    return FaultPlane.from_config(
        FaultConfig(
            origin=Point3D(x=-100, y=-200, z=0),
            strike_deg=120,
            dip_deg=65,
            core_half_width=2.5,
            influence_half_width=20.0,
        )
    )


def test_signed_distance_is_zero_everywhere_on_the_plane() -> None:
    f = fault()
    rng = np.random.default_rng(5)
    a, b = rng.uniform(-500, 500, size=(50, 2)).T
    on_plane = f.origin + a[:, None] * f.u + b[:, None] * f.v
    np.testing.assert_allclose(f.signed_distance(on_plane), 0.0, atol=1e-9)


@pytest.mark.parametrize(
    ("d", "zone", "influence"),
    [
        (0.0, FaultZone.CORE, 1.0),
        (2.5, FaultZone.CORE, 1.0),  # boundary is inclusive
        (11.25, FaultZone.DAMAGE, 0.5),  # midway between 2.5 and 20
        (20.0, FaultZone.DAMAGE, 0.0),  # boundary is inclusive, influence already 0
        (25.0, FaultZone.NORMAL, 0.0),
    ],
)
def test_zone_and_influence_at_reference_distances(d: float, zone: int, influence: float) -> None:
    f = fault()
    for sign in (+1.0, -1.0):  # symmetric about the plane
        p = f.origin + sign * d * f.normal
        assert f.signed_distance(p[None, :])[0] == pytest.approx(sign * d)
        assert f.zone(np.array([sign * d]))[0] == zone
        assert f.influence(np.array([sign * d]))[0] == pytest.approx(influence)


def test_influence_is_continuous_and_monotone() -> None:
    f = fault()
    d = np.linspace(0, 30, 301)
    inf = f.influence(d)
    assert np.all(np.diff(inf) <= 1e-12)  # non-increasing
    assert np.abs(np.diff(inf)).max() < 0.01  # no jumps


def test_fault_fields_on_grid_nearest_fault_wins() -> None:
    f1 = fault()
    f2 = FaultPlane.from_config(
        FaultConfig(origin=Point3D(x=200, y=200, z=0), strike_deg=30, dip_deg=80)
    )
    ff = compute_fault_fields(GRID, [f1, f2])
    centers = GRID.centers().reshape(-1, 3)
    d1, d2 = f1.signed_distance(centers), f2.signed_distance(centers)
    expected = np.where(np.abs(d1) <= np.abs(d2), d1, d2).astype(np.float32)
    np.testing.assert_allclose(ff.signed_distance.ravel(), expected, rtol=1e-6)
    assert set(np.unique(ff.nearest_index)) <= {0, 1}
    assert ff.influence.max() == pytest.approx(1.0)
    assert np.isfinite(ff.signed_distance).all()


def test_no_faults_gives_neutral_fields() -> None:
    ff = compute_fault_fields(GRID, [])
    assert np.all(ff.zone == FaultZone.NORMAL)
    assert np.all(ff.influence == 0)
    assert np.all(np.isinf(ff.signed_distance))  # +inf only inside NumPy (rule 34)
    assert np.all(ff.nearest_index == -1)


def test_clip_to_box_gives_planar_polygon_inside_box() -> None:
    f = fault()
    lo, hi = np.array([-300.0, -300.0, -300.0]), np.array([300.0, 300.0, 100.0])
    poly = f.clip_to_box(lo, hi)
    assert 3 <= poly.shape[0] <= 6
    np.testing.assert_allclose(f.signed_distance(poly), 0.0, atol=1e-6)
    assert np.all(poly >= lo - 1e-6) and np.all(poly <= hi + 1e-6)
