"""Phase 18 spatial-field core (rules 127–131): lattice geometry, batch
sampling, terrain boundary policy, determinism, RNG isolation, persistence
round-trip and legacy-artifact rejection."""

from __future__ import annotations

import numpy as np
import pytest

from minegen.core.models import FieldSamplingConfig, OrebodyConfig, Point3D, ScenarioCreate
from minegen.world.field_grid import FieldGrid
from minegen.world.geology import FaultZone
from minegen.world.spatial_fields import (
    COLUMN_TOP_FILL,
    FIELD_ARTIFACT_KEY,
    FIELD_ARTIFACT_VERSION,
    IncompatibleFieldArtifactError,
    RegularScalarField,
    SpatialFieldSet,
    column_top_fill,
    terrain_support_fraction,
)
from minegen.world.synthetic_world import generate_world
from tests.conftest import small_scenario

# -- FieldGrid geometry / index / centers ----------------------------------- #


def test_field_grid_extent_centers_and_indexing() -> None:
    g = FieldGrid.from_extent((-20.0, -10.0, 0.0), (20.0, 10.0, 25.0), (10.0, 5.0, 10.0))
    assert g.shape == (4, 4, 3)  # the last z cell extends past 25 to fully cover
    assert g.cell_count == 48
    assert g.max_corner == (20.0, 10.0, 30.0)
    np.testing.assert_allclose(g.axis_centers(0), [-15.0, -5.0, 5.0, 15.0])
    np.testing.assert_allclose(g.axis_centers(2), [5.0, 15.0, 25.0])
    c = g.centers()
    assert c.shape == (4, 4, 3, 3)
    np.testing.assert_allclose(c[1, 2, 0], [-5.0, 2.5, 5.0])
    idx = g.world_to_index(np.array([[-19.9, -9.9, 0.1], [19.9, 9.9, 29.9], [21.0, 0.0, 0.0]]))
    assert idx.tolist() == [[0, 0, 0], [3, 3, 2], [4, 2, 0]]
    assert g.contains_index(idx).tolist() == [True, True, False]
    with pytest.raises(ValueError):
        FieldGrid.from_extent((0.0, 0.0, 0.0), (0.0, 1.0, 1.0), (1.0, 1.0, 1.0))
    assert FieldGrid.from_npz_fields(g.to_npz_fields()) == g


# -- RegularScalarField: batch sampling / interpolation --------------------- #


def _linear_field() -> RegularScalarField:
    g = FieldGrid(origin=(0.0, 0.0, 0.0), spacing=(2.0, 2.0, 2.0), shape=(5, 4, 3))
    c = g.centers()
    values = (1.0 * c[..., 0] + 10.0 * c[..., 1] + 100.0 * c[..., 2]).astype(np.float32)
    return RegularScalarField("lin", g, values)


def test_batch_sample_is_exact_for_a_linear_field_and_clamps_outside() -> None:
    f = _linear_field()
    rng = np.random.default_rng(5)
    # anywhere inside the CENTER lattice a trilinear scheme reproduces a linear field
    pts = rng.uniform([1.0, 1.0, 1.0], [9.0, 7.0, 5.0], size=(1000, 3))
    expected = pts[:, 0] + 10 * pts[:, 1] + 100 * pts[:, 2]
    np.testing.assert_allclose(f.sample(pts), expected, atol=1e-3)
    # clamped to the outermost centers: no extrapolation
    far = np.array([[-50.0, -50.0, -50.0], [500.0, 500.0, 500.0]])
    np.testing.assert_allclose(f.sample(far), [1 + 10 + 100, 9 + 70 + 500], atol=1e-3)
    # batch result equals per-point results (vectorization is exact)
    one_by_one = np.array([f.sample(p[None, :])[0] for p in pts[:50]])
    np.testing.assert_array_equal(f.sample(pts[:50]), one_by_one)
    assert f.sample(pts).dtype == np.float64 and f.sample(pts).shape == (1000,)
    assert np.isfinite(f.sample(pts)).all()


