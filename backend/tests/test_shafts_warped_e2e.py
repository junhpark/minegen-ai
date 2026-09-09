"""Phase 20C.2B WARPED-301 E2E (directive §46, §53): layout → selected
candidate → level accesses → curved levels → shaft → network → capability
graph. The shaft gets NO WARPED-specific shortcut: the same planner, the
same hard gates under the candidate's certified clearance policy (rule
172); the WARPED stope boundary stays the typed Phase 09 limit."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from minegen.capability.builder import CapabilityGraphBuilder, can_reach, query_graph_from
from minegen.core.enums import Capability
from minegen.core.models import Point2D, Scenario, ShaftPlanningConfig, ShaftSpec
from minegen.design.constraints import DesignContext
from minegen.design.cost_field import DesignCostEvaluator
from minegen.layout.search import LayoutSearchResult, LayoutV2Search
from minegen.levels.models import LevelsPayload
from minegen.network.builder import MineNetworkBuilder
from minegen.shafts.models import ShaftFailureCode
from minegen.shafts.planner import ShaftPlanner
from minegen.world.synthetic_world import SyntheticWorld
from tests.test_curved_levels import _build_levels


def test_warped_301_shaft_network_and_capability_chain(
    warped_301: tuple[Scenario, SyntheticWorld],
    warped_301_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    sc, world = warped_301
    search, res = warped_301_search
    levels, ramp, accesses = _build_levels(sc, world, search, res)
    assert isinstance(levels, LevelsPayload) and levels.status == "SUCCESS", levels.failure_reason
    assert levels.development_geometry == "SECTION_FOOTWALL_OFFSET_TRACE"
    levels_dict: dict[str, Any] = levels.model_dump(mode="json", by_alias=True)

    # shaft under the SAME candidate certification the level builder used
    assert res.winner_id is not None
    _, policy, _ = search.candidate_policy(res, res.winner_id)

    def plan(spec: ShaftSpec) -> tuple[Scenario, Any]:
        sc_s = sc.model_copy(update={"shafts": ShaftPlanningConfig(specs=[spec])})
        axis_ev = DesignCostEvaluator(
            world, sc_s.design, DesignContext.shaft(sc_s.design), clearance=policy
        )
        access_ev = DesignCostEvaluator(world, sc_s.design, clearance=policy)
        return sc_s, ShaftPlanner(sc_s, world, axis_ev, access_ev).build(levels_dict, "src", "lv")

    # the conservative DEFAULT placement (clear of every development by
    # construction) overshoots on this laterally migrating curved backbone:
    # the deepest station drive exceeds the declared 200 m ceiling — a typed
    # failure, recorded, never tuned around (directive §16)
    _, default_res = plan(ShaftSpec())
    assert default_res.status == "FAILED"
    d_shaft = default_res.shafts[0]
    assert d_shaft.failure_code is ShaftFailureCode.SHAFT_STATION_CONNECTION_INFEASIBLE
    assert d_shaft.validation is not None and d_shaft.validation.valid  # axis itself is fine
    assert "maximumStationAccessLength" in (d_shaft.failure_reason or "")

    # directive option A: an EXPLICIT collar — 80 m along the away-from-ore
    # direction through the level-entry centroid (computed from the
    # delivered level geometry; no magic coordinate)
    entries = np.array([lv.entry[:2] for lv in levels.levels])
    centroid = entries.mean(axis=0)
    lo, hi = world.orebody.bounding_box()
    n = centroid - 0.5 * (np.asarray(lo)[:2] + np.asarray(hi)[:2])
    n /= np.linalg.norm(n)
    cx, cy = centroid + 80.0 * n
    sc2, shafts = plan(ShaftSpec(collar=Point2D(x=float(cx), y=float(cy))))
    assert shafts.status == "SUCCESS", shafts.failure_reason
    (shaft,) = shafts.shafts
    assert shaft.status == "OK" and shaft.collar_source == "EXPLICIT"
    assert [s.level_id for s in shaft.stations] == [lv.level_id for lv in levels.levels]
    assert shaft.validation is not None and shaft.validation.valid
    assert shaft.validation.development_clearance is not None
    assert shaft.validation.development_clearance.valid
    # the axis stays clear of the implicit body under the conservative policy
    axis = np.linspace(np.asarray(shaft.collar), np.asarray(shaft.bottom), 64)
    assert not bool(world.orebody.contains(axis).any())
    for st in shaft.stations:
        assert st.connection_target is not None
        # station drives end on the curved-trace level nodes (rule 183)
        assert st.connection_target.node_kind in ("LEVEL_ENTRY", "JUNCTION")

    net = MineNetworkBuilder(sc2).build(
        ramp,
        "netrev",
        levels_payload=levels_dict,
        geometry_artifact="layout_v2_selected.json",
        accesses_payload=accesses,
        shafts_payload=shafts.model_dump(mode="json", by_alias=True),
    )
    assert net.success, net.payload.failure_reason
    assert net.payload.validation is not None and net.payload.validation.connected
    assert net.payload.metrics is not None and net.payload.metrics.shaft_count == 1
    net_dict = net.payload.model_dump(mode="json", by_alias=True)

    cap = CapabilityGraphBuilder(sc2).build(
        net_dict, shafts.model_dump(mode="json", by_alias=True), "src", "filerev"
    )
    assert cap.status == "SUCCESS", cap.failure_reason
    assert cap.validation is not None and cap.validation.required_paths_satisfied
    graph = query_graph_from(net_dict, cap.model_dump(mode="json", by_alias=True))
    for st in shaft.stations:
        q = can_reach(graph, "PORTAL", st.station_id, Capability.PERSONNEL_ACCESS)
        assert q.physical_reachable and q.capability_reachable
    assert cap.egress_advisory is not None
    routes = {p.node_id: p.independent_egress_routes for p in cap.egress_advisory.per_node}
    assert all(routes[n] >= 2 for n in routes if n.startswith("LEVEL_ENTRY:"))
    # runtime observation (directive §56): recorded in the metrics, never a
    # gate — no wall-clock threshold is asserted
    assert shafts.metrics is not None and cap.metrics is not None
    assert math.isfinite(shafts.metrics.planning_seconds) and shafts.metrics.planning_seconds >= 0
    assert math.isfinite(cap.metrics.build_seconds) and cap.metrics.build_seconds >= 0
