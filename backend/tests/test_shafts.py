"""Phase 20C.2B shaft planner unit tests (directive §50, rules 182–184).

Built on the cached TABULAR selection (development acceleration, never
release authority — FULL regenerates it): cached Effective Ramp + level
accesses → level development → deterministic shaft planning."""

from __future__ import annotations

import json
from itertools import pairwise
from typing import Any

import numpy as np
import pytest

from minegen.core.enums import Capability, ShaftRole
from minegen.core.models import (
    Point2D,
    Point3D,
    RestrictedZone,
    Scenario,
    ScenarioCreate,
    ShaftPlanningConfig,
    ShaftSpec,
)
from minegen.design.constraints import DesignContext
from minegen.design.cost_field import DesignCostEvaluator
from minegen.levels.builder import LevelDevelopmentBuilder, entries_from_level_accesses
from minegen.shafts.models import ShaftFailureCode, ShaftsPayload
from minegen.shafts.planner import ShaftPlanner, level_breakpoints, plan_distance_to_polyline
from minegen.world.synthetic_world import SyntheticWorld, generate_world
from tests.verification_support import load_fixture


@pytest.fixture(scope="module")
def tabular_levels() -> tuple[Scenario, SyntheticWorld, dict[str, Any]]:
    fx = load_fixture("tabular_small_selected")
    sc = Scenario(**fx["scenario"])
    world = generate_world(sc)
    drift = DesignCostEvaluator(world, sc.design)
    cross = DesignCostEvaluator(world, sc.design, DesignContext.crosscut(sc.design))
    levels = LevelDevelopmentBuilder(sc, world.orebody, drift, cross).build(
        fx["effectiveRamp"], "rev", entries=entries_from_level_accesses(fx["levelAccesses"])
    )
    assert levels.status == "SUCCESS", levels.failure_reason
    return sc, world, levels.model_dump(mode="json", by_alias=True)


def _plan(
    base: Scenario, world: SyntheticWorld, levels: dict[str, Any], *specs: ShaftSpec, **cfg: Any
) -> ShaftsPayload:
    sc = base.model_copy(update={"shafts": ShaftPlanningConfig(specs=list(specs), **cfg)})
    axis_ev = DesignCostEvaluator(world, sc.design, DesignContext.shaft(sc.design))
    access_ev = DesignCostEvaluator(world, sc.design)
    return ShaftPlanner(sc, world, axis_ev, access_ev).build(levels, "src", "lv")


def _with_design(base: Scenario, world: SyntheticWorld, **design: Any) -> tuple[Scenario, Any]:
    sc = base.model_copy(update={"design": base.design.model_copy(update=design)})
    return sc, DesignCostEvaluator(world, sc.design, DesignContext.shaft(sc.design))


# -- config --------------------------------------------------------------- #


def test_shaft_config_is_optional_and_role_resolves_capabilities() -> None:
    sc = ScenarioCreate()
    assert sc.shafts.specs == []  # no shaft by default (rule 184)
    assert ShaftSpec(role=ShaftRole.VENTILATION).capabilities == [Capability.VENTILATION_PATH]
    assert set(ShaftSpec().capabilities or []) == set(Capability)
    with pytest.raises(ValueError, match="unique"):
        ShaftPlanningConfig(specs=[ShaftSpec(), ShaftSpec()])
    with pytest.raises(ValueError, match="unique"):
        ShaftSpec(capabilities=[Capability.PERSONNEL_ACCESS, Capability.PERSONNEL_ACCESS])


# -- geometry ------------------------------------------------------------- #


