"""Phase 20C.2B capability-graph tests (directive §52, rule 185): explicit
capability assignment, physical ≠ capability reachability, revision and
reference validation, required paths and the egress advisory."""

from __future__ import annotations

import json
from typing import Any

import pytest

from minegen.capability.builder import (
    CapabilityGraphBuilder,
    can_reach,
    query_graph_from,
)
from minegen.capability.models import CapabilityGraphPayload, CapabilitySource
from minegen.core.enums import Capability, EdgeType, ShaftRole
from minegen.core.models import CapabilityConfig, Scenario, ShaftPlanningConfig, ShaftSpec
from minegen.design.constraints import DesignContext
from minegen.design.cost_field import DesignCostEvaluator
from minegen.levels.builder import LevelDevelopmentBuilder, entries_from_level_accesses
from minegen.network.builder import MineNetworkBuilder
from minegen.shafts.models import ShaftsPayload
from minegen.shafts.planner import ShaftPlanner
from minegen.world.synthetic_world import SyntheticWorld, generate_world
from tests.verification_support import load_fixture

Chain = tuple[Scenario, SyntheticWorld, dict[str, Any], dict[str, Any]]


@pytest.fixture(scope="module")
def chain() -> Chain:
    fx = load_fixture("tabular_small_selected")
    sc = Scenario(**fx["scenario"])
    world = generate_world(sc)
    drift = DesignCostEvaluator(world, sc.design)
    cross = DesignCostEvaluator(world, sc.design, DesignContext.crosscut(sc.design))
    levels = LevelDevelopmentBuilder(sc, world.orebody, drift, cross).build(
        fx["effectiveRamp"], "rev", entries=entries_from_level_accesses(fx["levelAccesses"])
    )
    assert levels.status == "SUCCESS", levels.failure_reason
    return sc, world, levels.model_dump(mode="json", by_alias=True), fx


def _shafts(
    sc: Scenario, world: SyntheticWorld, levels: dict[str, Any], *specs: ShaftSpec
) -> ShaftsPayload:
    sc2 = sc.model_copy(update={"shafts": ShaftPlanningConfig(specs=list(specs))})
    axis = DesignCostEvaluator(world, sc2.design, DesignContext.shaft(sc2.design))
    res = ShaftPlanner(sc2, world, axis, DesignCostEvaluator(world, sc2.design)).build(
        levels, "src", "lv"
    )
    assert res.status == "SUCCESS", res.failure_reason
    return res


def _network(
    sc: Scenario, fx: dict[str, Any], levels: dict[str, Any], shafts: ShaftsPayload | None
) -> dict[str, Any]:
    res = MineNetworkBuilder(sc).build(
        fx["effectiveRamp"],
        "netrev",
        levels_payload=levels,
        geometry_artifact="layout_v2_selected.json",
        accesses_payload=fx["levelAccesses"],
        shafts_payload=shafts.model_dump(mode="json", by_alias=True) if shafts else None,
    )
    assert res.success, res.payload.failure_reason
    return res.payload.model_dump(mode="json", by_alias=True)


def _graph(
    sc: Scenario, net: dict[str, Any], shafts: ShaftsPayload | None, rev: str = "filerev"
) -> CapabilityGraphPayload:
    return CapabilityGraphBuilder(sc).build(
        net, shafts.model_dump(mode="json", by_alias=True) if shafts else None, "src", rev
    )


def test_no_shaft_graph_assigns_defaults_and_satisfies_required_paths(chain: Chain) -> None:
    sc, _, levels, fx = chain
    net = _network(sc, fx, levels, None)
    g = _graph(sc, net, None)
    assert g.status == "SUCCESS", g.failure_reason
    assert [e.edge_id for e in g.edges] == [e["id"] for e in net["edges"]]
    assert [n.node_id for n in g.nodes] == [n["id"] for n in net["nodes"]]
    for e in g.edges:
        assert e.source is CapabilitySource.EDGE_TYPE_DEFAULT
        assert e.capabilities == list(Capability) and e.restrictions == []
    assert g.surface_node_ids == ["PORTAL"]
    assert g.validation is not None and g.validation.valid
    assert g.required_paths and all(c.satisfied for c in g.required_paths)
    # single-decline topology: exactly one egress route per node (rule 70)
    assert g.egress_advisory is not None and g.egress_advisory.advisory_only
    assert {p.independent_egress_routes for p in g.egress_advisory.per_node} == {1}
    assert not any(p.meets_criterion for p in g.egress_advisory.per_node)
    assert g.network_source_revision == "netrev" and g.network_revision == "filerev"


