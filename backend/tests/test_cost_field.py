"""Phase 03 gate tests: DesignCostEvaluator (rules 41, 42)."""

from __future__ import annotations

import time

import numpy as np
import pytest

from minegen.core.models import FaultConfig, Point3D, RestrictedZone
from minegen.design.constraints import DesignContext, RejectionReason
from minegen.design.cost_field import DesignCostEvaluator
from minegen.world.geology import FaultPlane
from minegen.world.synthetic_world import generate_world
from tests.conftest import small_scenario


@pytest.fixture(scope="module")
def setup():  # type: ignore[no-untyped-def]
    sc = small_scenario(with_fault=True)
    w = generate_world(sc)
    return sc, w, DesignCostEvaluator(w, sc.design)


# -- orebody SDF: inside / surface / outside / buffer ------------------------


def test_orebody_sdf_inside_surface_outside(setup) -> None:  # type: ignore[no-untyped-def]
    _, w, _ = setup
    ob = w.orebody
    c = ob.center
    # inside: center → −half_thickness (nearest face is the thin one)
    assert ob.signed_distance(c[None, :])[0] == pytest.approx(-ob.half_thickness)
    # on the footwall face
    assert ob.signed_distance((c + ob.half_thickness * ob.w)[None, :])[0] == pytest.approx(0.0)
    # outside along w: exact perpendicular distance
    assert ob.signed_distance((c + 26.0 * ob.w)[None, :])[0] == pytest.approx(20.0)
    # outside near a corner: Euclidean to the corner
    p = c + (ob.half_length + 3) * ob.u + (ob.half_height + 4) * ob.v
    assert ob.signed_distance(p[None, :])[0] == pytest.approx(5.0)
    # sign consistent with contains()
    rng = np.random.default_rng(1)
    pts = c + rng.uniform(-150, 150, size=(2000, 3))
    sdf = ob.signed_distance(pts)
    assert np.array_equal(sdf <= 0, ob.contains(pts))


def test_orebody_exclusion_and_buffer(setup) -> None:  # type: ignore[no-untyped-def]
    sc, w, ev = setup
    ob = w.orebody
    buf = sc.design.orebody_exclusion_buffer  # 5 m
    pts = np.array(
        [
            ob.center,  # inside
            ob.center + (ob.half_thickness + buf / 2) * ob.w,  # in buffer
            ob.center + (ob.half_thickness + buf + 0.01) * ob.w,  # just outside buffer
            ob.center + (ob.half_thickness + 20.0) * ob.w,  # design offset
        ]
    )
    r = ev.evaluate_points(pts)
    assert r.rejection_reasons[0] == [RejectionReason.INSIDE_OREBODY]
    assert r.rejection_reasons[1] == [RejectionReason.OREBODY_BUFFER]
    assert r.valid[2] and r.valid[3]
    assert not r.valid[0] and not r.valid[1]
    assert np.isinf(r.total_cost_per_m[0]) and np.isinf(r.total_cost_per_m[1])
    # soft sterilization: maximal at the buffer edge, zero at the design offset
    assert r.orebody_penalty[2] == pytest.approx(sc.design.orebody_sterilization_weight, abs=0.01)
    assert r.orebody_penalty[3] == pytest.approx(0.0)


def test_crosscut_context_allows_orebody(setup) -> None:  # type: ignore[no-untyped-def]
    sc, w, _ = setup
    ctx = DesignContext(name="crosscut", orebody_exclusion_buffer=0.0, allow_inside_orebody=True)
    ev = DesignCostEvaluator(w, sc.design, ctx)
    r = ev.evaluate_points(w.orebody.center[None, :])
    assert r.valid[0] and np.isfinite(r.total_cost_per_m[0])


# -- fault penalty: core / damage / boundary / overlap -----------------------