def test_vertical_shaft_default_placement_serves_every_developed_level(
    tabular_levels: tuple[Scenario, SyntheticWorld, dict[str, Any]],
) -> None:
    sc, world, levels = tabular_levels
    res = _plan(sc, world, levels, ShaftSpec())
    assert res.status == "SUCCESS", res.failure_reason
    (shaft,) = res.shafts
    assert shaft.status == "OK" and shaft.collar_source == "DEFAULT_DERIVED"
    # vertical axis: collar and bottom share the plan position, collar on terrain
    assert shaft.collar[:2] == shaft.bottom[:2]
    terrain_z = float(world.terrain.sample(np.array([shaft.collar[:2]]))[0])
    assert shaft.collar[2] == pytest.approx(terrain_z)
    assert shaft.collar[2] > shaft.bottom[2]
    # one station per developed level, descending elevation, on the axis
    assert [s.level_id for s in shaft.stations] == [lv["levelId"] for lv in levels["levels"]]
    zs = [s.elevation for s in shaft.stations]
    assert zs == sorted(zs, reverse=True)
    for st in shaft.stations:
        assert st.status == "OK" and st.point[:2] == shaft.collar[:2]
        assert st.connection_target is not None and st.access_centerline_index is not None
        assert st.point[2] == pytest.approx(st.connection_target.position[2])
    # bottom = lowest station − sump
    assert shaft.bottom[2] == pytest.approx(zs[-1] - 10.0)
    # segments collar→STN₁…→bottom in order, station drives owned here too
    segs = [res.centerlines[i] for i in shaft.segment_indices]
    assert [s.kind for s in segs] == ["SHAFT_SEGMENT"] * (len(zs) + 1)
    chain = [segs[0].centerline.points[:3]] + [s.centerline.points[3:] for s in segs]
    assert chain[0] == list(shaft.collar) and chain[-1] == list(shaft.bottom)
    assert [c[2] for c in chain] == sorted((c[2] for c in chain), reverse=True)
    assert shaft.validation is not None and shaft.validation.valid
    assert shaft.metrics is not None
    assert shaft.metrics.depth == pytest.approx(shaft.collar[2] - shaft.bottom[2])
    assert shaft.metrics.nominal_excavation_volume == pytest.approx(
        shaft.profile.analytic_area * shaft.metrics.depth
    )
    assert res.metrics is not None and res.metrics.station_count == len(zs)


def test_station_targets_existing_level_nodes_only(
    tabular_levels: tuple[Scenario, SyntheticWorld, dict[str, Any]],
) -> None:
    sc, world, levels = tabular_levels
    res = _plan(sc, world, levels, ShaftSpec())
    bps = level_breakpoints(levels)
    (shaft,) = res.shafts
    for st in shaft.stations:
        tgt = st.connection_target
        assert tgt is not None
        cands = bps[st.level_id]
        match = [b for b in cands if abs(b.u - tgt.station_u) <= 1e-6]
        assert len(match) == 1  # an EXISTING breakpoint, never a new node
        assert np.allclose(match[0].position, tgt.position)
        # nearest in plan among the level's breakpoints
        d = [float(np.linalg.norm(b.position[:2] - np.asarray(st.point[:2]))) for b in cands]
        assert tgt.plan_distance_to_axis == pytest.approx(min(d))
        # straight drive: 2 points, from the station to the node
        cl = res.centerlines[st.access_centerline_index or 0]
        assert cl.kind == "STATION_ACCESS" and cl.level_id == st.level_id
        assert cl.centerline.points[:3] == list(st.point)
        assert cl.centerline.points[3:] == list(tgt.position)


def test_explicit_collar_and_level_subset(
    tabular_levels: tuple[Scenario, SyntheticWorld, dict[str, Any]],
) -> None:
    sc, world, levels = tabular_levels
    base = _plan(sc, world, levels, ShaftSpec()).shafts[0]
    x, y = base.collar[0] + 5.0, base.collar[1] - 5.0
    res = _plan(sc, world, levels, ShaftSpec(collar=Point2D(x=x, y=y), level_ids=["L02", "L03"]))
    assert res.status == "SUCCESS", res.failure_reason
    (shaft,) = res.shafts
    assert shaft.collar_source == "EXPLICIT" and shaft.collar[:2] == (x, y)
    assert [s.level_id for s in shaft.stations] == ["L02", "L03"]


