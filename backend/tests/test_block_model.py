from __future__ import annotations

import numpy as np
import pytest

from minegen.core.models import BlockModelConfig, OrebodyConfig, Point3D, ScenarioCreate
from minegen.world.block_model import BlockModel, RockType
from minegen.world.geology import FaultZone
from minegen.world.synthetic_world import generate_world
from tests.conftest import small_scenario

# -- gate A: determinism --------------------------------------------------- #


def test_world_is_bitwise_reproducible_from_seed() -> None:
    a = generate_world(small_scenario(seed=42))
    b = generate_world(small_scenario(seed=42))
    assert np.array_equal(a.terrain.z, b.terrain.z)
    for name in BlockModel.ARRAY_FIELDS:
        assert np.array_equal(getattr(a.block_model, name), getattr(b.block_model, name)), name


# -- gate B: seed sensitivity ---------------------------------------------- #


def test_different_seed_changes_fields_but_not_statistics() -> None:
    a = generate_world(small_scenario(seed=42))
    b = generate_world(small_scenario(seed=43))
    assert not np.array_equal(a.terrain.z, b.terrain.z)
    assert not np.array_equal(a.block_model.rock_quality, b.block_model.rock_quality)
    assert not np.array_equal(a.block_model.grade, b.block_model.grade)
    # geometry-driven fields do not depend on the seed at all
    assert np.array_equal(a.block_model.ore_fraction, b.block_model.ore_fraction)
    assert np.array_equal(a.block_model.fault_zone, b.block_model.fault_zone)
    sa, sb = a.block_model.stats(2.8), b.block_model.stats(2.8)
    assert sa["rockQualityMean"] == pytest.approx(sb["rockQualityMean"], abs=3.0)
    assert sa["meanOreGrade"] == pytest.approx(sb["meanOreGrade"], abs=0.8)


# -- grid / extent (rule 35) ----------------------------------------------- #


def test_grid_spans_reference_minus_depth_to_reference_plus_relief() -> None:
    sc = small_scenario()
    w = generate_world(sc)
    g = w.block_model.grid
    assert g.origin == (-200.0, -200.0, sc.terrain.base_elevation - sc.world.depth)
    assert g.max_corner[2] == sc.terrain.base_elevation + sc.terrain.relief
    assert g.max_corner[2] >= w.terrain.z_max  # terrain always fits inside the grid
    # shape is a function of configuration only, never of the seed
    assert generate_world(small_scenario(seed=43)).block_model.grid == g


def test_air_blocks_follow_subsampled_solid_fraction() -> None:
    w = generate_world(small_scenario())
    bm = w.block_model
    zc = bm.grid.axis_centers(2)
    air = bm.rock_type == RockType.AIR
    assert air.any()
    # air only where the block is at least partly above the terrain
    assert zc[np.nonzero(air.any(axis=(0, 1)))[0].min()] > w.terrain.z_min - bm.grid.spacing[2]
    assert not air[:, :, 0].any()  # bottom layer is never air
    assert not bm.ore_flag[air].any()
    # air is a column property: above an air block everything is air
    for k in range(bm.grid.shape[2] - 1):
        assert np.all(~air[:, :, k] | air[:, :, k + 1])
    # and blocks fully below the terrain minimum are never air
    assert not air[:, :, zc < w.terrain.z_min - bm.grid.spacing[2] / 2].any()


# -- orebody sampling ------------------------------------------------------ #


def test_sampled_ore_volume_matches_analytic_solid() -> None:
    sc = small_scenario()
    w = generate_world(sc)
    ratio = w.block_model.ore_volume() / w.orebody.volume()
    assert ratio == pytest.approx(1.0, abs=0.03)
    assert w.block_model.ore_tonnes(sc.orebody.density) == pytest.approx(
        w.orebody.tonnes(), rel=0.03
    )