def test_production_shaft_adds_declared_capabilities_and_a_second_egress(chain: Chain) -> None:
    sc, world, levels, fx = chain
    shafts = _shafts(sc, world, levels, ShaftSpec())
    net = _network(sc, fx, levels, shafts)
    g = _graph(sc, net, shafts)
    assert g.status == "SUCCESS", g.failure_reason
    shaft_edges = [
        e for e in g.edges if e.edge_type in (EdgeType.SHAFT, EdgeType.SHAFT_STATION_ACCESS)
    ]
    assert shaft_edges and all(e.source is CapabilitySource.SHAFT_DECLARED for e in shaft_edges)
    assert all(e.shaft_id == "SHAFT-01" for e in shaft_edges)
    assert all(e.capabilities == list(Capability) for e in shaft_edges)
    assert g.surface_node_ids == ["PORTAL", "SHAFT_COLLAR:SHAFT-01"]
    # collar → every station is a required PERSONNEL / HAULAGE path, satisfied
    collar_checks = [c for c in g.required_paths if c.source_node_id == "SHAFT_COLLAR:SHAFT-01"]
    n_st = sum(1 for n in net["nodes"] if n["type"] == "SHAFT_STATION")
    assert len(collar_checks) == 2 * n_st and all(c.satisfied for c in collar_checks)
    # level entries now have two edge-disjoint egress routes (portal + collar)
    assert g.egress_advisory is not None
    routes = {p.node_id: p.independent_egress_routes for p in g.egress_advisory.per_node}
    assert all(routes[n] >= 2 for n in routes if n.startswith("LEVEL_ENTRY:"))
    assert g.metrics is not None and g.metrics.surface_node_count == 2


def test_physical_path_is_not_a_capability_path(chain: Chain) -> None:
    sc, world, levels, fx = chain
    vent = ShaftSpec(shaft_id="VENT-01", role=ShaftRole.VENTILATION)
    shafts = _shafts(sc, world, levels, vent)
    net = _network(sc, fx, levels, shafts)
    g = _graph(sc, net, shafts)
    assert g.status == "SUCCESS", g.failure_reason
    for e in g.edges:
        if e.edge_type in (EdgeType.SHAFT, EdgeType.SHAFT_STATION_ACCESS):
            assert e.capabilities == [Capability.VENTILATION_PATH]
            assert Capability.PERSONNEL_ACCESS in e.restrictions
    graph = query_graph_from(net, g.model_dump(mode="json", by_alias=True))
    station = next(n["id"] for n in net["nodes"] if n["type"] == "SHAFT_STATION")
    q = can_reach(graph, "SHAFT_COLLAR:VENT-01", station, Capability.PERSONNEL_ACCESS)
    assert q.physical_reachable and not q.capability_reachable and q.path_edge_ids == []
    q2 = can_reach(graph, "SHAFT_COLLAR:VENT-01", station, Capability.VENTILATION_PATH)
    assert q2.capability_reachable and q2.path_node_ids[0] == "SHAFT_COLLAR:VENT-01"
    assert q2.path_node_ids[-1] == station and len(q2.path_edge_ids) == len(q2.path_node_ids) - 1
    # the collar → station personnel path is NOT required for a ventilation shaft,
    # and its unoccupied stations / bottom need no egress route (no personnel)
    assert not any(c.source_node_id == "SHAFT_COLLAR:VENT-01" for c in g.required_paths)
    assert not any("VENT-01" in c.source_node_id for c in g.required_paths)
    vent_nodes = [n for n in g.nodes if "VENT-01" in n.node_id and not n.surface]
    assert vent_nodes and all(n.supports == [Capability.VENTILATION_PATH] for n in vent_nodes)
    # a ventilation shaft is not an egress: route counts equal the no-shaft graph
    plain = _graph(sc, _network(sc, fx, levels, None), None)
    assert plain.egress_advisory is not None and g.egress_advisory is not None
    plain_routes = {p.node_id: p.independent_egress_routes for p in plain.egress_advisory.per_node}
    for p in g.egress_advisory.per_node:
        if p.node_id in plain_routes:
            assert p.independent_egress_routes == plain_routes[p.node_id]
    # personnel access to the level entries is unaffected
    q3 = can_reach(graph, "PORTAL", "LEVEL_ENTRY:L02", Capability.PERSONNEL_ACCESS)
    assert q3.capability_reachable