def test_planning_is_deterministic(
    tabular_levels: tuple[Scenario, SyntheticWorld, dict[str, Any]],
) -> None:
    sc, world, levels = tabular_levels
    a = _plan(sc, world, levels, ShaftSpec()).model_dump(mode="json", by_alias=True)
    b = _plan(sc, world, levels, ShaftSpec()).model_dump(mode="json", by_alias=True)
    a["metrics"].pop("planningSeconds")
    b["metrics"].pop("planningSeconds")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# -- typed failures ------------------------------------------------------- #


def test_collar_outside_world_fails_typed(
    tabular_levels: tuple[Scenario, SyntheticWorld, dict[str, Any]],
) -> None:
    sc, world, levels = tabular_levels
    res = _plan(sc, world, levels, ShaftSpec(collar=Point2D(x=5000.0, y=5000.0)))
    assert res.status == "FAILED"
    (shaft,) = res.shafts
    assert shaft.status == "FAILED"
    assert shaft.failure_code in (
        ShaftFailureCode.SHAFT_TERRAIN_INVALID,
        ShaftFailureCode.SHAFT_COLLAR_OUT_OF_BOUNDS,
    )
    assert shaft.stations == [] and res.centerlines == []


def test_shaft_through_the_orebody_fails_typed(
    tabular_levels: tuple[Scenario, SyntheticWorld, dict[str, Any]],
) -> None:
    sc, world, levels = tabular_levels
    lo, hi = world.orebody.bounding_box()
    # the orebody plan centre: a vertical axis there must cut the dipping body
    cx, cy = 0.5 * (lo[0] + hi[0]), 0.5 * (lo[1] + hi[1])
    res = _plan(sc, world, levels, ShaftSpec(collar=Point2D(x=cx, y=cy)))
    assert res.status == "FAILED"
    (shaft,) = res.shafts
    assert shaft.failure_code in (
        ShaftFailureCode.SHAFT_OREBODY_INTERSECTION,
        ShaftFailureCode.SHAFT_CLEARANCE_VIOLATION,
    )
    assert shaft.validation is not None and not shaft.validation.valid
    assert shaft.validation.rejection_counts  # explicit, never silent


def test_restricted_zone_on_the_axis_fails_typed(
    tabular_levels: tuple[Scenario, SyntheticWorld, dict[str, Any]],
) -> None:
    sc, world, levels = tabular_levels
    base = _plan(sc, world, levels, ShaftSpec()).shafts[0]
    x, y, zc = base.collar
    zone = RestrictedZone(
        name="box",
        min=Point3D(x=x - 3.0, y=y - 3.0, z=zc - 80.0),
        max=Point3D(x=x + 3.0, y=y + 3.0, z=zc - 60.0),
    )
    sc2, _ = _with_design(sc, world, restricted_zones=[zone])
    res = _plan(sc2, world, levels, ShaftSpec(collar=Point2D(x=x, y=y)))
    assert res.status == "FAILED"
    assert res.shafts[0].failure_code is ShaftFailureCode.SHAFT_RESTRICTED_ZONE_INTERSECTION


def test_unknown_required_level_is_a_station_level_mismatch(
    tabular_levels: tuple[Scenario, SyntheticWorld, dict[str, Any]],
) -> None:
    sc, world, levels = tabular_levels
    res = _plan(sc, world, levels, ShaftSpec(level_ids=["L01", "L99"]))
    assert res.status == "FAILED"
    assert res.shafts[0].failure_code is ShaftFailureCode.SHAFT_STATION_LEVEL_MISMATCH
    assert "L99" in (res.shafts[0].failure_reason or "")