def test_fault_penalty_core_damage_boundary(setup) -> None:  # type: ignore[no-untyped-def]
    _, w, ev = setup
    f = w.faults[0]
    cfg = f.config
    # pick a spot on the plane far from the orebody and below ground
    base = f.origin + np.array([0.0, 0.0, -100.0])
    base = base - f.signed_distance(base[None, :])[0] * f.normal  # project onto plane
    d = np.array(
        [
            0.0,
            cfg.core_half_width,
            (cfg.core_half_width + cfg.influence_half_width) / 2,
            cfg.influence_half_width,
            cfg.influence_half_width + 1.0,
        ]
    )
    pts = base[None, :] + d[:, None] * f.normal[None, :]
    pen, near = ev.fault_penalty(pts)
    np.testing.assert_allclose(near, d, atol=1e-9)
    assert pen[0] == pytest.approx(cfg.core_penalty)
    assert pen[1] == pytest.approx(cfg.core_penalty)  # boundary inclusive
    assert pen[2] == pytest.approx(cfg.damage_zone_penalty * 0.5)
    assert pen[3] == pytest.approx(0.0)  # influence boundary → 0
    assert pen[4] == pytest.approx(0.0)
    # continuity from core into damage zone is a step (core vs damage are distinct
    # parameters) but the damage ramp itself is continuous to 0
    dd = np.linspace(cfg.core_half_width + 1e-6, cfg.influence_half_width, 200)
    p2, _ = ev.fault_penalty(base[None, :] + dd[:, None] * f.normal[None, :])
    assert np.all(np.diff(p2) <= 1e-9)


def test_fault_penalty_overlap_is_summed(setup) -> None:  # type: ignore[no-untyped-def]
    sc, w, _ = setup
    f1 = w.faults[0]
    # second fault crossing the first at its origin, different penalties
    f2 = FaultPlane.from_config(
        FaultConfig(
            origin=Point3D(x=f1.origin[0], y=f1.origin[1], z=f1.origin[2]),
            strike_deg=f1.config.strike_deg + 60,
            dip_deg=80,
            core_half_width=2.5,
            influence_half_width=20,
            core_penalty=100.0,
            damage_zone_penalty=10.0,
        )
    )
    w.faults.append(f2)
    try:
        ev = DesignCostEvaluator(w, sc.design)
        p = f1.origin[None, :]  # on both planes
        pen, near = ev.fault_penalty(p)
        assert pen[0] == pytest.approx(f1.config.core_penalty + 100.0)
        assert near[0] == pytest.approx(0.0)
    finally:
        w.faults.pop()


# -- rock quality interpolation ---------------------------------------------


def test_rock_quality_is_the_spatial_field_sample(setup) -> None:  # type: ignore[no-untyped-def]
    """Rule 128: the evaluator's rock quality IS the batch field sample —
    no lattice classification lives in the evaluator any more."""
    _, w, ev = setup
    rng = np.random.default_rng(3)
    pts = rng.uniform([-200, -200, -150], [200, 200, 60], size=(2000, 3))
    np.testing.assert_array_equal(ev.rock_quality(pts), w.fields.rock_quality.sample(pts))
    assert not hasattr(w, "block_model")


def test_rock_quality_exact_at_cell_centers(setup) -> None:  # type: ignore[no-untyped-def]
    _, w, ev = setup
    fields = w.fields
    idx = np.argwhere(fields.supported)
    rng = np.random.default_rng(3)
    pick = idx[rng.choice(idx.shape[0], size=500, replace=False)]
    centers = fields.grid.origin + (pick + 0.5) * np.asarray(fields.grid.spacing)
    rq = ev.rock_quality(centers)
    truth = fields.rock_quality.values[pick[:, 0], pick[:, 1], pick[:, 2]]
    assert np.abs(rq - truth).max() < 1e-4


def test_rock_quality_midpoint_is_linear_and_surface_is_not_pulled_to_zero(setup) -> None:  # type: ignore[no-untyped-def]
    _, w, ev = setup
    fields = w.fields
    grid = fields.grid
    i, j, k = 10, 10, 3
    c0 = grid.origin + (np.array([i, j, k]) + 0.5) * np.asarray(grid.spacing)
    c1 = c0 + np.array([grid.spacing[0], 0, 0])
    mid = (c0 + c1) / 2
    v = fields.rock_quality.values
    expected = (v[i, j, k] + v[i + 1, j, k]) / 2
    assert ev.rock_quality(mid[None, :])[0] == pytest.approx(expected, abs=1e-4)
    # just below the surface (topmost supported cell) the value is a real
    # field value: the COLUMN_TOP_FILL boundary policy, not an AIR fill of 0
    col = fields.supported[i, j]
    k_top = int(np.nonzero(col)[0].max())
    z_top = grid.axis_centers(2)[k_top] + grid.spacing[2] * 0.45
    val = ev.rock_quality(np.array([[c0[0], c0[1], z_top]]))[0]
    assert val > 15.0


