"""Phase 20A — parametric whole-mine layout search (layout-v2).

Covers the directive §51 backend test list: required-level reuse, the level
service predicate, frozen finite enumeration, family coupling
(spiral radius, switchback leg length, non-uniform levels), delivered
centerline validation, family-signature diagnostics, EXACT vs CONSERVATIVE
clearance (including an empirical bound check), WARPED_VEIN acceptance
through layout-v2 while the legacy pipeline stays unchanged, effective-ramp
splitting at level connection points, determinism and finite serialization.
"""

from __future__ import annotations

import json
import math
from dataclasses import replace
from itertools import pairwise

import numpy as np
import pytest

from minegen.core.enums import ScenarioPreset
from minegen.core.models import LayoutV2Config, Scenario, SpiralFamilyGrid
from minegen.design.cost_field import (
    CONSERVATIVE_CLEARANCE_DIAGONAL_FACTOR,
    ConservativeClearance,
    DesignCostEvaluator,
    ExactDistanceRequiredError,
    clearance_policy_for,
)
from minegen.design.progress import ProgressEvent
from minegen.design.targets import generate_level_elevations, level_id
from minegen.layout.families import (
    FAMILY_ORDER,
    CandidateParams,
    FamilyInfeasible,
    InfeasibleReason,
    LayoutContext,
    RampFamily,
    build_family,
    build_footwall_track,
    enumerate_candidates,
)
from minegen.layout.geometry import analyze_centerline, find_crossing, insert_vertices, split_at
from minegen.layout.levels import LevelSections, RequiredLevel, required_levels
from minegen.layout.search import (
    SOURCE_KIND_PARAMETRIC_V2,
    CandidateStatus,
    LayoutSearchResult,
    LayoutV2Search,
    level_service,
    materialize_effective_ramp,
)
from minegen.services.scenario_realizer import realize_scenario
from minegen.world.orebody import ImplicitOrebody
from minegen.world.synthetic_world import SyntheticWorld, generate_world

from .conftest import small_scenario

# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def tabular() -> tuple[Scenario, SyntheticWorld]:
    sc = small_scenario()
    return sc, generate_world(sc)


@pytest.fixture(scope="module")
def tabular_search(
    tabular: tuple[Scenario, SyntheticWorld],
) -> tuple[LayoutV2Search, LayoutSearchResult]:
    sc, world = tabular
    search = LayoutV2Search(sc, world)
    return search, search.run()


@pytest.fixture(scope="module")
def warped() -> tuple[Scenario, SyntheticWorld]:
    sc = Scenario(
        **realize_scenario(ScenarioPreset.RANDOM_WARPED_VEIN, 301, fault_count=1).model_dump()
    )
    return sc, generate_world(sc)


@pytest.fixture(scope="module")
def warped_search(
    warped: tuple[Scenario, SyntheticWorld],
) -> tuple[LayoutV2Search, LayoutSearchResult]:
    sc, world = warped
    search = LayoutV2Search(sc, world)
    return search, search.run()


def _context(
    sc: Scenario, world: SyntheticWorld, search: LayoutV2Search, **cfg_overrides: object
) -> LayoutContext:
    cfg = sc.layout.model_copy(update=cfg_overrides) if cfg_overrides else sc.layout
    levels = required_levels(
        world.orebody,
        sc.mining.sublevel_interval,
        sc.design.top_mining_margin,
        sc.design.bottom_mining_margin,
    )
    sections = LevelSections(world.orebody, levels, cfg.section_sampling_spacing)
    track = build_footwall_track(world.orebody, sections)
    assert track is not None
    return LayoutContext(
        np.array(sc.portal.as_tuple(), dtype=np.float64)
        if sc.portal is not None
        else _portal(search),
        sections.serviceable(),
        sections,
        track,
        sc.ramp,
        cfg,
        sc.world.size_x / 2.0,
        sc.world.size_y / 2.0,
    )


def _portal(search: LayoutV2Search) -> np.ndarray:
    from minegen.design.targets import default_portal

    return np.asarray(default_portal(search.scenario, search.world.orebody, search.world.terrain))


# --------------------------------------------------------------------------- #
# required levels
# --------------------------------------------------------------------------- #