def test_station_drive_too_long_fails_the_required_station_and_the_shaft(
    tabular_levels: tuple[Scenario, SyntheticWorld, dict[str, Any]],
) -> None:
    sc, world, levels = tabular_levels
    res = _plan(sc, world, levels, ShaftSpec(), maximum_station_access_length=20.0)
    assert res.status == "FAILED"
    (shaft,) = res.shafts
    assert shaft.failure_code is ShaftFailureCode.SHAFT_STATION_CONNECTION_INFEASIBLE
    failed = [s for s in shaft.stations if s.status == "FAILED"]
    assert failed and all(
        s.failure_code is ShaftFailureCode.SHAFT_STATION_CONNECTION_INFEASIBLE for s in failed
    )
    # diagnostics retained: every station is reported, none silently dropped
    assert len(shaft.stations) == len(levels["levels"])
    assert shaft.validation is not None and shaft.validation.valid  # axis itself is fine


def test_two_shafts_too_close_fail_the_second_typed(
    tabular_levels: tuple[Scenario, SyntheticWorld, dict[str, Any]],
) -> None:
    sc, world, levels = tabular_levels
    base = _plan(sc, world, levels, ShaftSpec()).shafts[0]
    x, y = base.collar[:2]
    res = _plan(
        sc,
        world,
        levels,
        ShaftSpec(shaft_id="SHAFT-01", collar=Point2D(x=x, y=y)),
        ShaftSpec(shaft_id="SHAFT-02", collar=Point2D(x=x + 4.0, y=y), role=ShaftRole.VENTILATION),
    )
    assert res.status == "FAILED"
    by_id = {s.shaft_id: s for s in res.shafts}
    assert by_id["SHAFT-01"].status == "OK"
    assert by_id["SHAFT-02"].failure_code is ShaftFailureCode.SHAFT_GEOMETRY_INVALID


def test_failed_levels_artifact_is_not_consumable(
    tabular_levels: tuple[Scenario, SyntheticWorld, dict[str, Any]],
) -> None:
    sc, world, levels = tabular_levels
    bad = dict(levels)
    bad["status"] = "FAILED"
    res = _plan(sc, world, bad, ShaftSpec())
    assert res.status == "FAILED" and "not consumable" in (res.failure_reason or "")
    assert res.shafts == []


# -- MineNetwork integration (directive §51, rules 182–184) --------------- #


def _network(sc: Scenario, levels: dict[str, Any], shafts: ShaftsPayload | None) -> Any:
    from minegen.network.builder import MineNetworkBuilder

    fx = load_fixture("tabular_small_selected")
    return MineNetworkBuilder(sc).build(
        fx["effectiveRamp"],
        "rev",
        levels_payload=levels,
        geometry_artifact="layout_v2_selected.json",
        accesses_payload=fx["levelAccesses"],
        shafts_payload=shafts.model_dump(mode="json", by_alias=True) if shafts else None,
    )