# -- hard constraints --------------------------------------------------------


def test_restricted_zone_is_infinite(setup) -> None:  # type: ignore[no-untyped-def]
    sc, w, _ = setup
    zone = RestrictedZone(
        name="shaft pillar", min=Point3D(x=-150, y=-150, z=-120), max=Point3D(x=-100, y=-100, z=-80)
    )
    ctx = DesignContext.decline(sc.design.model_copy(update={"restricted_zones": [zone]}))
    ev = DesignCostEvaluator(w, sc.design, ctx)
    r = ev.evaluate_points(np.array([[-125.0, -125.0, -100.0], [-125.0, -125.0, -60.0]]))
    assert not r.valid[0] and np.isinf(r.total_cost_per_m[0])
    assert r.rejection_reasons[0] == [RejectionReason.RESTRICTED_ZONE]
    assert r.valid[1]


def test_world_and_terrain_validity(setup) -> None:  # type: ignore[no-untyped-def]
    _, w, ev = setup
    xy = np.array([-150.0, 120.0])
    z_surf = w.terrain.sample(xy[None, :])[0]
    r = ev.evaluate_points(
        np.array(
            [
                [xy[0], xy[1], z_surf + 1.0],
                [xy[0], xy[1], z_surf - 1.0],
                [5000.0, 0.0, -50.0],
                [xy[0], xy[1], -1000.0],
            ]
        )
    )
    assert r.rejection_reasons[0] == [RejectionReason.ABOVE_TERRAIN]
    assert r.valid[1]
    assert RejectionReason.OUTSIDE_WORLD in r.rejection_reasons[2]
    assert RejectionReason.OUTSIDE_WORLD in r.rejection_reasons[3]


def test_minimum_cover(setup) -> None:  # type: ignore[no-untyped-def]
    sc, w, _ = setup
    ctx = DesignContext.decline(sc.design.model_copy(update={"minimum_surface_cover": 15.0}))
    ev = DesignCostEvaluator(w, sc.design, ctx)
    xy = np.array([-150.0, 120.0])
    z_surf = w.terrain.sample(xy[None, :])[0]
    r = ev.evaluate_points(np.array([[xy[0], xy[1], z_surf - 5.0], [xy[0], xy[1], z_surf - 20.0]]))
    assert r.rejection_reasons[0] == [RejectionReason.INSUFFICIENT_COVER]
    assert r.valid[1]


# -- totals, payload, determinism, throughput -------------------------------


def test_total_is_sum_of_components_and_payload_is_finite(setup) -> None:  # type: ignore[no-untyped-def]
    _, _w, ev = setup
    rng = np.random.default_rng(7)
    pts = rng.uniform([-200, -200, -150], [200, 200, 60], size=(2000, 3))
    r = ev.evaluate_points(pts)
    v = r.valid
    np.testing.assert_allclose(
        r.total_cost_per_m[v],
        (r.base_cost + r.rock_penalty + r.fault_penalty + r.orebody_penalty)[v],
    )
    assert np.all(r.total_cost_per_m[v] >= ev.minimum_cost_per_m)
    assert np.all(np.isinf(r.total_cost_per_m[~v]))
    payload = r.to_payload()
    for row in payload:
        for key, val in row.items():
            if isinstance(val, float):
                assert np.isfinite(val), key
    assert any(row["totalCostPerM"] is None for row in payload)


def test_evaluation_is_deterministic(setup) -> None:  # type: ignore[no-untyped-def]
    _, _, ev = setup
    pts = np.random.default_rng(9).uniform([-200, -200, -150], [200, 200, 60], size=(500, 3))
    a, b = ev.evaluate_points(pts), ev.evaluate_points(pts)
    assert np.array_equal(a.total_cost_per_m, b.total_cost_per_m)
    assert a.rejection_reasons == b.rejection_reasons


def test_throughput_100k_points(setup) -> None:  # type: ignore[no-untyped-def]
    _, _, ev = setup
    pts = np.random.default_rng(11).uniform([-200, -200, -150], [200, 200, 60], size=(100_000, 3))
    t = time.perf_counter()
    ev.evaluate_points(pts)
    rate = 100_000 / (time.perf_counter() - t)
    print(f"\nGATE throughput: {rate:,.0f} points/s")
    assert rate > 50_000