def test_sample_shape_and_field_shape_validation() -> None:
    f = _linear_field()
    with pytest.raises(ValueError):
        f.sample(np.zeros((3, 2)))
    with pytest.raises(ValueError):
        RegularScalarField("bad", f.grid, np.zeros((2, 2, 2), dtype=np.float32))


def test_sample_nearest_for_categorical_fields() -> None:
    g = FieldGrid(origin=(0.0, 0.0, 0.0), spacing=(1.0, 1.0, 1.0), shape=(3, 3, 3))
    values = np.arange(27, dtype=np.uint8).reshape(3, 3, 3)
    f = RegularScalarField("cat", g, values)
    out = f.sample_nearest(np.array([[0.5, 0.5, 0.5], [2.4, 1.6, 0.6], [99.0, 99.0, 99.0]]))
    assert out.tolist() == [0, 2 * 9 + 1 * 3 + 0, 26]  # nearest centers (2.5, 1.5, 0.5)


# -- terrain boundary policy ------------------------------------------------ #


def test_terrain_support_is_monotone_and_bottom_layer_is_fully_supported() -> None:
    w = generate_world(small_scenario())
    fields = w.fields
    s = fields.terrain_support
    assert s.dtype == np.float32 and s.shape == fields.grid.shape
    assert np.all(s[:, :, 0] == 1.0)
    assert np.all(np.diff(s, axis=2) <= 0.0)  # fraction below terrain never grows upward
    assert (s < 1.0).any() and (s == 0.0).any()
    zc = fields.grid.axis_centers(2)
    fully_below = zc < w.terrain.z_min - fields.grid.spacing[2] / 2
    assert np.all(s[:, :, fully_below] == 1.0)
    # identical to a direct recomputation (deterministic pattern)
    np.testing.assert_array_equal(s, terrain_support_fraction(fields.grid, w.terrain))


def test_column_top_fill_copies_the_topmost_supported_value_upward() -> None:
    values = np.arange(2 * 2 * 4, dtype=np.float32).reshape(2, 2, 4)
    supported = np.ones((2, 2, 4), dtype=bool)
    supported[0, 0, 2:] = False  # column (0,0): cells 2,3 above ground
    supported[1, 1, 3] = False
    out = column_top_fill(values, supported)
    assert out[0, 0].tolist() == [0.0, 1.0, 1.0, 1.0]
    assert out[1, 1].tolist() == [12.0, 13.0, 14.0, 14.0]
    assert out[0, 1].tolist() == values[0, 1].tolist()
    assert values[0, 0, 2] == 2.0  # input untouched
    supported[0, 0, 0] = False
    with pytest.raises(ValueError):
        column_top_fill(values, supported)


def test_rock_quality_carries_the_column_top_fill_policy() -> None:
    w = generate_world(small_scenario())
    rq = w.fields.rock_quality
    assert rq.meta["boundaryPolicy"] == COLUMN_TOP_FILL
    supported = w.fields.supported
    v = rq.values
    for k in range(1, v.shape[2]):
        unsupported = ~supported[:, :, k]
        assert np.array_equal(v[:, :, k][unsupported], v[:, :, k - 1][unsupported])
    assert v.min() >= 20.0  # no 0 "air" fill anywhere


# -- determinism / RNG isolation (rules 7, 121) ----------------------------- #


def test_world_is_bitwise_reproducible_from_seed() -> None:
    a = generate_world(small_scenario(seed=42))
    b = generate_world(small_scenario(seed=42))
    assert np.array_equal(a.terrain.z, b.terrain.z)
    for name in SpatialFieldSet.FIELD_NAMES:
        assert np.array_equal(a.fields.field(name).values, b.fields.field(name).values), name
    assert np.array_equal(a.fields.terrain_support, b.fields.terrain_support)