def test_network_integrates_shaft_nodes_edges_and_geometry_refs(
    tabular_levels: tuple[Scenario, SyntheticWorld, dict[str, Any]],
) -> None:
    sc, world, levels = tabular_levels
    shafts = _plan(sc, world, levels, ShaftSpec())
    assert shafts.status == "SUCCESS"
    without = _network(sc, levels, None).payload
    res = _network(sc, levels, shafts)
    net = res.payload
    assert net.status == "SUCCESS", net.failure_reason
    assert net.validation is not None and net.validation.connected and net.validation.synchronized
    node_ids = [n.id for n in net.nodes]
    assert len(set(node_ids)) == len(node_ids)
    edge_ids = [e.id for e in net.edges]
    assert len(set(edge_ids)) == len(edge_ids)
    shaft = shafts.shafts[0]
    n_st = len(shaft.stations)
    assert "SHAFT_COLLAR:SHAFT-01" in node_ids and "SHAFT_BOTTOM:SHAFT-01" in node_ids
    stations = [n for n in net.nodes if n.type.value == "SHAFT_STATION"]
    assert [n.id for n in stations] == [s.station_id for s in shaft.stations]
    shaft_edges = [e for e in net.edges if e.type.value == "SHAFT"]
    access_edges = [e for e in net.edges if e.type.value == "SHAFT_STATION_ACCESS"]
    assert len(shaft_edges) == n_st + 1 and len(access_edges) == n_st
    # vertical edges: no gradient, explicit vertical drop, circular section
    for e in shaft_edges:
        assert e.orientation == "VERTICAL"
        assert e.mean_gradient_signed is None and e.max_abs_gradient is None
        assert e.vertical_drop is not None and e.vertical_drop > 0
        assert e.cross_section.shape == "CIRCULAR" and e.cross_section.width == 6.0
        assert e.geometry_ref.artifact == "shafts.json"
        assert shafts.centerlines[e.geometry_ref.segment_index].id == e.id
    # the axis chain is collar → stations → bottom
    chain = [
        "SHAFT_COLLAR:SHAFT-01",
        *[s.station_id for s in shaft.stations],
        "SHAFT_BOTTOM:SHAFT-01",
    ]
    assert [(e.from_node, e.to_node) for e in shaft_edges] == list(pairwise(chain))
    # station drives end on EXISTING level nodes (no new node was created)
    existing = {n.id for n in without.nodes}
    for e in access_edges:
        assert e.orientation == "DEVELOPMENT" and e.from_node in [
            s.station_id for s in shaft.stations
        ]
        assert e.to_node in existing
        assert e.geometry_ref.artifact == "shafts.json"
        assert shafts.centerlines[e.geometry_ref.segment_index].id == e.id
    # nothing else changed versus the no-shaft network
    assert [n.id for n in without.nodes] == [
        n.id for n in net.nodes if not n.id.startswith("SHAFT")
    ]
    assert [e.id for e in without.edges] == [
        e.id for e in net.edges if e.type.value not in ("SHAFT", "SHAFT_STATION_ACCESS")
    ]
    assert net.metrics is not None and without.metrics is not None
    assert net.metrics.shaft_count == 1 and net.metrics.shaft_station_count == n_st
    assert without.metrics.shaft_count == 0 and without.metrics.shaft_edge_count == 0
    assert net.metrics.total_shaft_length3d == pytest.approx(
        shaft.metrics.total_shaft_length3d if shaft.metrics else 0
    )
    # the shaft collar is a second surface node: every underground node now
    # has one more edge-disjoint surface path than before (advisory only)
    before = {
        p.node_id: p.independent_surface_paths for p in without.surface_path_advisory[0].per_node
    }
    after = {p.node_id: p.independent_surface_paths for p in net.surface_path_advisory[0].per_node}
    assert all(after[k] >= before[k] for k in before)
    assert any(after[k] > before[k] for k in before)


def test_network_refuses_failed_or_stale_shaft_artifacts(
    tabular_levels: tuple[Scenario, SyntheticWorld, dict[str, Any]],
) -> None:
    sc, world, levels = tabular_levels
    failed = _plan(sc, world, levels, ShaftSpec(level_ids=["L01", "L99"]))
    assert failed.status == "FAILED"
    res = _network(sc, levels, failed)
    assert res.payload.status == "FAILED" and "not consumable" in (res.payload.failure_reason or "")
    assert res.payload.nodes == [] and res.payload.edges == []


# -- downstream consumers: timeline + infrastructure (directive amendment A3) -- #


def _stopes(sc: Scenario, world: SyntheticWorld, levels: dict[str, Any]) -> dict[str, Any]:
    from minegen.mining.methods.base import strategy_for

    strategy = strategy_for(sc.mining.method)
    assert strategy is not None
    hard = DesignCostEvaluator(world, sc.design, DesignContext.crosscut(sc.design))
    payload = strategy.generate(sc, world, levels, hard, "rev")
    assert payload.status == "SUCCESS", payload.failure_reason
    return payload.model_dump(mode="json", by_alias=True)