def test_declared_edge_type_override_and_unsatisfied_required_path_fail_explicitly(
    chain: Chain,
) -> None:
    sc, _, levels, fx = chain
    net = _network(sc, fx, levels, None)
    # crosscuts may carry personnel and haulage but are declared NOT to be
    # egress routes: personnel can reach every STOPE_ACCESS, none can egress
    cfg = CapabilityConfig(
        edge_type_capabilities={
            EdgeType.CROSSCUT: [Capability.PERSONNEL_ACCESS, Capability.MATERIAL_HAULAGE]
        }
    )
    sc2 = sc.model_copy(update={"capability": cfg})
    g = _graph(sc2, net, None)
    crosscuts = [e for e in g.edges if e.edge_type is EdgeType.CROSSCUT]
    assert crosscuts and all(e.source is CapabilitySource.EDGE_TYPE_DECLARED for e in crosscuts)
    assert all(
        e.capabilities == [Capability.PERSONNEL_ACCESS, Capability.MATERIAL_HAULAGE]
        for e in crosscuts
    )
    assert all(Capability.EMERGENCY_EGRESS in e.restrictions for e in crosscuts)
    # STOPE_ACCESS nodes have a physical route out but no EMERGENCY_EGRESS
    # route: an explicit FAILED graph, never a silent pass
    assert g.status == "FAILED" and g.validation is not None
    assert not g.validation.required_paths_satisfied
    assert "unsatisfied" in (g.failure_reason or "")
    unsat = [c for c in g.required_paths if not c.satisfied]
    assert unsat and all(c.source_node_id.startswith("STOPE_ACCESS:") for c in unsat)
    assert all(c.physical_reachable and not c.capability_reachable for c in unsat)
    assert g.egress_advisory is not None
    routes = {p.node_id: p.independent_egress_routes for p in g.egress_advisory.per_node}
    assert all(routes[n] == 0 for n in routes if n.startswith("STOPE_ACCESS:"))
    # an override that carries no personnel makes the node unoccupied: no
    # egress requirement, the graph stays SUCCESS
    cfg2 = CapabilityConfig(
        edge_type_capabilities={EdgeType.CROSSCUT: [Capability.MATERIAL_HAULAGE]}
    )
    g2 = _graph(sc.model_copy(update={"capability": cfg2}), net, None)
    assert g2.status == "SUCCESS", g2.failure_reason
    assert not any(c.source_node_id.startswith("STOPE_ACCESS:") for c in g2.required_paths)
    with pytest.raises(ValueError, match="declared per shaft"):
        CapabilityConfig(edge_type_capabilities={EdgeType.SHAFT: [Capability.VENTILATION_PATH]})


def test_stale_revision_missing_reference_and_duplicates_are_rejected(chain: Chain) -> None:
    sc, world, levels, fx = chain
    net = _network(sc, fx, levels, None)
    stale = _graph(sc, net, None, rev="")
    assert stale.status == "FAILED" and stale.validation is not None
    assert not stale.validation.network_revision_matches
    broken = json.loads(json.dumps(net))
    broken["edges"][3]["toNode"] = "GHOST"
    g = _graph(sc, broken, None)
    assert g.status == "FAILED" and "missing endpoints" in (g.failure_reason or "")
    dup = json.loads(json.dumps(net))
    dup["edges"].append(json.loads(json.dumps(dup["edges"][0])))
    g = _graph(sc, dup, None)
    assert g.status == "FAILED" and "duplicate edge ids" in (g.failure_reason or "")
    failed_net = json.loads(json.dumps(net))
    failed_net["status"] = "FAILED"
    g = _graph(sc, failed_net, None)
    assert g.status == "FAILED" and "not consumable" in (g.failure_reason or "")
    # shaft edges without the owning shaft artifact cannot be assigned
    shafts = _shafts(sc, world, levels, ShaftSpec())
    net_s = _network(sc, fx, levels, shafts)
    g = _graph(sc, net_s, None)
    assert g.status == "FAILED" and "shaft artifact" in (g.failure_reason or "")


def test_capability_graph_is_deterministic(chain: Chain) -> None:
    sc, world, levels, fx = chain
    shafts = _shafts(sc, world, levels, ShaftSpec())
    net = _network(sc, fx, levels, shafts)
    a = _graph(sc, net, shafts).model_dump(mode="json", by_alias=True)
    b = _graph(sc, net, shafts).model_dump(mode="json", by_alias=True)
    a["metrics"].pop("buildSeconds")
    b["metrics"].pop("buildSeconds")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