def test_different_seed_changes_fields_but_not_geometry_fields() -> None:
    a = generate_world(small_scenario(seed=42))
    b = generate_world(small_scenario(seed=43))
    assert not np.array_equal(a.terrain.z, b.terrain.z)
    assert not np.array_equal(a.fields.rock_quality.values, b.fields.rock_quality.values)
    assert not np.array_equal(a.fields.grade.values, b.fields.grade.values)
    # geometry-driven fields do not depend on the seed at all
    assert np.array_equal(a.fields.fault_zone.values, b.fields.fault_zone.values)
    assert a.fields.grid == b.fields.grid
    sa, sb = a.fields.stats(), b.fields.stats()
    assert sa["rockQuality"]["mean"] == pytest.approx(sb["rockQuality"]["mean"], abs=3.0)


def test_rng_domains_are_isolated() -> None:
    """Changing faults or the orebody (their own sub-streams) never shifts
    the rock / grade draws; the rock-quality config never touches grade."""
    base = generate_world(small_scenario(with_fault=True))
    no_fault = generate_world(small_scenario(with_fault=False))
    assert np.array_equal(base.fields.rock_quality.values, no_fault.fields.rock_quality.values)
    assert np.array_equal(base.fields.grade.values, no_fault.fields.grade.values)
    moved = small_scenario(with_fault=True)
    moved.orebody = OrebodyConfig(
        center=Point3D(x=-40.0, y=-20.0, z=-70.0),
        strike_deg=80.0,
        dip_deg=60.0,
        length=150.0,
        height=100.0,
        thickness=8.0,
        mean_grade=4.2,
        grade_variability=0.3,
    )
    m = generate_world(moved)
    assert np.array_equal(base.fields.rock_quality.values, m.fields.rock_quality.values)
    assert np.array_equal(base.fields.grade.values, m.fields.grade.values)
    rq_cfg = small_scenario(with_fault=True)
    rq_cfg.geology.rock_quality.mean = 50.0
    r = generate_world(rq_cfg)
    assert np.array_equal(base.fields.grade.values, r.fields.grade.values)
    assert not np.array_equal(base.fields.rock_quality.values, r.fields.rock_quality.values)


def test_grade_correlation_lengths_are_independent_of_rock_quality() -> None:
    base = small_scenario(with_fault=False)
    a = generate_world(base)
    short = small_scenario(with_fault=False)
    short.orebody.grade_correlation_length_xy = 15.0
    short.orebody.grade_correlation_length_z = 10.0
    b = generate_world(short)
    assert np.array_equal(a.fields.rock_quality.values, b.fields.rock_quality.values)
    assert not np.array_equal(a.fields.grade.values, b.fields.grade.values)


# -- grade semantics (rule 129) ---------------------------------------------- #


def test_grade_field_is_defined_everywhere_and_membership_is_analytic() -> None:
    w = generate_world(small_scenario(with_fault=False))
    g = w.fields.grade.values
    assert g.dtype == np.float32 and (g > 0).all()
    centers = w.fields.grid.centers().reshape(-1, 3)
    inside = w.orebody.contains(centers)
    # the field carries no membership of its own: values outside the solid are
    # ordinary field values, and the only way to know is the analytic solid
    assert (g.ravel()[~inside] > 0).all()
    assert 0.0 < inside.mean() < 0.5


def test_analytic_orebody_is_invariant_to_sampling_resolution() -> None:
    coarse = generate_world(small_scenario(with_fault=False))
    sc = small_scenario(with_fault=False)
    sc.field_sampling = FieldSamplingConfig(spacing_x=5, spacing_y=5, spacing_z=5)
    fine = generate_world(sc)
    assert coarse.orebody.to_dict() == fine.orebody.to_dict()
    assert fine.fields.grid.shape == tuple(2 * n for n in coarse.fields.grid.shape)


# -- lattice extent (rule 35) ----------------------------------------------- #


def test_grid_spans_reference_minus_depth_to_reference_plus_relief() -> None:
    sc = small_scenario()
    w = generate_world(sc)
    g = w.fields.grid
    assert g.origin == (-200.0, -200.0, sc.terrain.base_elevation - sc.world.depth)
    assert g.max_corner[2] == sc.terrain.base_elevation + sc.terrain.relief
    assert g.max_corner[2] >= w.terrain.z_max
    assert generate_world(small_scenario(seed=43)).fields.grid == g