def test_timeline_sinks_the_shaft_from_the_collar_and_drives_stations_from_the_shaft(
    tabular_levels: tuple[Scenario, SyntheticWorld, dict[str, Any]],
) -> None:
    from minegen.scheduling.builder import MineTimelineBuilder

    sc, world, levels = tabular_levels
    fx = load_fixture("tabular_small_selected")
    shafts = _plan(sc, world, levels, ShaftSpec())
    stopes = _stopes(sc, world, levels)
    net = _network(sc, levels, shafts).payload.model_dump(mode="json", by_alias=True)
    net_plain = _network(sc, levels, None).payload.model_dump(mode="json", by_alias=True)
    shafts_dict = shafts.model_dump(mode="json", by_alias=True)
    build = MineTimelineBuilder(sc).build
    tl = build(net, stopes, fx["effectiveRamp"], levels, "rev", fx["levelAccesses"], shafts_dict)
    assert tl.status == "SUCCESS", tl.failure_reason
    plain = build(net_plain, stopes, fx["effectiveRamp"], levels, "rev", fx["levelAccesses"])
    assert plain.status == "SUCCESS", plain.failure_reason
    tasks = {t.id: t for t in tl.tasks}
    shaft_edges = [e for e in net["edges"] if e["type"] == "SHAFT"]
    access_edges = [e for e in net["edges"] if e["type"] == "SHAFT_STATION_ACCESS"]
    # one DEVELOP_SHAFT task per axis segment, chained collar → deeper
    prev = None
    for e in shaft_edges:
        t = tasks[f"TASK:DEVELOP:{e['id']}"]
        assert t.task_type.value == "DEVELOP_SHAFT"
        assert t.basis.rate == sc.schedule.shaft_sink_m_per_day
        assert t.duration_days == pytest.approx(e["length3d"] / sc.schedule.shaft_sink_m_per_day)
        assert t.dependencies == ([] if prev is None else [prev])
        prev = t.id
    # a station drive waits for the sinking task that reaches its station
    sink_by_station = {e["toNode"]: f"TASK:DEVELOP:{e['id']}" for e in shaft_edges}
    for e in access_edges:
        t = tasks[f"TASK:DEVELOP:{e['id']}"]
        assert t.task_type.value == "DEVELOP_SHAFT_STATION_ACCESS"
        assert t.dependencies == [sink_by_station[e["fromNode"]]]
        assert t.start_day == pytest.approx(tasks[sink_by_station[e["fromNode"]]].end_day)
    # excavation direction: shaft from the collar side, drive from the station
    by_edge = {d.edge_id: d for d in tl.developments}
    for e in shaft_edges + access_edges:
        d = by_edge[e["id"]]
        assert d.excavation_start_node == e["fromNode"] and d.progress_direction == 1
        assert d.geometry_ref.artifact == "shafts.json"
        assert d.point_chainage_fractions == [0.0, 1.0]
    # the ramp-rooted level schedule is unchanged by the shaft (rule 85)
    plain_tasks = {t.id: t for t in plain.tasks}
    for tid, t in plain_tasks.items():
        assert tasks[tid].start_day == pytest.approx(t.start_day)
        assert tasks[tid].end_day == pytest.approx(t.end_day)
        assert tasks[tid].dependencies == t.dependencies
    assert set(tasks) - set(plain_tasks) == {
        f"TASK:DEVELOP:{e['id']}" for e in shaft_edges + access_edges
    }


