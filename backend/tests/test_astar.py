"""Phase 04 gate tests: Hybrid-A* segment search (rules 47–55)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from minegen.core.models import FaultConfig, Point3D, RestrictedZone, TerrainConfig
from minegen.design.astar_3d import HybridAStar, SegmentStatus
from minegen.design.constraints import DesignContext
from minegen.design.cost_field import DesignCostEvaluator
from minegen.design.motion_primitives import Pose, Steering, azimuth_between
from minegen.design.targets import generate_access_targets, resolve_portal
from minegen.world.synthetic_world import generate_world
from tests.conftest import small_scenario


def flat_world(faults: list[FaultConfig] | None = None, zones: list[RestrictedZone] | None = None):  # type: ignore[no-untyped-def]
    """Flat terrain, orebody moved far away: a clean corridor at z ≈ −50."""
    sc = small_scenario(with_fault=False)
    sc.terrain = TerrainConfig(grid_spacing=10, base_elevation=100, relief=0, octaves=1)
    sc.geology.rock_quality.std = 0.0  # uniform rock: the only cost structure is what a test adds
    sc.orebody.center = Point3D(x=0.0, y=150.0, z=-120.0)
    sc.geology.faults = faults or []
    sc.design.restricted_zones = zones or []
    sc.design.search.max_expansions_per_candidate = 20000
    w = generate_world(sc)
    ev = DesignCostEvaluator(w, sc.design)
    return sc, w, ev, HybridAStar(ev, sc.ramp, sc.design.search)


# -- closed-key continuity (rule 47) ---------------------------------------


def test_closed_key_shares_cell_but_coordinates_stay_continuous() -> None:
    _sc, _, _, a = flat_world()
    p1 = Pose(12.3, -4.7, -50.2, math.radians(10.0))
    p2 = Pose(13.9, -1.1, -50.9, math.radians(8.0))  # same 5 m cell, same 1 m z bin, same bin
    assert a.key(p1, True) == a.key(p2, True)
    assert p1 != p2
    # a real search path: sample coordinates are never multiples of the grid
    a2 = a
    start = Pose(-100.0, 0.0, -50.0, math.pi / 2)
    r = a2.search(start, np.array([60.0, 0.0, -58.0]))
    assert r.success and r.path is not None
    pts = r.path.points
    assert not np.allclose(pts[:, 2] % 1.0, 0.0)  # z unsnapped
    assert (np.abs(pts[1:-1, 0] % 5.0) > 1e-6).any()


# -- whole-primitive evaluation (rule 50) -----------------------------------


def test_fault_core_crossing_primitive_is_penalized_between_endpoints() -> None:
    # thin fault core (2.5 m half-width) perpendicular to an eastward primitive
    fault = FaultConfig(
        origin=Point3D(x=3.5, y=0, z=-50),
        strike_deg=0,
        dip_deg=90,
        core_half_width=1.0,
        influence_half_width=1.2,
        core_penalty=500.0,
        damage_zone_penalty=0.0,
    )
    _, _, ev, a = flat_world(faults=[fault])
    prims = a.prims.expand(Pose(0.0, 0.0, -50.0, math.pi / 2))  # heading east, Lh 7.07
    straight = next(p for p in prims if p.steering is Steering.STRAIGHT and p.grade == 0.0)
    # endpoints are outside the core, an intermediate sample (x≈3.5) is inside
    ends = ev.fault_penalty(straight.samples[[0, -1]])[0]
    assert np.all(ends == 0.0)
    mids = ev.fault_penalty(straight.samples[1:-1])[0]
    assert mids.max() == pytest.approx(500.0)
    res = a.evaluate_primitives([straight], True)[0]
    assert res is not None
    # integrated cost carries the core penalty (trapezoid over 2 m samples)
    assert res[0] > 500.0 * 1.0  # at least one 2 m interval at ~half weight
    assert res[0] > 7.07 * 1.5  # far above the base-only cost


def test_restricted_zone_between_endpoints_rejects_primitive() -> None:
    zone = RestrictedZone(min=Point3D(x=3.0, y=-10, z=-60), max=Point3D(x=4.0, y=10, z=-40))
    _, _, _, a = flat_world(zones=[zone])
    prims = a.prims.expand(Pose(0.0, 0.0, -50.0, math.pi / 2))
    straight = next(p for p in prims if p.steering is Steering.STRAIGHT and p.grade == 0.0)
    assert not (3.0 <= straight.samples[0, 0] <= 4.0) and not (
        3.0 <= straight.samples[-1, 0] <= 4.0
    )
    assert a.evaluate_primitives([straight], True)[0] is None


def test_orebody_buffer_crossing_primitive_is_rejected() -> None:
    _sc, w, ev, a = flat_world()
    ob = w.orebody
    # walk along strike just outside the orebody, grazing the 5 m buffer mid-way
    mid = ob.center + (ob.half_thickness + 2.0) * ob.w  # inside the buffer (sdf = 2 < 5)
    heading = azimuth_between(np.zeros(3), ob.u)
    start = Pose(*(mid - 3.53 * ob.u), heading)
    prims = a.prims.expand(start)
    straight = next(p for p in prims if p.steering is Steering.STRAIGHT and p.grade == 0.0)
    sdf = ev.orebody_distance(straight.samples)
    assert (sdf > 0).all() and sdf.min() < 5.0  # outside the orebody, inside the buffer
    assert a.evaluate_primitives([straight], True)[0] is None


# -- portal transition (rule 52) ----------------------------------------------


def test_portal_cover_transition() -> None:
    sc, w, _, _ = flat_world()
    ctx = DesignContext.decline(sc.design.model_copy(update={"minimum_surface_cover": 15.0}))
    ev = DesignCostEvaluator(w, sc.design, ctx)
    a = HybridAStar(ev, sc.ramp, sc.design.search)
    surface = 100.0

    def prim_with_z(zs: list[float]):  # type: ignore[no-untyped-def]
        base = a.prims.expand(Pose(0.0, 0.0, surface, 0.0))[4]  # straight, any grade
        samples = base.samples.copy()
        samples[:, 2] = zs
        return base.__class__(**{**base.__dict__, "samples": samples})

    # shallow descent from the surface, cover never reaches 15 m: accepted, not established
    res = a.evaluate_primitives([prim_with_z([100, 99, 98, 97, 96])], False)[0]
    assert res is not None and res[1] is False
    # reaching 15 m cover inside the primitive: accepted, established
    res = a.evaluate_primitives([prim_with_z([90, 88, 86, 84, 82])], False)[0]
    assert res is not None and res[1] is True
    # once established, coming back up to < 15 m cover is rejected
    assert a.evaluate_primitives([prim_with_z([82, 83, 84, 85, 90])], True)[0] is None
    # not yet established and going back above the terrain is still rejected
    assert a.evaluate_primitives([prim_with_z([99, 100.5, 99, 98, 97])], False)[0] is None
    # full search from the surface establishes cover before finishing
    r = a.search(
        Pose(-100.0, 0.0, surface, math.pi / 2),
        np.array([120.0, 0.0, 72.0]),
        cover_established=False,
    )
    assert r.success and r.cover_established_at_end


# -- segment searches ----------------------------------------------------------


def test_flat_segment_is_straight_and_deterministic() -> None:
    _, _, _, a = flat_world()
    start = Pose(-100.0, 0.0, -50.0, math.pi / 2)
    target = np.array([60.0, 0.0, -50.0])
    r1 = a.search(start, target)
    r2 = a.search(start, target)
    assert r1.success and r1.path is not None
    assert all(p.steering is Steering.STRAIGHT for p in r1.path.primitives)
    assert r1.path.length == pytest.approx(160.0, abs=1e-6)
    assert float(np.linalg.norm(r1.end_pose.position - target)) < 1e-9  # type: ignore[union-attr]
    assert r1.path.to_dict() == r2.path.to_dict()  # type: ignore[union-attr]
    assert r1.cost == r2.cost and r1.diagnostics.expanded_states == r2.diagnostics.expanded_states


def test_descending_segment_reaches_target_exactly() -> None:
    sc = small_scenario(with_fault=True)
    w = generate_world(sc)
    ev = DesignCostEvaluator(w, sc.design)
    portal, gen = resolve_portal(sc, w)
    ts = generate_access_targets(
        w, sc.design, sc.ramp, sc.mining.sublevel_interval, ev, portal, gen
    )
    c = ts.levels[0].candidates[2]
    sc.design.search.max_expansions_per_candidate = 20000
    a = HybridAStar(ev, sc.ramp, sc.design.search)
    start = Pose(
        float(portal[0]), float(portal[1]), float(portal[2]), azimuth_between(portal, c.position)
    )
    r = a.search(start, c.position)
    assert r.status is SegmentStatus.SUCCESS
    assert r.path is not None and r.end_pose is not None
    assert float(np.linalg.norm(r.end_pose.position - c.position)) < 1e-9
    assert r.path.max_grade <= sc.ramp.max_gradient + 1e-9
    assert r.path.min_radius >= sc.ramp.min_turn_radius - 1e-9
    # length equals the grade-limited lower bound: a perfect max-grade decline
    dz = portal[2] - c.position[2]
    assert r.path.length == pytest.approx(dz * math.sqrt(1 + 0.12**2) / 0.12, rel=0.01)
    assert r.cost >= r.diagnostics.admissible_bound
    d = r.diagnostics.to_dict()
    for k in ("expandedStates", "generatedStates", "closedStates", "peakOpenSize", "elapsedMs"):
        assert d[k] > 0


def test_restricted_zone_causes_detour() -> None:
    zone = RestrictedZone(min=Point3D(x=-30, y=-40, z=-80), max=Point3D(x=-10, y=40, z=-20))
    _, _, _, a_free = flat_world()
    _, _, _, a_blocked = flat_world(zones=[zone])
    start, target = Pose(-100.0, 0.0, -50.0, math.pi / 2), np.array([60.0, 0.0, -50.0])
    free, blocked = a_free.search(start, target), a_blocked.search(start, target)
    assert free.success and blocked.success and blocked.path is not None
    assert blocked.path.length > free.path.length + 10.0  # type: ignore[union-attr]
    pts = blocked.path.points
    inside = (pts[:, 0] >= -30) & (pts[:, 0] <= -10) & (np.abs(pts[:, 1]) <= 40)
    assert not inside.any()


def test_high_fault_penalty_routes_around_the_fault() -> None:
    def fault(core_penalty: float) -> FaultConfig:
        return FaultConfig(
            origin=Point3D(x=-20, y=0, z=-50),
            strike_deg=0,
            dip_deg=90,
            core_half_width=2.5,
            influence_half_width=5.0,
            core_penalty=core_penalty,
            damage_zone_penalty=core_penalty / 5,
        )

    _, _, _ev_cheap, a_cheap = flat_world(faults=[fault(0.0)])
    _, _, _ev_dear, a_dear = flat_world(faults=[fault(40.0)])
    start, target = Pose(-100.0, 0.0, -50.0, math.pi / 2), np.array([60.0, 30.0, -50.0])
    # the fault plane x = −20 spans the whole world; it cannot be avoided entirely,
    # so the expensive run must minimize exposure: fewer samples in the core
    cheap, dear = a_cheap.search(start, target), a_dear.search(start, target)
    assert cheap.success and dear.success
    exp_cheap = np.sum(np.abs(cheap.path.points[:, 0] + 20) <= 2.5)  # type: ignore[union-attr]
    exp_dear = np.sum(np.abs(dear.path.points[:, 0] + 20) <= 2.5)  # type: ignore[union-attr]
    assert exp_dear <= exp_cheap
    # with the generalized cost, crossing perpendicular (shortest exposure) is preferred
    # the expensive run pays for the unavoidable crossing but not for a long wander:
    # one perpendicular core crossing costs ≈ 40/m × 5 m (+ damage zones ≈ 8/m × 5 m)
    assert 0.0 < dear.cost - cheap.cost < 2.0 * (40.0 * 5.0 + 8.0 * 5.0)
    assert dear.path.length < cheap.path.length + 60.0  # type: ignore[union-attr]


def test_sealed_target_fails_without_relaxing_constraints() -> None:
    box = RestrictedZone(min=Point3D(x=40, y=-20, z=-80), max=Point3D(x=80, y=20, z=-20))
    sc, _, _, a = flat_world(zones=[box])
    sc.design.search.max_expansions_per_candidate = 400
    a = HybridAStar(a.ev, sc.ramp, sc.design.search)
    before = (sc.ramp.model_dump(), sc.design.model_dump())
    r = a.search(Pose(-100.0, 0.0, -50.0, math.pi / 2), np.array([60.0, 0.0, -50.0]))
    assert r.status is SegmentStatus.EXPANSION_LIMIT and r.path is None and math.isinf(r.cost)
    assert (sc.ramp.model_dump(), sc.design.model_dump()) == before
    assert r.diagnostics.expanded_states == 400