# -- fault fields ----------------------------------------------------------- #


def test_fault_zones_present_and_ordered() -> None:
    w = generate_world(small_scenario(with_fault=True))
    zone = w.fields.fault_zone.values
    sd = w.fields.fault_signed_distance.values
    assert (zone == FaultZone.CORE).any() and (zone == FaultZone.DAMAGE).any()
    assert (zone == FaultZone.NORMAL).any()
    assert np.abs(sd[zone == FaultZone.CORE]).max() <= 2.5
    assert np.abs(sd[zone == FaultZone.DAMAGE]).min() > 2.5
    assert w.fields.fault_influence.values[zone == FaultZone.CORE].min() == pytest.approx(1.0)


def test_all_fields_finite_with_a_fault() -> None:
    w = generate_world(small_scenario(with_fault=True))
    for name in SpatialFieldSet.FIELD_NAMES:
        assert np.isfinite(w.fields.field(name).values).all(), name


# -- stats: neutral diagnostics only (rule 131) ----------------------------- #


def test_stats_are_neutral_field_diagnostics() -> None:
    sc = ScenarioCreate()
    w = generate_world(sc)
    st = w.fields.stats()
    assert st["grid"]["shape"][:2] == [120, 120]
    assert 60 <= st["grid"]["shape"][2] <= 70
    assert st["cellCount"] == int(np.prod(st["grid"]["shape"]))
    assert 0.0 < st["terrainSupportedFraction"] < 1.0
    assert 20.0 <= st["rockQuality"]["min"] <= st["rockQuality"]["mean"] <= st["rockQuality"]["max"]
    assert st["boundaryPolicy"] == COLUMN_TOP_FILL
    assert {k: v["dtype"] for k, v in st["arrays"].items()} == {
        "rock_quality": "float32",
        "grade": "float32",
        "fault_signed_distance": "float32",
        "fault_zone": "uint8",
        "fault_influence": "float32",
        "terrain_support": "float32",
    }
    assert st["totalMB"] < 25.0
    banned = {
        "nBlocks",
        "nOreBlocks",
        "nAirBlocks",
        "nRockBlocks",
        "oreVolumeM3",
        "oreTonnes",
        "meanOreGrade",
        "faultCoreBlocks",
        "faultDamageBlocks",
    }
    assert not banned & set(st)
    world_stats = w.stats(sc)
    assert "blockModel" not in world_stats and "tonnes" not in world_stats["orebody"]


# -- persistence ------------------------------------------------------------ #


def test_npz_roundtrip_preserves_every_field(tmp_path) -> None:  # type: ignore[no-untyped-def]
    w = generate_world(small_scenario())
    p = tmp_path / "arrays.npz"
    np.savez_compressed(p, **w.fields.to_npz_fields())
    with np.load(p) as npz:
        assert int(npz[FIELD_ARTIFACT_KEY][0]) == FIELD_ARTIFACT_VERSION
        back = SpatialFieldSet.from_npz(npz)
    assert back.grid == w.fields.grid
    for name in SpatialFieldSet.FIELD_NAMES:
        assert np.array_equal(back.field(name).values, w.fields.field(name).values), name
    assert np.array_equal(back.terrain_support, w.fields.terrain_support)
    assert back.rock_quality.meta["boundaryPolicy"] == COLUMN_TOP_FILL
    pts = np.random.default_rng(1).uniform([-200, -200, -150], [200, 200, 60], size=(200, 3))
    np.testing.assert_array_equal(back.rock_quality.sample(pts), w.fields.rock_quality.sample(pts))