def test_infrastructure_domain_and_communication_accept_shaft_edges(
    tabular_levels: tuple[Scenario, SyntheticWorld, dict[str, Any]],
) -> None:
    from minegen.infrastructure.builder import CommunicationBuilder
    from minegen.infrastructure.network_domain import InfrastructureNetworkDomain

    sc, world, levels = tabular_levels
    fx = load_fixture("tabular_small_selected")
    shafts = _plan(sc, world, levels, ShaftSpec())
    net = _network(sc, levels, shafts).payload.model_dump(mode="json", by_alias=True)
    shafts_dict = shafts.model_dump(mode="json", by_alias=True)
    domain = InfrastructureNetworkDomain.build(
        net, fx["effectiveRamp"], levels, fx["levelAccesses"], shafts_dict
    )
    assert np.all(np.isfinite(domain.node_dist))
    collar = domain.node_index["SHAFT_COLLAR:SHAFT-01"]
    bottom = domain.node_index["SHAFT_BOTTOM:SHAFT-01"]
    shaft = shafts.shafts[0]
    assert shaft.metrics is not None
    # geodesic collar → bottom along the axis is the shaft length (3-D, vertical)
    assert domain.node_dist[collar, bottom] == pytest.approx(shaft.metrics.total_shaft_length3d)
    comm = CommunicationBuilder(sc).build(
        net, fx["effectiveRamp"], levels, "rev", fx["levelAccesses"], shafts_dict
    )
    assert comm.status == "SUCCESS", comm.failure_reason
    # a shaft artifact whose edges are present but the payload is withheld
    # is a typed domain failure (never a KeyError)
    from minegen.infrastructure.network_domain import DomainValidationError

    with pytest.raises(DomainValidationError, match="out of range"):
        InfrastructureNetworkDomain.build(net, fx["effectiveRamp"], levels, fx["levelAccesses"])


def test_axis_too_close_to_an_existing_development_is_a_clearance_violation(
    tabular_levels: tuple[Scenario, SyntheticWorld, dict[str, Any]],
) -> None:
    """Directive §10 minimum infrastructure clearance: the shaft excavation
    keeps a rock pillar from every existing level development."""
    sc, world, levels = tabular_levels
    entry = levels["levels"][1]["entry"]  # put the axis 4 m from the L02 entry
    res = _plan(sc, world, levels, ShaftSpec(collar=Point2D(x=entry[0] + 4.0, y=entry[1])))
    assert res.status == "FAILED"
    (shaft,) = res.shafts
    assert shaft.failure_code is ShaftFailureCode.SHAFT_CLEARANCE_VIOLATION
    assert shaft.validation is not None
    dc = shaft.validation.development_clearance
    assert dc is not None and not dc.valid
    assert (
        dc.minimum_plan_distance is not None
        and dc.minimum_plan_distance < dc.required_plan_distance
    )
    assert dc.required_plan_distance == pytest.approx(3.0 + 2.5 + 2.0 * sc.ramp.tunnel_width)
    assert dc.nearest_development_id is not None and "L02" in dc.nearest_development_id
    # the healthy default placement reports its clearance too
    ok = _plan(sc, world, levels, ShaftSpec()).shafts[0]
    assert ok.validation is not None and ok.validation.development_clearance is not None
    assert ok.validation.development_clearance.valid


def test_development_clearance_catches_a_segment_passing_the_axis_between_samples(
    tabular_levels: tuple[Scenario, SyntheticWorld, dict[str, Any]],
) -> None:
    """Regression: the rock-pillar gate measures the EXACT plan point-to-
    segment distance, never the vertex-only distance. A synthetic drift
    whose two vertices sit 60 m either side of the axis but whose segment
    passes THROUGH the axis at its midpoint must be a violation."""
    sc, world, levels = tabular_levels
    ok = _plan(sc, world, levels, ShaftSpec()).shafts[0]
    assert ok.status == "OK" and ok.validation is not None
    dc0 = ok.validation.development_clearance
    assert dc0 is not None and dc0.valid
    cx, cy, _ = ok.collar
    z_mid = 0.5 * (ok.collar[2] + ok.bottom[2])
    synthetic = {
        "id": "CROSSCUT:SYNTH:MIDPOINT",
        "kind": "CROSSCUT",
        "levelId": levels["levels"][0]["levelId"],
        "centerline": {"points": [[cx - 60.0, cy, z_mid], [cx + 60.0, cy, z_mid]]},
    }
    patched = json.loads(json.dumps(levels))
    patched["developments"].append(synthetic)
    # vertex-only reading of the synthetic segment: 60 m (would pass)
    vertex_only = min(np.hypot(px - cx, py - cy) for px, py, _ in synthetic["centerline"]["points"])
    assert vertex_only == pytest.approx(60.0)
    res = _plan(sc, world, patched, ShaftSpec(collar=Point2D(x=cx, y=cy)))
    assert res.status == "FAILED"
    (shaft,) = res.shafts
    assert shaft.failure_code is ShaftFailureCode.SHAFT_CLEARANCE_VIOLATION
    assert shaft.validation is not None
    dc = shaft.validation.development_clearance
    assert dc is not None and not dc.valid
    assert dc.minimum_plan_distance == pytest.approx(0.0, abs=1e-9)
    assert dc.nearest_development_id == "CROSSCUT:SYNTH:MIDPOINT"
    assert dc.segments_checked == dc0.segments_checked + 1