def test_required_levels_reuse_the_existing_generator(
    tabular: tuple[Scenario, SyntheticWorld],
) -> None:
    sc, world = tabular
    levels = required_levels(
        world.orebody,
        sc.mining.sublevel_interval,
        sc.design.top_mining_margin,
        sc.design.bottom_mining_margin,
    )
    expected = generate_level_elevations(
        world.orebody,
        sc.mining.sublevel_interval,
        sc.design.top_mining_margin,
        sc.design.bottom_mining_margin,
    )
    assert [lv.elevation for lv in levels] == [float(z) for z in expected]
    assert [lv.level_id for lv in levels] == [level_id(i, z) for i, z in enumerate(expected)]
    assert [lv.index for lv in levels] == list(range(len(expected)))
    assert levels[0].level_id == "L01"
    # descending
    assert all(a.elevation > b.elevation for a, b in pairwise(levels))


def test_required_levels_generic_for_warped_vein(warped: tuple[Scenario, SyntheticWorld]) -> None:
    sc, world = warped
    assert isinstance(world.orebody, ImplicitOrebody)
    levels = required_levels(
        world.orebody,
        sc.mining.sublevel_interval,
        sc.design.top_mining_margin,
        sc.design.bottom_mining_margin,
    )
    assert len(levels) >= 2
    sections = LevelSections(world.orebody, levels, sc.layout.section_sampling_spacing)
    serviceable = sections.serviceable()
    # the generic generator works from the CONSERVATIVE bounding box, so a
    # WARPED_VEIN may own required levels with no orebody section; those are
    # reported, never silently dropped
    assert 2 <= len(serviceable) <= len(levels)
    assert set(lv.level_id for lv in serviceable) <= set(lv.level_id for lv in levels)


# --------------------------------------------------------------------------- #
# level service predicate
# --------------------------------------------------------------------------- #


def test_find_crossing_is_segment_interpolation_without_tolerance() -> None:
    pts = np.array([[0.0, 0.0, 10.0], [10.0, 0.0, 4.0], [20.0, 0.0, -2.0]])
    cr = find_crossing(pts, 1.0)
    assert cr is not None
    assert cr.edge_index == 1
    assert math.isclose(cr.t, 0.5)
    np.testing.assert_allclose(cr.point, [15.0, 0.0, 1.0])
    assert math.isclose(cr.chainage, math.hypot(10, 6) + 0.5 * math.hypot(10, 6))
    # exactly at a vertex
    cr4 = find_crossing(pts, 4.0)
    assert cr4 is not None and cr4.edge_index == 0 and math.isclose(cr4.t, 1.0)
    np.testing.assert_allclose(cr4.point, [10.0, 0.0, 4.0])
    # never reached, however close: no elevation tolerance
    assert find_crossing(pts, -2.0000001) is None
    assert find_crossing(pts, 10.0000001) is None


def test_level_service_records_every_unserved_reason(
    tabular: tuple[Scenario, SyntheticWorld],
) -> None:
    sc, world = tabular
    levels = required_levels(
        world.orebody,
        sc.mining.sublevel_interval,
        sc.design.top_mining_margin,
        sc.design.bottom_mining_margin,
    )
    sections = LevelSections(world.orebody, levels, 2.0)
    top, second = levels[0], levels[1]
    sec = sections.section(top)
    inside = sec.centroid
    # a vertical-ish line through the centroid of the top level that stops
    # above the second level
    pts = np.array(
        [
            [inside[0], inside[1], top.elevation + 20.0],
            [inside[0] + 1.0, inside[1], top.elevation - 5.0],
        ]
    )
    reach = 60.0
    fake_level = RequiredLevel("L99", 98, -5000.0)  # far below the orebody
    records, crossings = level_service(
        pts,
        [top, second, fake_level],
        LevelSections(world.orebody, [top, second, fake_level], 2.0),
        reach,
    )
    assert [r.level_id for r in records] == ["L01", "L02", "L99"]
    r_top, r_second, r_fake = records
    assert r_top.served and r_top.access_distance == 0.0 and r_top.unserved_reason is None
    assert r_top.connection_position is not None and r_top.connection_position[2] == top.elevation
    assert crossings[0] is not None and r_top.connection_chainage == crossings[0].chainage
    assert not r_second.served and r_second.unserved_reason == InfeasibleReason.NO_RL_CROSSING.value
    assert not r_fake.served
    assert r_fake.unserved_reason == InfeasibleReason.NO_OREBODY_SECTION_AT_LEVEL.value
    # far crossing: ACCESS_REACH_EXCEEDED with the measured distance
    far = np.array(
        [
            [inside[0] + 150.0, inside[1] + 150.0, top.elevation + 5.0],
            [inside[0] + 150.0, inside[1] + 150.0, top.elevation - 5.0],
        ]
    )
    far_records, _ = level_service(far, [top], sections, reach)
    assert not far_records[0].served
    assert far_records[0].unserved_reason == InfeasibleReason.ACCESS_REACH_EXCEEDED.value
    assert far_records[0].access_distance is not None and far_records[0].access_distance > reach
    # served exactly at the reach boundary (≤)
    exact, _ = level_service(far, [top], sections, far_records[0].access_distance)
    assert exact[0].served