def test_ore_flags_lie_inside_or_adjacent_to_analytic_orebody() -> None:
    w = generate_world(small_scenario())
    bm = w.block_model
    idx = np.argwhere(bm.ore_flag)
    centers = bm.grid.origin + (idx + 0.5) * np.asarray(bm.grid.spacing)
    # ore-flagged block centers are within half a block diagonal of the slab
    local = np.abs(w.orebody.to_local(centers))
    tol = np.linalg.norm(np.asarray(bm.grid.spacing)) / 2
    assert np.all(local <= w.orebody.half_extents + tol)
    assert bm.rock_type[bm.ore_flag].min() == RockType.ORE


def test_analytic_orebody_is_invariant_to_block_resolution() -> None:
    """Halving the block size must not move the orebody (analytic truth)."""
    coarse = generate_world(small_scenario(with_fault=False))
    sc = small_scenario(with_fault=False)
    sc.block_model = BlockModelConfig(dx=5, dy=5, dz=5)
    fine = generate_world(sc)
    assert coarse.orebody.to_dict() == fine.orebody.to_dict()
    assert coarse.block_model.ore_volume() == pytest.approx(fine.block_model.ore_volume(), rel=0.03)
    assert fine.block_model.ore_volume() / fine.orebody.volume() == pytest.approx(1.0, abs=0.02)


# -- fault fields on the block model --------------------------------------- #


def test_fault_zones_present_and_ordered() -> None:
    w = generate_world(small_scenario(with_fault=True))
    bm = w.block_model
    assert (bm.fault_zone == FaultZone.CORE).any()
    assert (bm.fault_zone == FaultZone.DAMAGE).any()
    assert (bm.fault_zone == FaultZone.NORMAL).any()
    core, damage = bm.fault_zone == FaultZone.CORE, bm.fault_zone == FaultZone.DAMAGE
    assert np.abs(bm.fault_signed_distance[core]).max() <= 2.5
    assert np.abs(bm.fault_signed_distance[damage]).min() > 2.5
    assert bm.fault_influence[core].min() == pytest.approx(1.0)


# -- gate F: memory / dtypes ----------------------------------------------- #


def test_all_fields_finite_except_no_fault_distance() -> None:
    w = generate_world(small_scenario(with_fault=True))
    for name in BlockModel.ARRAY_FIELDS:
        a = getattr(w.block_model, name)
        assert np.isfinite(a).all(), name


def test_default_world_block_model_memory_budget() -> None:
    sc = ScenarioCreate()
    w = generate_world(sc)
    st = w.block_model.stats(sc.orebody.density)
    assert st["shape"][:2] == [120, 120]
    assert 60 <= st["shape"][2] <= 70  # (300+600+relief)/10 layers
    assert st["nBlocks"] == int(np.prod(st["shape"]))
    expected_dtypes = {
        "rock_type": "uint8",
        "ore_fraction": "float32",
        "ore_flag": "bool",
        "grade": "float32",
        "rock_quality": "float32",
        "fault_signed_distance": "float32",
        "fault_zone": "uint8",
        "fault_influence": "float32",
    }
    assert {k: v["dtype"] for k, v in st["arrays"].items()} == expected_dtypes
    assert st["totalMB"] < 25.0  # 950k blocks × 23 bytes
    print("\nGATE F default world:", {k: st[k] for k in ("shape", "nBlocks", "totalMB")})
    for k, v in st["arrays"].items():
        print(f"  {k:22s} {v['dtype']:8s} {v['bytes'] / 1e6:6.2f} MB")


def test_npz_roundtrip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    w = generate_world(small_scenario())
    p = tmp_path / "arrays.npz"
    w.block_model.save_npz(p)
    bm = BlockModel.load_npz(p)
    assert bm.grid == w.block_model.grid
    for name in BlockModel.ARRAY_FIELDS:
        assert np.array_equal(getattr(bm, name), getattr(w.block_model, name)), name