def _legacy_block_model_npz(path) -> None:  # type: ignore[no-untyped-def]
    """The exact key layout Phase 17 persisted (BlockModel.ARRAY_FIELDS + grid)."""
    shape = (4, 4, 3)
    np.savez_compressed(
        path,
        rock_type=np.ones(shape, dtype=np.uint8),
        ore_fraction=np.zeros(shape, dtype=np.float32),
        ore_flag=np.zeros(shape, dtype=bool),
        grade=np.zeros(shape, dtype=np.float32),
        rock_quality=np.full(shape, 60.0, dtype=np.float32),
        fault_signed_distance=np.zeros(shape, dtype=np.float32),
        fault_zone=np.zeros(shape, dtype=np.uint8),
        fault_influence=np.zeros(shape, dtype=np.float32),
        grid_origin=np.array([0.0, 0.0, 0.0]),
        grid_spacing=np.array([10.0, 10.0, 10.0]),
        grid_shape=np.array(shape, dtype=np.float64),
        terrain_z=np.zeros((5, 5)),
        terrain_meta=np.array([0.0, 0.0, 10.0]),
    )


def test_legacy_block_model_npz_is_rejected_never_reinterpreted(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = tmp_path / "arrays.npz"
    _legacy_block_model_npz(p)
    with np.load(p) as npz, pytest.raises(IncompatibleFieldArtifactError, match="legacy"):
        SpatialFieldSet.from_npz(npz)


def test_wrong_artifact_version_or_missing_arrays_is_rejected(tmp_path) -> None:  # type: ignore[no-untyped-def]
    w = generate_world(small_scenario())
    fields = dict(w.fields.to_npz_fields())
    fields[FIELD_ARTIFACT_KEY] = np.array([FIELD_ARTIFACT_VERSION + 1])
    p = tmp_path / "v.npz"
    np.savez_compressed(p, **fields)
    with np.load(p) as npz, pytest.raises(IncompatibleFieldArtifactError, match="version"):
        SpatialFieldSet.from_npz(npz)
    fields = dict(w.fields.to_npz_fields())
    fields.pop("field_grade")
    q = tmp_path / "m.npz"
    np.savez_compressed(q, **fields)
    with np.load(q) as npz, pytest.raises(IncompatibleFieldArtifactError, match="missing"):
        SpatialFieldSet.from_npz(npz)


# -- lattice plane construction (Phase 18 acceptance hotfix) ---------------- #


def test_plane_centers_match_the_full_lattice_but_build_one_plane_only() -> None:
    """``plane_centers`` must equal the corresponding plane of ``centers()``
    in value AND order (the slice payload ravels the field the same way),
    while allocating only rows×cols points instead of the whole lattice."""
    g = FieldGrid(origin=(-20.0, -10.0, 0.0), spacing=(10.0, 5.0, 10.0), shape=(4, 4, 3))
    full = g.centers()
    for axis in range(3):
        for index in range(g.shape[axis]):
            expected = np.take(full, index, axis=axis).reshape(-1, 3)
            got = g.plane_centers(axis, index)
            np.testing.assert_array_equal(got, expected)
            assert got.shape[0] == expected.shape[0] < g.cell_count
    with pytest.raises(IndexError):
        g.plane_centers(2, 3)


def test_cell_subsample_offsets_are_deterministic_symmetric_midpoints() -> None:
    g = FieldGrid(origin=(0.0, 0.0, 0.0), spacing=(10.0, 4.0, 2.0), shape=(2, 2, 2))
    off = g.cell_subsample_offsets(3)
    assert off.shape == (27, 3)
    np.testing.assert_array_equal(off, g.cell_subsample_offsets(3))  # deterministic
    np.testing.assert_allclose(off.mean(axis=0), [0.0, 0.0, 0.0], atol=1e-12)  # symmetric
    # every offset stays inside its own cell
    assert np.all(np.abs(off) < np.asarray(g.spacing) / 2.0)
    np.testing.assert_allclose(np.unique(off[:, 0]), [-10 / 3, 0.0, 10 / 3], atol=1e-12)
    assert g.cell_subsample_offsets(1).tolist() == [[0.0, 0.0, 0.0]]
    with pytest.raises(ValueError):
        g.cell_subsample_offsets(0)
    assert g.cell_half_diagonal == pytest.approx(0.5 * np.sqrt(100 + 16 + 4))