def test_access_distance_is_an_upper_bound_within_sampling_error(
    tabular: tuple[Scenario, SyntheticWorld],
) -> None:
    sc, world = tabular
    levels = required_levels(
        world.orebody,
        sc.mining.sublevel_interval,
        sc.design.top_mining_margin,
        sc.design.bottom_mining_margin,
    )
    spacing = 2.0
    sec = LevelSections(world.orebody, levels, spacing).section(levels[1])
    rng = np.random.default_rng(3)
    z = levels[1].elevation
    # dense in-plane reference (0.25 m): its nearest inside sample is itself
    # an upper bound of the true in-plane distance, within 0.25·√2 of it
    lo, hi = world.orebody.bounding_box()
    xs = np.arange(lo[0] - 1.0, hi[0] + 1.0, 0.25)
    ys = np.arange(lo[1] - 1.0, hi[1] + 1.0, 0.25)
    gx, gy = np.meshgrid(xs, ys, indexing="ij")
    dense = np.column_stack([gx.ravel(), gy.ravel(), np.full(gx.size, z)])
    dense_inside = dense[world.orebody.contains(dense)][:, :2]
    from scipy.spatial import cKDTree

    dense_tree = cKDTree(dense_inside)
    dense_slack = 0.25 * math.sqrt(2.0)
    for _ in range(40):
        p = sec.centroid + rng.uniform(-120.0, 120.0, size=2)
        d = sec.access_distance(p)
        assert d >= 0.0
        if d == 0.0:
            assert bool(world.orebody.contains(np.array([[p[0], p[1], z]]))[0])
            continue
        # the returned point at distance d along p→nearest sample is inside
        s = sec.nearest_inside(p)
        q = p + (d / float(np.linalg.norm(s - p))) * (s - p)
        assert bool(world.orebody.contains(np.array([[q[0], q[1], z]]))[0])
        # never optimistic: d ≥ true distance ≥ dense reference − slack
        ref, _ = dense_tree.query(p)
        assert d >= float(ref) - dense_slack - 1e-9
        # and the in-plane 3-D exact SDF is a further lower bound
        exact_3d = float(world.orebody.signed_distance(np.array([[p[0], p[1], z]]))[0])
        assert exact_3d <= d + 1e-6
        # over-estimate stays within the sampling diagonal of the reference
        assert d - float(ref) <= spacing * math.sqrt(2.0) + dense_slack


# --------------------------------------------------------------------------- #
# enumeration
# --------------------------------------------------------------------------- #


def test_enumeration_is_finite_frozen_and_stable() -> None:
    cfg = LayoutV2Config()
    params = enumerate_candidates(cfg)
    spiral = (
        len(cfg.spiral.turns_per_level)
        * len(cfg.spiral.turn_senses)
        * len(cfg.spiral.entry_orientations_deg)
    )
    longitudinal = len(cfg.longitudinal.orientations) * len(cfg.longitudinal.sides)
    switchback = (
        len(cfg.switchback.legs_per_level)
        * len(cfg.switchback.principal_orientations_deg)
        * len(cfg.switchback.initial_turn_senses)
    )
    assert len(params) == (spiral + longitudinal + switchback) * len(cfg.target_gradients) == 68
    ids = [p.candidate_id for p in params]
    assert len(set(ids)) == len(ids)
    assert ids == [p.candidate_id for p in enumerate_candidates(LayoutV2Config())]
    # family order is frozen: SPIRAL, LONGITUDINAL, SWITCHBACK
    families = [p.family for p in params]
    order = [FAMILY_ORDER.index(f) for f in families]
    assert order == sorted(order)
    assert ids[0] == "SPIRAL-n1-CW-e-45-g0.120"
    assert ids[-1] == "SWITCHBACK-k2-p+20-CCW-g0.100"
    assert "LONGITUDINAL-STRIKE_POSITIVE-FOOTWALL-g0.120" in ids
    # a smaller declared grid shrinks the enumeration, no sampling involved
    small = LayoutV2Config(
        spiral=SpiralFamilyGrid(
            turns_per_level=[1.0], turn_senses=["CW"], entry_orientations_deg=[0.0]
        )
    )
    assert len(enumerate_candidates(small)) == (1 + longitudinal + switchback) * len(
        cfg.target_gradients
    )