# -- outcropping orebody (P02.1 item 2) ------------------------------------ #


def outcrop_scenario() -> ScenarioCreate:
    """Orebody center lifted to z = +80 with terrain at 100 ± 20: roughly the
    top third of the slab is above ground."""
    sc = small_scenario(with_fault=False)
    sc.orebody = OrebodyConfig(
        center=Point3D(x=40.0, y=20.0, z=80.0),
        strike_deg=35.0,
        dip_deg=70.0,
        length=200.0,
        height=120.0,
        thickness=12.0,
        mean_grade=4.2,
    )
    return sc


def _monte_carlo_in_situ_volume(sc: ScenarioCreate, n: int = 400_000) -> float:
    """Brute-force reference: uniform samples in the orebody's local box,
    counted when inside the slab and below the terrain."""
    w = generate_world(sc)
    ob = w.orebody
    rng = np.random.default_rng(123)
    local = rng.uniform(-ob.half_extents, ob.half_extents, size=(n, 3))
    pts = ob.to_world(local)
    below = pts[:, 2] <= w.terrain.sample(pts[:, :2])
    return float(below.mean()) * ob.volume()


def test_outcropping_orebody_excludes_volume_above_terrain() -> None:
    sc = outcrop_scenario()
    w = generate_world(sc)
    bm = w.block_model
    analytic = w.orebody.volume()
    reference = _monte_carlo_in_situ_volume(sc)
    assert reference < 0.85 * analytic  # the scenario really outcrops

    in_situ = bm.ore_volume()
    assert in_situ < analytic
    assert in_situ == pytest.approx(reference, rel=0.04)
    # ore is a subset of solid: no ore above ground, no ore in AIR blocks
    assert not bm.ore_flag[bm.rock_type == RockType.AIR].any()
    above = bm.grid.axis_centers(2)[None, None, :] > w.terrain.z_max + bm.grid.spacing[2]
    assert bm.ore_fraction[np.broadcast_to(above, bm.grid.shape)].max() == 0.0


def test_buried_orebody_in_situ_equals_analytic() -> None:
    w = generate_world(small_scenario(with_fault=False))
    assert w.block_model.ore_volume() == pytest.approx(
        w.orebody.volume(), abs=0.03 * w.orebody.volume()
    )


# -- rock-only fault statistics (P02.1 item 3) ----------------------------- #


def test_fault_statistics_count_rock_blocks_only() -> None:
    w = generate_world(small_scenario(with_fault=True))
    bm = w.block_model
    st = bm.stats(2.8)
    rock = bm.rock_type != RockType.AIR
    assert st["faultCoreBlocks"] == int(((bm.fault_zone == 2) & rock).sum())
    assert st["faultDamageBlocks"] == int(((bm.fault_zone == 1) & rock).sum())
    # the field itself is still defined in air (mathematical plane distance)
    assert ((bm.fault_zone == 1) & ~rock).any()
    assert st["faultDamageBlocks"] < int((bm.fault_zone == 1).sum())


# -- grade continuity decoupled from rock quality (P02.1 item 4) ----------- #


def test_grade_correlation_lengths_are_independent_of_rock_quality() -> None:
    base = small_scenario(with_fault=False)
    a = generate_world(base)
    short = small_scenario(with_fault=False)
    short.orebody.grade_correlation_length_xy = 15.0
    short.orebody.grade_correlation_length_z = 10.0
    b = generate_world(short)
    # rock quality untouched, grade field changed
    assert np.array_equal(a.block_model.rock_quality, b.block_model.rock_quality)
    assert not np.array_equal(a.block_model.grade, b.block_model.grade)
    # defaults preserve the pre-P02.1 coupling (80 / 40 m)
    assert (
        base.orebody.grade_correlation_length_xy == base.geology.rock_quality.correlation_length_xy
    )
    assert base.orebody.grade_correlation_length_z == base.geology.rock_quality.correlation_length_z
