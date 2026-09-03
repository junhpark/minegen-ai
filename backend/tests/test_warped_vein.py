"""Phase 19 — WARPED_VEIN authoritative implicit solid and its derivatives
(rules 133–140)."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest
from pydantic import ValidationError

from minegen.core.enums import DistanceContract, OrebodyType, ScenarioPreset
from minegen.core.models import (
    HarmonicMode,
    OrebodyConfig,
    Point3D,
    Scenario,
    ScenarioCreate,
    WarpedVeinConfig,
)
from minegen.design.cost_field import DesignCostEvaluator, ExactDistanceRequiredError
from minegen.export.scene_manifest import (
    MASK_OREBODY_INTERSECTION_BELOW_TERRAIN,
    build_scene,
    cells_intersect_orebody,
    slice_mask,
)
from minegen.services.scenario_realizer import (
    realize_scenario,
    warped_vein_morphology_valid,
)
from minegen.world.orebody import (
    AnalyticOrebody,
    EllipsoidOrebody,
    ImplicitOrebody,
    TabularOrebody,
    build_orebody,
)
from minegen.world.synthetic_world import generate_world
from minegen.world.warped_vein import (
    MAX_GEOMETRY_CELLS,
    VOLUME_RELATIVE_TOLERANCE,
    WarpedVeinGeometryBudgetError,
    WarpedVeinMorphology,
    WarpedVeinOrebody,
    plan_lattice,
)

M = HarmonicMode


def fixed_config(**overrides: object) -> OrebodyConfig:
    """A hand-written resolved morphology (no realizer, no RNG)."""
    vein = WarpedVeinConfig(
        warp_amplitude=24.0,
        centerline_deviation=50.0,
        outline_irregularity=0.3,
        thickness_variability=0.4,
        pinch_floor_ratio=0.45,
        edge_taper=0.5,
        warp_modes=[
            M(ku=1, kv=0, phase_u=0.3, weight=0.8),
            M(ku=0, kv=1, phase_v=1.1, weight=-0.5),
            M(ku=1, kv=1, weight=0.4),
        ],
        deviation_modes=[M(ku=0, kv=1, phase_v=0.4, weight=0.9), M(ku=0, kv=2, weight=0.3)],
        outline_modes=[
            M(ku=1, kv=0, phase_u=0.7, weight=0.6),
            M(ku=0, kv=1, phase_v=2.0, weight=0.5),
            M(ku=2, kv=1, weight=0.3),
        ],
        thickness_modes=[
            M(ku=1, kv=0, weight=0.7),
            M(ku=1, kv=1, phase_u=1.0, weight=0.5),
            M(ku=0, kv=2, weight=0.4),
        ],
    )
    base = dict(
        orebody_type=OrebodyType.WARPED_VEIN,
        center=Point3D(x=100.0, y=50.0, z=-80.0),
        strike_deg=35.0,
        dip_deg=65.0,
        length=520.0,
        height=310.0,
        thickness=16.0,
        warped_vein=vein,
    )
    base.update(overrides)
    return OrebodyConfig(**base)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def vein() -> WarpedVeinOrebody:
    ob = build_orebody(fixed_config())
    assert isinstance(ob, WarpedVeinOrebody)
    return ob


def _random_points(ob: WarpedVeinOrebody, n: int, seed: int = 0) -> np.ndarray:
    lo, hi = ob.bounding_box()
    rng = np.random.default_rng(seed)
    return rng.uniform(lo - 30.0, hi + 30.0, size=(n, 3))


def _mesh_edges(faces: np.ndarray) -> np.ndarray:
    return np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), axis=1)


# -- contracts --------------------------------------------------------------- #


def test_contract_split_is_honest(vein: WarpedVeinOrebody) -> None:
    assert isinstance(vein, ImplicitOrebody) and not isinstance(vein, AnalyticOrebody)
    assert vein.distance_contract is DistanceContract.DERIVED_APPROXIMATE_CLEARANCE
    assert not hasattr(vein, "signed_distance")  # never mislabelled as an SDF
    for analytic in (
        build_orebody(ScenarioCreate().orebody),
        build_orebody(
            ScenarioCreate().orebody.model_copy(update={"orebody_type": OrebodyType.ELLIPSOID})
        ),
    ):
        assert isinstance(analytic, AnalyticOrebody)
        assert analytic.distance_contract is DistanceContract.EXACT_METRIC_SDF
    assert isinstance(build_orebody(ScenarioCreate().orebody), TabularOrebody)
    info = vein.clearance_info()
    assert info["contract"] == "DERIVED_APPROXIMATE_CLEARANCE"
    assert info["exact"] is False and info["usableForHardEngineeringBuffers"] is False
    assert info["maxAbsErrorEstimateM"] > 0


def test_generic_interface_has_no_tabular_assumptions() -> None:
    from minegen.world.orebody import Orebody

    assert "half_thickness" not in Orebody.__abstractmethods__
    assert not hasattr(Orebody, "footwall_point")
    assert hasattr(TabularOrebody, "footwall_point")
    assert not hasattr(WarpedVeinOrebody, "footwall_point")
    assert not hasattr(WarpedVeinOrebody, "half_thickness")


# -- authoritative implicit solid ------------------------------------------- #


def test_same_config_same_phi_and_contains_no_hidden_rng(vein: WarpedVeinOrebody) -> None:
    other = build_orebody(fixed_config())
    pts = _random_points(vein, 20_000)
    np.testing.assert_array_equal(vein.level(pts), other.level(pts))
    np.testing.assert_array_equal(vein.contains(pts), other.contains(pts))
    # batch-vectorized, finite, membership == (φ <= 0) and nothing else
    phi = vein.level(pts)
    assert phi.shape == (20_000,) and np.all(np.isfinite(phi))
    np.testing.assert_array_equal(vein.contains(pts), phi <= 0.0)
    assert vein.contains(pts.reshape(100, 200, 3)).shape == (100, 200)


def test_inside_outside_boundary_cases(vein: WarpedVeinOrebody) -> None:
    m = vein.morphology
    # centre of the planform: inside on the mid-surface, outside past thickness
    w_mid, h_scale, pk = m.plane_terms(np.array([0.0]), np.array([0.0]))
    h = float(h_scale[0] * math.sqrt(1.0 - pk[0]))
    on_mid = vein.to_world(np.array([[0.0, 0.0, float(w_mid[0])]]))
    assert vein.contains(on_mid)[0] and vein.level(on_mid)[0] < 0
    just_out = vein.to_world(np.array([[0.0, 0.0, float(w_mid[0]) + h + 0.01]]))
    just_in = vein.to_world(np.array([[0.0, 0.0, float(w_mid[0]) + h - 0.01]]))
    boundary = vein.to_world(np.array([[0.0, 0.0, float(w_mid[0]) + h]]))
    assert not vein.contains(just_out)[0] and vein.contains(just_in)[0]
    assert abs(float(vein.level(boundary)[0])) < 1e-6
    # far beyond the outline: outside whatever w
    far = vein.to_world(np.array([[2000.0, 0.0, 0.0], [0.0, 2000.0, 0.0]]))
    assert not vein.contains(far).any()


def test_morphology_is_real_not_metadata(vein: WarpedVeinOrebody) -> None:
    m = vein.morphology
    d = m.diagnostics()
    # variable thickness / pinch and swell
    assert d["maxInteriorThicknessMultiplier"] - d["minInteriorThicknessMultiplier"] > 0.15
    assert d["maxInteriorThickness"] > d["minInteriorThickness"] * 1.15
    # warp: the mid-surface actually moves by a good part of the amplitude
    assert d["midSurfaceMax"] - d["midSurfaceMin"] > 0.5 * m.amplitude
    # lateral deviation: centreline shifts along dip
    assert d["centerlineShiftMax"] - d["centerlineShiftMin"] > 0.5 * m.deviation
    # asymmetric outline
    assert max(d["strikeEdgeAsymmetry"], d["dipEdgeAsymmetry"]) > 0.05
    # one connected principal solid
    assert d["planformConnectedComponents"] == 1


def test_internal_thickness_floor_holds_everywhere_in_interior(vein: WarpedVeinOrebody) -> None:
    """The pinch floor is guaranteed by construction (V ≤ 1 − floor): sample
    the interior densely and check the ACTUAL thickness, not the config."""
    m = vein.morphology
    lo, hi = m.local_bounds()
    u = np.linspace(lo[0], hi[0], 400)
    v = np.linspace(lo[1], hi[1], 300)
    p = m.planform(u[:, None], v[None, :])
    h = m.half_thickness(u[:, None], v[None, :])
    interior = p < 0.8
    floor = m.vein.pinch_floor_ratio * m.half_thickness_nominal
    assert interior.sum() > 1000
    # taper multiplies by sqrt(1 − P^k) ≥ sqrt(1 − 0.8^4) at P = 0.8
    assert np.min(h[interior]) >= floor * math.sqrt(1.0 - 0.8**m.taper_exponent) - 1e-9
    assert np.min(h[p < 0.5]) >= 0.99 * floor
    # terminations taper to zero at the outline
    assert np.all(h[p >= 1.0] == 0.0)


def test_low_frequency_only(vein: WarpedVeinOrebody) -> None:
    """No high-frequency ripple: the thickness along strike through the
    centre has few extrema (bounded by the maximum wavenumber)."""
    m = vein.morphology
    u = np.linspace(-m.half_length, m.half_length, 2000)
    h = m.half_thickness(u, np.zeros_like(u))
    inside = h > 0
    dh = np.diff(h[inside])
    extrema = int(np.sum(np.sign(dh[1:]) != np.sign(dh[:-1])))
    assert extrema <= 8


def test_no_overhang_single_valued_vein(vein: WarpedVeinOrebody) -> None:
    """Along any local normal line the inside set is one interval."""
    m = vein.morphology
    rng = np.random.default_rng(5)
    lo, hi = m.local_bounds()
    for _ in range(50):
        u, v = rng.uniform(lo[0], hi[0]), rng.uniform(lo[1], hi[1])
        w = np.linspace(lo[2], hi[2], 600)
        inside = m.level_local(np.column_stack([np.full_like(w, u), np.full_like(w, v), w])) <= 0
        changes = int(np.sum(inside[1:] != inside[:-1]))
        assert changes in (0, 2)


# -- bounding box ------------------------------------------------------------ #


def test_bounding_box_contains_solid_and_mesh(vein: WarpedVeinOrebody) -> None:
    lo, hi = vein.bounding_box()
    assert np.all(np.isfinite(lo)) and np.all(np.isfinite(hi)) and np.all(hi > lo)
    pts = _random_points(vein, 200_000, seed=3)
    inside = vein.contains(pts)
    assert inside.sum() > 100
    assert np.all(pts[inside] >= lo - 1e-9) and np.all(pts[inside] <= hi + 1e-9)
    verts, _ = vein.mesh()
    assert np.all(verts >= lo - 1e-6) and np.all(verts <= hi + 1e-6)


# -- volume ------------------------------------------------------------------ #


def test_volume_is_deterministic_positive_and_converges(vein: WarpedVeinOrebody) -> None:
    v1 = vein.volume()
    assert v1 > 0 and vein.volume() == v1
    finer = vein.morphology.volume(0.5)
    assert abs(finer - v1) / v1 < VOLUME_RELATIVE_TOLERANCE
    # independent 3-D check: count lattice cells of the authoritative solid
    lo, hi = vein.morphology.local_bounds()
    su, sv, sw = 4.0, 4.0, 0.5
    u = np.arange(lo[0] + su / 2, hi[0], su)
    v = np.arange(lo[1] + sv / 2, hi[1], sv)
    w = np.arange(lo[2] + sw / 2, hi[2], sw)
    grid = np.stack(np.meshgrid(u, v, w, indexing="ij"), axis=-1).reshape(-1, 3)
    counted = float(np.count_nonzero(vein.morphology.level_local(grid) <= 0)) * su * sv * sw
    assert abs(counted - v1) / v1 < 0.02
    # and the closed derived mesh encloses the same volume (tessellation error)
    verts, faces = vein.mesh()
    rel = verts[faces] - vein.center
    signed = float(np.sum(np.einsum("ij,ij->i", rel[:, 0], np.cross(rel[:, 1], rel[:, 2])))) / 6
    assert signed > 0 and abs(signed - v1) / v1 < 0.02
    assert vein.to_dict()["volumeMethod"]["semantics"].startswith("geometric")


# -- derived mesh ------------------------------------------------------------ #


def test_mesh_is_deterministic_watertight_finite_and_on_the_surface(
    vein: WarpedVeinOrebody,
) -> None:
    verts, faces = vein.mesh()
    v2, f2 = build_orebody(fixed_config()).mesh()
    assert np.array_equal(verts, v2) and np.array_equal(faces, f2)
    assert np.all(np.isfinite(verts)) and faces.dtype == np.int32
    assert faces.min() >= 0 and faces.max() < verts.shape[0]
    # watertight: every undirected edge is shared by exactly two triangles
    _, counts = np.unique(_mesh_edges(faces), axis=0, return_counts=True)
    assert np.all(counts == 2)
    # no degenerate triangles
    tri = verts[faces]
    areas = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
    assert np.min(areas) > 1e-9
    # vertices lie on φ = 0 within the lattice resolution
    diag = float(np.linalg.norm(vein.lattice.spacing))
    assert float(np.max(np.abs(vein.approximate_clearance(verts)))) <= diag
    assert float(np.median(np.abs(vein.level(verts)))) < 0.05
    # transport budget
    assert 2_000 < verts.shape[0] < 100_000 and faces.shape[0] < 200_000


def test_mesh_world_transform_matches_local(vein: WarpedVeinOrebody) -> None:
    from scipy.spatial import cKDTree

    local_verts, _ = vein.derived.mesh_local
    verts, _ = vein.mesh()
    # every world vertex is the rigid image of a local isosurface vertex
    # (mm rounding + re-weld may drop a few coincident ones, never add)
    assert verts.shape[0] <= local_verts.shape[0]
    dist, _ = cKDTree(local_verts).query(vein.to_local(verts))
    assert float(np.max(dist)) < 2e-3
    lo, hi = vein.morphology.local_bounds()
    assert np.all(local_verts >= lo - 1e-6) and np.all(local_verts <= hi + 1e-6)


# -- derived clearance ------------------------------------------------------- #


def test_clearance_sign_agrees_with_contains_and_is_metric_scale(
    vein: WarpedVeinOrebody,
) -> None:
    pts = _random_points(vein, 100_000, seed=11)
    inside = vein.contains(pts)
    d = vein.approximate_clearance(pts)
    assert d.shape == (100_000,) and np.all(np.isfinite(d))
    np.testing.assert_array_equal(d <= 0.0, inside)
    # metric scale: far points report roughly their distance to the envelope
    lo, hi = vein.bounding_box()
    far = np.array([[lo[0] - 200.0, 0.5 * (lo[1] + hi[1]), 0.5 * (lo[2] + hi[2])]])
    assert 150.0 < float(vein.approximate_clearance(far)[0]) < 800.0
    # interior points are negative by about their depth below the surface
    m = vein.morphology
    w_mid, _, _ = m.plane_terms(np.array([0.0]), np.array([0.0]))
    centre = vein.to_world(np.array([[0.0, 0.0, float(w_mid[0])]]))
    assert -20.0 < float(vein.approximate_clearance(centre)[0]) < -3.0


def test_membership_never_comes_from_the_clearance(vein: WarpedVeinOrebody) -> None:
    """Points within one lattice cell of the boundary are exactly where the
    EDT can disagree with φ; membership must follow φ there, never the
    lattice."""
    m = vein.morphology
    rng = np.random.default_rng(2)
    u = rng.uniform(-100.0, 100.0, 5000)
    v = rng.uniform(-80.0, 80.0, 5000)
    w_mid, h_scale, pk = m.plane_terms(u, v)
    h = h_scale * np.sqrt(np.clip(1.0 - pk, 0.0, None))
    w = w_mid + h + rng.uniform(-1.0, 1.0, 5000)  # straddling the surface
    pts = vein.to_world(np.column_stack([u, v, w]))
    phi_inside = vein.level(pts) <= 0.0
    np.testing.assert_array_equal(vein.contains(pts), phi_inside)
    np.testing.assert_array_equal(vein.approximate_clearance(pts) <= 0.0, phi_inside)


def test_analytic_exact_sdf_unchanged_by_phase19() -> None:
    cfg = ScenarioCreate().orebody
    tab = build_orebody(cfg)
    assert isinstance(tab, TabularOrebody)
    p = tab.center + tab.w * (tab.half_thickness + 7.0)
    assert float(tab.signed_distance(p[None, :])[0]) == pytest.approx(7.0)
    ell = build_orebody(cfg.model_copy(update={"orebody_type": OrebodyType.ELLIPSOID}))
    assert isinstance(ell, EllipsoidOrebody)
    q = ell.center + ell.u * (ell.semi_axes[0] + 5.0)
    assert float(ell.signed_distance(q[None, :])[0]) == pytest.approx(5.0, abs=1e-6)


# -- legacy design boundary (rule 135 / 140) --------------------------------- #


def test_legacy_evaluator_refuses_approximate_clearance() -> None:
    sc = realize_scenario(ScenarioPreset.RANDOM_WARPED_VEIN, 3, fault_count=1)
    world = generate_world(Scenario(**sc.model_dump()))
    with pytest.raises(ExactDistanceRequiredError):
        DesignCostEvaluator(world, sc.design)


# -- lazy derived geometry / budget ------------------------------------------ #


def test_construction_is_cheap_and_derivatives_are_lazy() -> None:
    ob = build_orebody(fixed_config())
    assert isinstance(ob, WarpedVeinOrebody)
    assert "derived" not in ob.__dict__  # cached_property not yet evaluated
    ob.bounding_box()
    ob.contains(np.array([[0.0, 0.0, 0.0]]))
    assert "derived" not in ob.__dict__
    ob.mesh()
    assert "derived" in ob.__dict__
    assert ob.lattice.cell_count <= MAX_GEOMETRY_CELLS


def test_geometry_budget_fails_explicitly() -> None:
    cfg = fixed_config(length=2000.0, height=1500.0, thickness=60.0)
    cfg = cfg.model_copy(
        update={"warped_vein": cfg.warped_vein.model_copy(update={"geometry_resolution": 2.0})}
    )
    with pytest.raises(WarpedVeinGeometryBudgetError):
        plan_lattice(WarpedVeinMorphology(cfg))
    with pytest.raises(WarpedVeinGeometryBudgetError):
        build_orebody(cfg)


def test_lattice_resolves_the_thickness_floor(vein: WarpedVeinOrebody) -> None:
    m = vein.morphology
    min_thickness = 2.0 * m.half_thickness_nominal * (1.0 - m.variability)
    assert vein.lattice.spacing[2] <= min_thickness / 3.0 + 1e-9
    assert vein.lattice.spacing[0] == m.vein.geometry_resolution


# -- persistence / schema ---------------------------------------------------- #


def test_resolved_morphology_round_trips_and_reproduces_geometry() -> None:
    sc = realize_scenario(ScenarioPreset.RANDOM_WARPED_VEIN, 12, fault_count=2)
    assert sc.orebody.orebody_type is OrebodyType.WARPED_VEIN
    assert sc.orebody.warped_vein is not None
    assert sc.orebody.warped_vein.shape_model_version == 1
    dumped = sc.model_dump_json(by_alias=True)
    assert '"shapeModelVersion":1' in dumped.replace(" ", "")
    restored = ScenarioCreate.model_validate_json(dumped)
    assert restored == sc
    a = build_orebody(sc.orebody)
    b = build_orebody(restored.orebody)
    pts = _random_points(a, 50_000)  # type: ignore[arg-type]
    np.testing.assert_array_equal(a.contains(pts), b.contains(pts))
    va, fa = a.mesh()
    vb, fb = b.mesh()
    assert np.array_equal(va, vb) and np.array_equal(fa, fb)
    assert a.to_dict() == b.to_dict()
    # world generation is a pure function of the document
    w1 = generate_world(Scenario(**sc.model_dump()))
    w2 = generate_world(Scenario(**restored.model_dump()))
    assert w1.orebody.to_dict() == w2.orebody.to_dict()
    assert np.array_equal(w1.fields.grade.values, w2.fields.grade.values)


def test_unsupported_shape_model_version_fails_explicitly() -> None:
    raw = json.loads(fixed_config().model_dump_json(by_alias=True))
    raw["warpedVein"]["shapeModelVersion"] = 2
    with pytest.raises(ValidationError, match="unsupported warped-vein shapeModelVersion"):
        OrebodyConfig.model_validate(raw)


def test_warped_vein_requires_resolved_morphology_and_forbids_it_elsewhere() -> None:
    with pytest.raises(ValidationError, match="requires a resolved warpedVein"):
        OrebodyConfig(
            orebody_type=OrebodyType.WARPED_VEIN,
            center=Point3D(x=0, y=0, z=-100),
            strike_deg=0,
            dip_deg=60,
            length=400,
            height=200,
            thickness=10,
        )
    with pytest.raises(ValidationError, match="only valid for orebodyType WARPED_VEIN"):
        fixed_config(orebody_type=OrebodyType.TABULAR)
    with pytest.raises(ValidationError, match="thicknessVariability"):
        cfg = fixed_config()
        WarpedVeinConfig(
            **{
                **cfg.warped_vein.model_dump(),  # type: ignore[union-attr]
                "thickness_variability": 0.7,
                "pinch_floor_ratio": 0.5,
            }
        )
    with pytest.raises(ValidationError):
        HarmonicMode(ku=0, kv=0, weight=0.5)
    with pytest.raises(ValidationError):
        HarmonicMode(ku=4, kv=0, weight=0.5)  # above the low-order bound


def test_schema_version_stays_2_and_analytic_documents_are_unchanged() -> None:
    from minegen.core.models import SCENARIO_SCHEMA_VERSION

    assert SCENARIO_SCHEMA_VERSION == 2
    doc = json.loads(ScenarioCreate().model_dump_json(by_alias=True, exclude_none=True))
    assert "warpedVein" not in doc["orebody"]
    assert Scenario(**ScenarioCreate().model_dump()).schema_version == 2


# -- scene / slice integration ----------------------------------------------- #


@pytest.fixture(scope="module")
def vein_world() -> tuple[Scenario, object]:
    sc = realize_scenario(ScenarioPreset.RANDOM_WARPED_VEIN, 21, fault_count=1)
    scenario = Scenario(**sc.model_dump())
    return scenario, generate_world(scenario)


def test_scene_ships_backend_mesh_as_the_only_orebody_geometry(vein_world: tuple) -> None:
    scenario, world = vein_world
    scene = build_scene(scenario, world)
    ob = scene["orebody"]
    assert ob["type"] == "WARPED_VEIN"
    assert ob["distanceContract"] == "DERIVED_APPROXIMATE_CLEARANCE"
    assert ob["shapeModelVersion"] == 1
    assert ob["meshVertices"] * 3 == len(ob["positions"])
    assert ob["meshTriangles"] * 3 == len(ob["indices"])
    assert ob["morphology"]["planformConnectedComponents"] == 1
    assert "nominalHalfExtents" in ob and "halfExtents" not in ob
    assert scene["stats"]["orebody"]["volumeM3"] > 0
    for banned in ("tonnes", "resource", "reserve"):
        assert banned not in json.dumps(ob).lower()


def test_grade_slice_mask_follows_the_irregular_solid(vein_world: tuple) -> None:
    scenario, world = vein_world
    grid = world.fields.grid
    zc = grid.axis_centers(2)
    k = int(np.argmin(np.abs(zc - world.orebody.center[2])))
    mask, semantics = slice_mask(world, "grade", "z", k)
    assert semantics == MASK_OREBODY_INTERSECTION_BELOW_TERRAIN
    assert mask.any()
    centers = grid.plane_centers(2, k)
    lo, hi = world.orebody.bounding_box()
    half = grid.cell_half_diagonal
    # nothing shown beyond the conservative envelope (never invents ore)
    reach = np.all((centers >= lo - half) & (centers <= hi + half), axis=-1)
    assert not np.any(mask & ~reach)
    # every shown cell really intersects the authoritative solid (dense check)
    offsets = grid.cell_subsample_offsets(7)
    shown = centers[mask]
    dense = world.orebody.contains((shown[:, None, :] + offsets[None, :, :]).reshape(-1, 3))
    assert np.all(dense.reshape(-1, offsets.shape[0]).any(axis=1))
    # the mask is an irregular footprint, not a rectangle: compare against the
    # analytic slab of the same nominal dimensions
    nominal = build_orebody(
        scenario.orebody.model_copy(
            update={"orebody_type": OrebodyType.TABULAR, "warped_vein": None}
        )
    )
    slab = cells_intersect_orebody(grid, centers, nominal)
    assert np.any(mask != slab)


def test_cells_intersect_uses_only_contains_for_implicit_bodies(vein: WarpedVeinOrebody) -> None:
    """The implicit route never calls the approximate clearance."""
    from minegen.world.field_grid import FieldGrid

    grid = FieldGrid.from_extent(
        (-600.0, -600.0, -300.0), (600.0, 600.0, 400.0), (10.0, 10.0, 10.0)
    )
    calls = {"clearance": 0}
    original = vein.approximate_clearance

    def spy(points: np.ndarray) -> np.ndarray:
        calls["clearance"] += 1
        return original(points)

    vein.approximate_clearance = spy  # type: ignore[method-assign]
    try:
        k = int(np.argmin(np.abs(grid.axis_centers(2) - vein.center[2])))
        hit = cells_intersect_orebody(grid, grid.plane_centers(2, k), vein)
    finally:
        del vein.approximate_clearance
    assert hit.any() and calls["clearance"] == 0


# -- realization -------------------------------------------------------------- #


def test_realized_morphology_is_valid_on_many_seeds() -> None:
    for seed in range(1, 25):
        sc = realize_scenario(ScenarioPreset.RANDOM_WARPED_VEIN, seed, fault_count=0)
        ok, reason = warped_vein_morphology_valid(sc.orebody)
        assert ok, f"seed {seed}: {reason}"
        assert sc.orebody.warped_vein is not None
        assert all(
            m.ku <= 2 and m.kv <= 3
            for group in (
                sc.orebody.warped_vein.warp_modes,
                sc.orebody.warped_vein.outline_modes,
                sc.orebody.warped_vein.thickness_modes,
                sc.orebody.warped_vein.deviation_modes,
            )
            for m in group
        )


def test_morphology_acceptance_rejects_pathological_candidates() -> None:
    # no asymmetry at all: symmetric outline modes, no lateral deviation
    cfg = fixed_config()
    vein = cfg.warped_vein
    assert vein is not None
    symmetric = vein.model_copy(
        update={
            "outline_irregularity": 0.0,
            "outline_modes": [M(ku=2, kv=0, weight=1.0)],
        }
    )
    ok, reason = warped_vein_morphology_valid(cfg.model_copy(update={"warped_vein": symmetric}))
    assert not ok and "asymmetric" in reason
    # no pinch/swell at all
    flat = vein.model_copy(update={"thickness_variability": 0.0})
    ok, reason = warped_vein_morphology_valid(cfg.model_copy(update={"warped_vein": flat}))
    assert not ok and "pinch/swell" in reason
    # geometry budget
    ok, reason = warped_vein_morphology_valid(
        fixed_config(length=2000.0, height=1500.0, thickness=60.0).model_copy(
            update={"warped_vein": vein.model_copy(update={"geometry_resolution": 2.0})}
        )
    )
    assert not ok and "budget" in reason