def test_candidate_id_round_trips_parameters() -> None:
    p = CandidateParams(
        RampFamily.SPIRAL, 0.1, turns_per_level=1.5, turn_sense="CCW", entry_orientation_deg=-45.0
    )
    assert p.candidate_id == "SPIRAL-n1.5-CCW-e-45-g0.100"
    assert p.to_dict() == {
        "family": "SPIRAL",
        "targetGradient": 0.1,
        "turnsPerLevel": 1.5,
        "turnSense": "CCW",
        "entryOrientationDeg": -45.0,
    }


# --------------------------------------------------------------------------- #
# family coupling
# --------------------------------------------------------------------------- #


def test_spiral_radius_is_derived_from_gradient_and_level_interval(
    tabular: tuple[Scenario, SyntheticWorld],
    tabular_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    sc, world = tabular
    search, _ = tabular_search
    ctx = _context(sc, world, search)
    dz = ctx.levels[0].elevation - ctx.levels[1].elevation
    for n, g in [(1.0, 0.12), (1.5, 0.12), (1.0, 0.10)]:
        p = CandidateParams(
            RampFamily.SPIRAL, g, turns_per_level=n, turn_sense="CW", entry_orientation_deg=0.0
        )
        built = build_family(p, ctx)
        assert not isinstance(built, FamilyInfeasible), built
        assert math.isclose(built.derived["radius"], dz / (2.0 * math.pi * g * n))
    # n = 2 at g = 0.12 gives R = 16.6 m < R_min = 18 m → typed infeasibility
    p2 = CandidateParams(
        RampFamily.SPIRAL, 0.12, turns_per_level=2.0, turn_sense="CW", entry_orientation_deg=0.0
    )
    built2 = build_family(p2, ctx)
    assert isinstance(built2, FamilyInfeasible)
    assert built2.reason is InfeasibleReason.TURN_RADIUS
    assert dz / (2.0 * math.pi * 0.12 * 2.0) < sc.ramp.min_turn_radius


def test_spiral_rejects_non_uniform_level_intervals(
    tabular: tuple[Scenario, SyntheticWorld],
    tabular_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    sc, world = tabular
    search, _ = tabular_search
    ctx = _context(sc, world, search)
    levels = list(ctx.levels)
    levels[1] = RequiredLevel(levels[1].level_id, levels[1].index, levels[1].elevation - 3.0)
    ctx_bad = replace(ctx, levels=levels)
    p = CandidateParams(
        RampFamily.SPIRAL, 0.12, turns_per_level=1.0, turn_sense="CW", entry_orientation_deg=0.0
    )
    built = build_family(p, ctx_bad)
    assert isinstance(built, FamilyInfeasible)
    assert built.reason is InfeasibleReason.LEVEL_INTERVAL_NONUNIFORM


def test_switchback_leg_length_subtracts_the_hairpin_arc(
    tabular: tuple[Scenario, SyntheticWorld],
    tabular_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    sc, world = tabular
    search, _ = tabular_search
    ctx = _context(sc, world, search)
    dz = ctx.levels[0].elevation - ctx.levels[1].elevation
    for k, g in [(1, 0.12), (2, 0.12), (1, 0.10)]:
        p = CandidateParams(
            RampFamily.SWITCHBACK,
            g,
            legs_per_level=k,
            principal_orientation_deg=0.0,
            initial_turn_sense="CW",
        )
        built = build_family(p, ctx)
        assert not isinstance(built, FamilyInfeasible), built
        expected = (dz / k) / g - math.pi * sc.ramp.min_turn_radius
        assert math.isclose(built.derived["legLengthNominal"], expected)
        assert built.derived["hairpinRadius"] == sc.ramp.min_turn_radius
    # too many legs: derived straight leg drops below min_straight_length
    ctx_short = _context(sc, world, search, min_straight_length=60.0)
    p = CandidateParams(
        RampFamily.SWITCHBACK,
        0.12,
        legs_per_level=2,
        principal_orientation_deg=0.0,
        initial_turn_sense="CW",
    )
    built = build_family(p, ctx_short)
    assert isinstance(built, FamilyInfeasible) and built.reason is InfeasibleReason.LEG_TOO_SHORT


def test_every_candidate_starts_at_the_portal(
    tabular_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    _, res = tabular_search
    for c in res.candidates:
        if c.points is not None:
            np.testing.assert_allclose(c.points[0], res.portal, atol=1e-9)


# --------------------------------------------------------------------------- #
# delivered centerline validation and signatures
# --------------------------------------------------------------------------- #


def test_delivered_centerline_limits_hold_for_every_non_infeasible_candidate(
    tabular: tuple[Scenario, SyntheticWorld],
    tabular_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    sc, _ = tabular
    _, res = tabular_search
    checked = 0
    for c in res.candidates:
        if c.status == CandidateStatus.INFEASIBLE or c.diagnostics is None:
            continue
        d = c.diagnostics
        assert d.max_abs_gradient <= sc.ramp.max_gradient + 1e-9
        assert d.min_plan_radius is None or d.min_plan_radius >= sc.ramp.min_turn_radius - 0.05
        assert d.monotonic_descent
        assert d.max_local_turn_deg < 15.0  # tangent continuity at every join
        assert c.points is not None
        assert np.all(np.abs(c.points[:, 0]) <= sc.world.size_x / 2)
        assert np.all(np.abs(c.points[:, 1]) <= sc.world.size_y / 2)
        # every level served, once, exactly at its elevation
        assert c.served_count == len(c.level_service) == len(res.serviceable_ids)
        for rec in c.level_service:
            assert rec.connection_position is not None
            assert rec.connection_position[2] == rec.elevation
            assert rec.access_distance is not None and rec.access_distance <= res.access_reach
        checked += 1
    assert checked >= 3


def test_infeasible_candidates_carry_typed_reasons_and_are_never_ranked(
    tabular_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    _, res = tabular_search
    valid = {r.value for r in InfeasibleReason}
    infeasible = [c for c in res.candidates if c.status == CandidateStatus.INFEASIBLE]
    assert infeasible
    for c in infeasible:
        assert c.failure_reasons and set(c.failure_reasons) <= valid
        assert c.failure_detail
        assert c.rank is None and c.candidate_id not in res.ranking
    assert res.ranking and res.winner_id == res.ranking[0]
    assert all(res.candidate(i) is not None for i in res.ranking)
    assert [res.candidate(i).rank for i in res.ranking] == list(range(1, len(res.ranking) + 1))  # type: ignore[union-attr]
    # hard failures never become score terms: a detailed-stage failure keeps
    # its reason even though scores were computed for inspection
    hard = [c for c in infeasible if c.shortlisted]
    for c in hard:
        assert c.stage_reached == "DETAILED"
        assert c.failure_reasons


def test_family_signatures_are_quantitatively_distinct(
    tabular_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    _, res = tabular_search
    by_family: dict[RampFamily, list] = {f: [] for f in FAMILY_ORDER}
    for c in res.candidates:
        if c.diagnostics is not None and c.status != CandidateStatus.INFEASIBLE:
            by_family[c.params.family].append(c.diagnostics)
    spirals = by_family[RampFamily.SPIRAL]
    switchbacks = by_family[RampFamily.SWITCHBACK]
    assert spirals and switchbacks
    for d in spirals:
        assert d.cumulative_heading_change_deg > 720.0
        assert d.turn_direction_consistency > 0.95
        assert d.heading_reversal_count == 0
    for d in switchbacks:
        assert d.heading_reversal_count >= 3
        assert d.hairpin_run_count >= d.heading_reversal_count
    # longitudinal candidates are constructed even when the small world makes
    # them infeasible: their signature is one dominant axis, no hairpins
    longs = [
        c.diagnostics
        for c in res.candidates
        if c.params.family is RampFamily.LONGITUDINAL and c.diagnostics is not None
    ]
    assert longs
    for d in longs:
        assert d.cumulative_heading_change_deg < 200.0
        assert d.heading_reversal_count <= 1


def test_analyze_centerline_signature_on_synthetic_shapes() -> None:
    # straight ramp: no turning
    s = np.column_stack([np.zeros(11), np.linspace(0, 100, 11), np.linspace(0, -10, 11)])
    d = analyze_centerline(s)
    assert d.cumulative_heading_change_deg == 0.0 and d.min_plan_radius is None
    assert math.isclose(d.max_abs_gradient, 0.1)
    assert d.dominant_azimuths_deg[0] == 7.5  # the 0°–15° bin
    # two full CW turns of radius 30 m sampled every 3°: 239 interior
    # vertices → cumulative 717°, consistency 1, 0 reversals
    th = np.linspace(0, 4 * math.pi, 241)
    helix = np.column_stack([30 * np.sin(th), 30 * np.cos(th), -np.linspace(0, 40, 241)])
    h = analyze_centerline(helix)
    assert math.isclose(h.cumulative_heading_change_deg, 720.0 - 3.0, abs_tol=1e-6)
    assert h.signed_heading_change_deg > 0 and math.isclose(h.turn_direction_consistency, 1.0)
    assert h.heading_reversal_count == 0 and h.hairpin_run_count == 1
    assert math.isclose(h.min_plan_radius or 0.0, 30.0, rel_tol=1e-3)
    # one hairpin: straight north, 180° CW arc, straight south
    leg = np.column_stack([np.zeros(20), np.linspace(0, 100, 20), np.zeros(20)])
    phi = np.linspace(0, math.pi, 40)[1:]
    arc = np.column_stack([20 - 20 * np.cos(phi), 100 + 20 * np.sin(phi), np.zeros(39)])
    back = np.column_stack([np.full(19, 40.0), np.linspace(100, 0, 20)[1:], np.zeros(19)])
    hp = analyze_centerline(np.vstack([leg, arc, back]))
    assert hp.heading_reversal_count == 1 and hp.hairpin_run_count == 1
    assert math.isclose(hp.cumulative_heading_change_deg, 180.0, abs_tol=1e-6)


# --------------------------------------------------------------------------- #
# clearance policies
# --------------------------------------------------------------------------- #


def test_tabular_uses_the_exact_policy_and_legacy_evaluator_is_unchanged(
    tabular: tuple[Scenario, SyntheticWorld],
    tabular_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    sc, world = tabular
    search, res = tabular_search
    assert res.clearance_basis == "EXACT" and res.clearance_error_bound == 0.0
    policy = clearance_policy_for(world.orebody)
    assert policy.basis == "EXACT"
    legacy = DesignCostEvaluator(world, sc.design)
    pts = np.array([[0.0, 0.0, -30.0], [40.0, 20.0, -50.0], [100.0, -100.0, 20.0]])
    np.testing.assert_array_equal(legacy.orebody_distance(pts), world.orebody.signed_distance(pts))
    np.testing.assert_array_equal(
        search.evaluator.orebody_distance(pts), world.orebody.signed_distance(pts)
    )
    for c in res.candidates:
        if c.clearance is not None:
            assert c.clearance.basis == "EXACT"
            assert c.clearance.error_bound is None and c.clearance.approximate_minimum is None


def test_conservative_clearance_bound_is_derived_and_empirically_safe(
    warped: tuple[Scenario, SyntheticWorld],
) -> None:
    _, world = warped
    ob = world.orebody
    assert isinstance(ob, ImplicitOrebody)
    policy = ConservativeClearance.for_orebody(ob)
    spacing = np.asarray(ob.clearance_info()["latticeSpacing"], dtype=np.float64)
    assert policy.basis == "CONSERVATIVE"
    assert math.isclose(
        policy.error_bound, CONSERVATIVE_CLEARANCE_DIAGONAL_FACTOR * float(np.linalg.norm(spacing))
    )
    assert policy.error_bound > 0.0
    assert clearance_policy_for(ob).basis == "CONSERVATIVE"
    # empirical check on the derived surface mesh (vertices lie on φ = 0
    # within lattice resolution): the approximate clearance there is inside
    # ±error_bound, so the conservative clearance is ≤ 0 on the surface
    verts, _ = ob.mesh()
    approx = ob.approximate_clearance(verts)
    assert float(np.max(np.abs(approx))) <= policy.error_bound
    assert np.all(policy.signed_clearance(verts) <= 0.0)
    # random exterior points: the conservative clearance never exceeds the
    # distance to the nearest surface vertex (an upper bound of the true
    # distance), i.e. it never over-promises clearance
    lo, hi = ob.bounding_box()
    rng = np.random.default_rng(20)
    pts = rng.uniform(lo - 40.0, hi + 40.0, size=(4000, 3))
    outside = ~ob.contains(pts)
    from scipy.spatial import cKDTree

    nearest, _ = cKDTree(verts).query(pts[outside])
    assert np.all(policy.signed_clearance(pts[outside]) <= nearest + 1e-9)
    # sign agreement with membership is inherited from the approximation
    assert np.all(policy.signed_clearance(pts[~outside]) < 0.0)


def test_warped_vein_is_accepted_by_layout_v2_but_not_by_the_legacy_pipeline(
    warped: tuple[Scenario, SyntheticWorld],
    warped_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    sc, world = warped
    _, res = warped_search
    with pytest.raises(ExactDistanceRequiredError):
        DesignCostEvaluator(world, sc.design)
    assert res.clearance_basis == "CONSERVATIVE"
    assert res.clearance_error_bound > 0.0
    assert math.isclose(
        res.required_clearance,
        sc.design.orebody_exclusion_buffer
        + math.hypot(sc.ramp.tunnel_width / 2.0, sc.ramp.tunnel_height),
    )
    assert len(res.candidates) == 68
    assert res.shortlist  # candidates reached the detailed stage
    validated = [c for c in res.candidates if c.clearance is not None]
    assert validated
    for c in validated:
        cl = c.clearance
        assert cl is not None and cl.basis == "CONSERVATIVE"
        assert cl.error_bound == res.clearance_error_bound
        assert cl.approximate_minimum is not None
        assert math.isclose(cl.approximate_minimum - cl.error_bound, cl.conservative_minimum)
        assert cl.satisfied == (cl.conservative_minimum >= cl.required - 1e-9)
        if c.status == CandidateStatus.FEASIBLE:
            assert cl.satisfied
        d = cl.to_dict()
        assert set(d) >= {
            "clearanceBasis",
            "approximateMinimumClearance",
            "clearanceErrorBound",
            "conservativeMinimumClearance",
            "requiredClearance",
        }
    # the fixed seed 301 world has feasible parametric candidates and a winner
    assert res.winner_id is not None
    winner = res.candidate(res.winner_id)
    assert winner is not None and winner.served_count == len(res.serviceable_ids)


# --------------------------------------------------------------------------- #
# determinism, serialization, ranking, progress
# --------------------------------------------------------------------------- #


def test_search_is_deterministic_and_serializes_finite(
    tabular: tuple[Scenario, SyntheticWorld],
    tabular_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    sc, world = tabular
    _, res = tabular_search
    again = LayoutV2Search(sc, world).run()
    a, b = res.to_dict(), again.to_dict()
    a.pop("performance")
    b.pop("performance")
    assert a == b
    text = json.dumps(a, allow_nan=False)  # no NaN / inf anywhere (rule 34)
    assert len(text) > 1000
    assert a["candidateCount"] == 68 and a["layoutVersion"] == 1
    assert a["status"] == "SUCCESS" and a["winnerId"] == res.winner_id
    # geometry only for shortlisted candidates (§41: no duplication for
    # discarded candidates)
    for c in a["candidates"]:
        assert (c["centerline"] is not None) == c["shortlisted"]
        assert c["status"] in {"FEASIBLE", "INFEASIBLE", "NOT_VALIDATED"}
    assert all(lv["hasOrebodySection"] for lv in a["requiredLevels"])
    assert a["searchConfig"]["accessReach"] == sc.layout.access_reach


def test_ranking_is_feasibility_total_family_id(
    tabular_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    _, res = tabular_search
    ranked = [res.candidate(i) for i in res.ranking]
    assert all(c is not None and c.status == CandidateStatus.FEASIBLE for c in ranked)
    totals = [c.scores.total for c in ranked]  # type: ignore[union-attr]
    assert totals == sorted(totals)
    for c in ranked:
        assert c is not None and c.scores is not None
        w = res.config["weights"]
        assert math.isclose(
            c.scores.total,
            w["development"] * c.scores.development
            + w["geology"] * c.scores.geology
            + w["geometry"] * c.scores.geometry,
        )
        assert c.scores.development > 0 and c.scores.geology >= 0 and c.scores.geometry >= 0


def test_group_weights_reorder_the_ranking_deterministically(
    tabular: tuple[Scenario, SyntheticWorld],
) -> None:
    sc, world = tabular
    heavy = sc.model_copy(
        update={
            "layout": sc.layout.model_copy(
                update={"weights": sc.layout.weights.model_copy(update={"geometry": 50.0})}
            )
        }
    )
    res = LayoutV2Search(heavy, world).run()
    base = LayoutV2Search(sc, world).run()
    assert set(res.ranking) == set(base.ranking)  # feasibility is weight-independent
    for cid in res.ranking:
        c = res.candidate(cid)
        assert c is not None and c.scores is not None
        assert math.isclose(
            c.scores.total, c.scores.development + c.scores.geology + 50.0 * c.scores.geometry
        )


def test_progress_events_are_emitted_and_never_change_the_result(
    tabular: tuple[Scenario, SyntheticWorld],
    tabular_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    sc, world = tabular
    _, res = tabular_search
    events: list[ProgressEvent] = []
    again = LayoutV2Search(sc, world).run(events.append)
    assert again.ranking == res.ranking and again.winner_id == res.winner_id
    assert events and all(e.phase == "LAYOUT_V2" for e in events)
    assert events[-1].progress == 1.0 and events[-1].message == res.winner_id
    ids = {e.candidate_id for e in events if e.candidate_id}
    assert ids == {c.candidate_id for c in res.candidates}


# --------------------------------------------------------------------------- #
# effective ramp materialization
# --------------------------------------------------------------------------- #


def test_insert_and_split_preserve_geometry() -> None:
    pts = np.array([[0.0, 0.0, 10.0], [10.0, 0.0, 4.0], [20.0, 0.0, -2.0], [30.0, 0.0, -8.0]])
    # 7 → interior of edge 0 (new vertex); 4 → existing vertex; −5 → interior
    # of edge 2 (new vertex); −8 → the terminal vertex
    crossings = [find_crossing(pts, z) for z in (7.0, 4.0, -5.0, -8.0)]
    assert all(c is not None for c in crossings)
    new, idx = insert_vertices(pts, [c for c in crossings if c is not None])
    assert new.shape[0] == 6 and idx == [1, 2, 4, 5]
    np.testing.assert_allclose(new[idx][:, 2], [7.0, 4.0, -5.0, -8.0])
    pieces = split_at(new, idx)
    assert len(pieces) == 4
    for a, b in pairwise(pieces):
        np.testing.assert_array_equal(a[-1], b[0])
    total = sum(float(np.sum(np.linalg.norm(np.diff(p, axis=0), axis=1))) for p in pieces)
    assert math.isclose(total, float(np.sum(np.linalg.norm(np.diff(pts, axis=0), axis=1))))


def test_effective_ramp_splits_exactly_at_level_connections(
    tabular_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    search, res = tabular_search
    assert res.winner_id is not None
    winner = res.candidate(res.winner_id)
    assert winner is not None
    ramp = materialize_effective_ramp(res, winner, search.evaluator, "rev-test")
    assert ramp["status"] == "SUCCESS"
    assert ramp["sourceKind"] == SOURCE_KIND_PARAMETRIC_V2
    assert ramp["sourceRevision"] == "rev-test"
    assert ramp["candidateId"] == winner.candidate_id
    np.testing.assert_allclose(ramp["portal"], res.portal)
    segs = ramp["segments"]
    assert [s["levelId"] for s in segs] == res.serviceable_ids
    assert len(ramp["levelConnections"]) == len(segs)
    prev_end = None
    prev_tangent = None
    total = 0.0
    for s, rec, lv in zip(segs, winner.level_service, res.serviceable_levels, strict=True):
        pts = np.asarray(s["effectiveCenterline"]["points"]).reshape(-1, 3)
        assert pts.shape[0] == s["effectiveCenterline"]["pointCount"] >= 2
        assert s["effectiveSource"] == SOURCE_KIND_PARAMETRIC_V2 and s["smoothed"] is None
        # the segment ends exactly at the level connection point
        assert pts[-1, 2] == lv.elevation
        assert rec.connection_position is not None
        np.testing.assert_allclose(pts[-1], rec.connection_position, atol=1e-9)
        np.testing.assert_allclose(s["levelConnection"]["position"], rec.connection_position)
        assert s["levelConnection"]["chainage"] == rec.connection_chainage
        if prev_end is not None:
            np.testing.assert_array_equal(pts[0], prev_end)  # shared vertex
            np.testing.assert_allclose(s["boundaryTangents"]["start"], prev_tangent)
        prev_end = pts[-1]
        prev_tangent = s["boundaryTangents"]["end"]
        assert math.isclose(float(np.linalg.norm(s["boundaryTangents"]["end"])), 1.0)
        assert (
            s["report"]["valid"]
            and s["report"]["maxGradient"] <= search.scenario.ramp.max_gradient + 1e-9
        )
        total += s["report"]["rawLength"]
    assert prev_end is not None
    np.testing.assert_allclose(prev_end, winner.points[-1])  # type: ignore[index]
    assert math.isclose(ramp["totals"]["rawLength"], total)
    assert math.isclose(ramp["totals"]["rawLength"], winner.diagnostics.length3d, rel_tol=1e-9)  # type: ignore[union-attr]
    assert ramp["totals"]["segments"] == len(segs)
    assert ramp["clearance"]["clearanceBasis"] == "EXACT"
    json.dumps(ramp, allow_nan=False)
    # only FEASIBLE candidates can be materialized
    bad = next(c for c in res.candidates if c.status != CandidateStatus.FEASIBLE)
    with pytest.raises(ValueError, match="not FEASIBLE"):
        materialize_effective_ramp(res, bad, search.evaluator, "rev-test")


def test_effective_ramp_for_warped_vein_reports_conservative_clearance(
    warped_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    search, res = warped_search
    assert res.winner_id is not None
    winner = res.candidate(res.winner_id)
    assert winner is not None
    ramp = materialize_effective_ramp(res, winner, search.evaluator, "rev-wv")
    assert ramp["clearance"]["clearanceBasis"] == "CONSERVATIVE"
    assert ramp["clearance"]["clearanceErrorBound"] == res.clearance_error_bound
    assert ramp["clearance"]["conservativeMinimumClearance"] >= res.required_clearance - 1e-9
    assert len(ramp["segments"]) == len(res.serviceable_ids)
    json.dumps(ramp, allow_nan=False)