def test_plan_distance_clips_an_inclined_segment_straddling_the_depth_band() -> None:
    """Regression: an inclined segment crossing the depth-band boundary is
    clipped to the band BEFORE the plan distance is measured. Two mirrored
    cases: (i) the near vertex lies OUTSIDE the band, so the exact distance
    is the clipped intersection point's distance (not the far in-band
    vertex, not the excluded near vertex); (ii) the near vertex lies INSIDE
    the band and the far one outside, so the distance is the in-band
    vertex's."""
    xy = np.array([0.0, 0.0])
    z_lo, z_hi = 100.0, 200.0
    # (i) from (0, 0, 80) [below the band, at the axis] rising to (100, 0, 180)
    # [inside]: the band is entered at z = 100 → x = 20 → exact distance 20 m.
    seg = np.array([[0.0, 0.0, 80.0], [100.0, 0.0, 180.0]])
    d, n = plan_distance_to_polyline(xy, seg, z_lo, z_hi)
    assert n == 1 and d == pytest.approx(20.0)
    # the vertex-only reading (in-band vertices only) would say 100 m — wrong
    in_band = seg[(seg[:, 2] >= z_lo) & (seg[:, 2] <= z_hi)]
    assert np.hypot(in_band[:, 0], in_band[:, 1]).min() == pytest.approx(100.0)
    # reversed point order gives the same answer
    d_rev, _ = plan_distance_to_polyline(xy, seg[::-1].copy(), z_lo, z_hi)
    assert d_rev == pytest.approx(20.0)
    # (ii) mirrored at the UPPER boundary: from (5, 0, 150) [inside] rising to
    # (0, 0, 250) [above the band, at the axis]: the excluded vertex must not
    # count (not 0 m), the in-band vertex is not the answer either (not 5 m);
    # the band is left at z = 200 → x = 2.5 → exact distance 2.5 m
    seg2 = np.array([[5.0, 0.0, 150.0], [0.0, 0.0, 250.0]])
    d2, n2 = plan_distance_to_polyline(xy, seg2, z_lo, z_hi)
    assert n2 == 1 and d2 == pytest.approx(2.5)
    # a segment entirely outside the band contributes nothing
    assert plan_distance_to_polyline(
        xy, np.array([[1.0, 0.0, 10.0], [1.0, 0.0, 90.0]]), z_lo, z_hi
    ) == (None, 0)
    # a segment touching the band at exactly one point contributes that point
    d3, n3 = plan_distance_to_polyline(
        xy, np.array([[7.0, 0.0, 90.0], [3.0, 0.0, 100.0]]), z_lo, z_hi
    )
    assert n3 == 1 and d3 == pytest.approx(3.0)
    # a horizontal in-band segment: exact interior point (perpendicular foot)
    d4, _ = plan_distance_to_polyline(
        xy, np.array([[-50.0, 4.0, 150.0], [50.0, 4.0, 150.0]]), z_lo, z_hi
    )
    assert d4 == pytest.approx(4.0)
