"""Phase 10 — MineTimeline builder (rules 81–86).

Deterministic precedence-only EARLIEST-START scheduler: no resource
capacities, no crews, no optimization — for every task
``startDay = max(endDay of dependencies)`` and
``endDay = startDay + durationDays`` (rule 82). The task graph must be a
DAG; topological ordering uses stable task IDs as the tie breaker.

Physical-access precedence (rule 85): RAMP tasks follow the canonical
portal→deeper decline chain validated from topology (never lexical IDs);
each level's DRIFT/CROSSCUT development is rooted at its LEVEL_ENTRY on the
UNDIRECTED physical subgraph via deterministic Dijkstra (duration-weighted,
edge/node-id tie-breaking) — one accessible endpoint is sufficient to start
advancing a development, and canonical edge direction is geometry
orientation, not operational one-way travel. Stope preparation requires
BOTH Phase 09 STOPE_ACCESS crosscuts.

Continuous chainage (rule 83): every development resolves its geometryRef
against the OWNING centerline artifact; the backend persists normalized
cumulative chainage fractions so a DEVELOPING excavation is only ever drawn
partially (rule 31). The timeline never copies geometry coordinates.
"""

from __future__ import annotations

import heapq
import math
from itertools import pairwise
from typing import Any, Literal

import numpy as np

from minegen.core.enums import ObjectState, TaskType
from minegen.core.models import Scenario
from minegen.mining.methods.contracts import (
    ProductionScheduleContext,
    ProductionScheduleSpec,
)
from minegen.mining.methods.registry import plan_for
from minegen.network.geometry_refs import GeometryRefError, resolve_owning_centerline
from minegen.network.models import GeometryRef
from minegen.network.node_ids import level_entry_id
from minegen.scheduling.models import (
    DevelopmentTimeline,
    ProductionTimeline,
    ProductionUnitTimeline,
    StateTransition,
    StopeTimeline,
    TaskBasis,
    TimelineMetrics,
    TimelinePayload,
    TimelineTask,
)

LENGTH_SYNC_TOLERANCE = 1e-6  # m — recomputed centerline length vs edge scalar
#: Phase 20C.1-V: the excavation start node must coincide with one owning
#: centerline endpoint (the network welds nodes onto centerline endpoints)
START_NODE_WELD_TOLERANCE = 1e-3

DAY_TOLERANCE = 1e-9

_DEV_TASK_TYPE = {
    "RAMP": TaskType.DEVELOP_RAMP,
    "LEVEL_ACCESS": TaskType.DEVELOP_LEVEL_ACCESS,
    "DRIFT": TaskType.DEVELOP_LEVEL,
    "CROSSCUT": TaskType.DEVELOP_CROSSCUT,
    # Phase 20C.2B: shaft sinking collar → deeper, station drives from the station
    "SHAFT": TaskType.DEVELOP_SHAFT,
    "SHAFT_STATION_ACCESS": TaskType.DEVELOP_SHAFT_STATION_ACCESS,
}


def _failed(source_revision: str, reason: str) -> TimelinePayload:
    return TimelinePayload(
        status="FAILED",
        failure_reason=reason,
        source_revision=source_revision,
        start_day=0.0,
        end_day=0.0,
        tasks=[],
        developments=[],
        stopes=[],
        metrics=None,
    )


def solve_earliest_start(tasks: dict[str, TimelineTask]) -> str | None:
    """Deterministic precedence-only earliest-start solve IN PLACE (rule 82).

    Validates self/missing dependencies and acyclicity (deterministic Kahn
    with stable task-ID tie-breaking), then assigns
    ``startDay = max(dependency endDay, default 0)`` and
    ``endDay = startDay + durationDays``. Returns a failure reason or None."""
    for t in tasks.values():
        if t.id in t.dependencies:
            return f"task {t.id} depends on itself"
        for d in t.dependencies:
            if d not in tasks:
                return f"task {t.id} references missing dependency {d}"
    indegree = {tid: len(t.dependencies) for tid, t in tasks.items()}
    dependents: dict[str, list[str]] = {tid: [] for tid in tasks}
    for t in tasks.values():
        for d in t.dependencies:
            dependents[d].append(t.id)
    ready = [tid for tid, n in indegree.items() if n == 0]
    heapq.heapify(ready)
    order: list[str] = []
    while ready:
        tid = heapq.heappop(ready)  # stable task-ID tie breaker
        order.append(tid)
        for nxt in dependents[tid]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                heapq.heappush(ready, nxt)
    if len(order) != len(tasks):
        stuck = sorted(tid for tid, n in indegree.items() if n > 0)[:5]
        return f"task graph contains a cycle (unresolved: {stuck})"
    for tid in order:
        t = tasks[tid]
        start = max((tasks[d].end_day for d in t.dependencies), default=0.0)
        t.start_day = start
        t.end_day = start + t.duration_days
    return None


def _resolve_centerline(
    ref: Any,
    smoothed_payload: dict[str, Any],
    levels_payload: dict[str, Any],
    accesses_payload: dict[str, Any] | None = None,
    shafts_payload: dict[str, Any] | None = None,
) -> tuple[list[float] | None, str | None]:
    """Safely resolve a GeometryRef to its owning centerline points
    (blocker 2): malformed references return a reason, never raise
    KeyError / IndexError / TypeError. AC-01I: the ONE shared reference
    resolver (``network/geometry_refs.py``) decides; this is its
    reason-returning adapter for the builder's typed FAILED payloads."""
    try:
        resolved = resolve_owning_centerline(
            ref,
            smoothed_payload=smoothed_payload,
            levels_payload=levels_payload,
            accesses_payload=accesses_payload,
            shafts_payload=shafts_payload,
        )
    except GeometryRefError as exc:
        return None, str(exc)
    return resolved.points, None


def _chainage(points: list[float]) -> tuple[list[float], float]:
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(cum[-1])
    if total <= 0.0:
        return [], 0.0
    frac = cum / total
    frac[0] = 0.0
    frac[-1] = 1.0
    return [float(f) for f in frac], total


class MineTimelineBuilder:
    """Builds ``timeline.json`` from network + stopes + owning centerlines."""

    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario
        self.schedule = scenario.schedule

    def build(
        self,
        network_payload: dict[str, Any],
        stopes_payload: dict[str, Any],
        smoothed_payload: dict[str, Any],
        levels_payload: dict[str, Any],
        source_revision: str,
        accesses_payload: dict[str, Any] | None = None,
        shafts_payload: dict[str, Any] | None = None,
    ) -> TimelinePayload:
        sch = self.schedule
        # -- prerequisite gates (rule 86): FAILED inputs never schedule ------ #
        if network_payload.get("status") != "SUCCESS":
            return _failed(
                source_revision,
                f"prerequisite network artifact status {network_payload.get('status')!r} "
                "is not consumable — partial geometry is never scheduled",
            )
        if stopes_payload.get("status") != "SUCCESS":
            return _failed(
                source_revision,
                f"prerequisite stopes artifact status {stopes_payload.get('status')!r} "
                "is not consumable — partial geometry is never scheduled",
            )

        # -- identity / reference integrity gate (blocker 2) ----------------- #
        # Uniqueness is VALIDATED explicitly, never established by silent
        # dict-assignment overwrite.
        node_list = network_payload["nodes"]
        node_ids = [n["id"] for n in node_list]
        if len(set(node_ids)) != len(node_ids):
            dup = sorted({i for i in node_ids if node_ids.count(i) > 1})[:3]
            return _failed(source_revision, f"duplicate network node ids: {dup}")
        edges = network_payload["edges"]
        edge_ids = [e["id"] for e in edges]
        if len(set(edge_ids)) != len(edge_ids):
            dup = sorted({i for i in edge_ids if edge_ids.count(i) > 1})[:3]
            return _failed(source_revision, f"duplicate network edge ids: {dup}")
        # Phase 21B/C: the mining-method plan is the ONLY method authority —
        # the builder never inspects ``scenario.mining.method`` itself.
        plan = plan_for(self.scenario.mining.method)
        unit_id_list, unit_noun = plan.production_identity(stopes_payload)
        if len(set(unit_id_list)) != len(unit_id_list):
            dup = sorted({i for i in unit_id_list if unit_id_list.count(i) > 1})[:3]
            return _failed(source_revision, f"duplicate {unit_noun} ids: {dup}")
        nodes = {n["id"]: n for n in node_list}
        for e in edges:
            for endpoint in (e["fromNode"], e["toNode"]):
                if endpoint not in nodes:
                    return _failed(
                        source_revision,
                        f"edge {e['id']} references missing node {endpoint}",
                    )

        # -- development tasks: exactly one per physical edge (rule 82) ------ #
        tasks: dict[str, TimelineTask] = {}

        def add_task(task: TimelineTask) -> str | None:
            """Checked insertion (blocker 2): a duplicate generated task ID is
            an explicit failure, never a silent overwrite."""
            if task.id in tasks:
                return f"duplicate generated task id {task.id}"
            tasks[task.id] = task
            return None

        dev_task_by_edge: dict[str, str] = {}
        rate_by_type = {
            "RAMP": (sch.ramp_advance_m_per_day, "m/day"),
            "LEVEL_ACCESS": (sch.level_access_advance_m_per_day, "m/day"),
            "DRIFT": (sch.drift_advance_m_per_day, "m/day"),
            "CROSSCUT": (sch.crosscut_advance_m_per_day, "m/day"),
            "SHAFT": (sch.shaft_sink_m_per_day, "m/day"),
            "SHAFT_STATION_ACCESS": (sch.shaft_station_access_advance_m_per_day, "m/day"),
        }
        for e in edges:
            etype = e["type"]
            if etype not in _DEV_TASK_TYPE:
                return _failed(
                    source_revision,
                    f"UNSUPPORTED_DEVELOPMENT_TYPE: edge {e['id']} has type {etype} — "
                    "RAISE scheduling is not implemented and is never silently ignored",
                )
            rate, rate_unit = rate_by_type[etype]
            length = float(e["length3d"])
            duration = length / float(rate)
            if not (duration > 0.0 and math.isfinite(duration)):
                return _failed(
                    source_revision, f"non-positive development duration for edge {e['id']}"
                )
            task_id = f"TASK:DEVELOP:{e['id']}"
            add_failure = add_task(
                TimelineTask(
                    id=task_id,
                    task_type=_DEV_TASK_TYPE[etype],
                    target_kind="DEVELOPMENT",
                    target_id=e["id"],
                    duration_days=duration,
                    start_day=0.0,
                    end_day=0.0,
                    dependencies=[],
                    basis=TaskBasis(
                        quantity=length,
                        quantity_unit="m",
                        rate=float(rate),
                        rate_unit=rate_unit,
                    ),
                )
            )
            if add_failure is not None:
                return _failed(source_revision, add_failure)
            dev_task_by_edge[e["id"]] = task_id

        # -- RAMP precedence: topology-validated portal→deeper chain (§6) ---- #
        ramp_edges = [e for e in edges if e["type"] == "RAMP"]
        ramp_by_from = {e["fromNode"]: e for e in ramp_edges}
        if len(ramp_by_from) != len(ramp_edges):
            return _failed(source_revision, "ramp chain branches: duplicate fromNode")
        portal_ids = [n["id"] for n in network_payload["nodes"] if n["type"] == "PORTAL"]
        if len(portal_ids) != 1:
            return _failed(source_revision, f"expected exactly one PORTAL, got {len(portal_ids)}")
        chain: list[dict[str, Any]] = []
        cursor = portal_ids[0]
        walked: set[str] = set()
        while cursor in ramp_by_from:
            if cursor in walked:
                return _failed(source_revision, "ramp chain contains a cycle")
            walked.add(cursor)
            e = ramp_by_from.pop(cursor)
            chain.append(e)
            cursor = e["toNode"]
        if ramp_by_from:
            leftovers = sorted(e["id"] for e in ramp_by_from.values())
            return _failed(
                source_revision,
                f"ramp chain is not continuous from the PORTAL: unreached {leftovers}",
            )
        ramp_task_by_entry: dict[str, str] = {}
        prev_task: str | None = None
        # Phase 20C.1-V: the node every development is excavated FROM (rule
        # 174) — the portal side of each ramp segment, the junction of each
        # access, the endpoint reached first for level development
        start_node_by_edge: dict[str, str] = {}
        for e in chain:
            tid = dev_task_by_edge[e["id"]]
            if prev_task is not None:
                tasks[tid].dependencies.append(prev_task)
            ramp_task_by_entry[e["toNode"]] = tid
            start_node_by_edge[e["id"]] = str(e["fromNode"])
            prev_task = tid

        # -- Phase 20B level accesses: RAMP_JUNCTION → LEVEL_ENTRY (rule 157) --- #
        # an access branch starts once the ramp task reaching its junction is
        # done; the level entry it reaches is then the root of that level's
        # development. A ramp RL crossing never establishes access by itself.
        for e in sorted((e for e in edges if e["type"] == "LEVEL_ACCESS"), key=lambda e: e["id"]):
            ramp_task = ramp_task_by_entry.get(e["fromNode"])
            if ramp_task is None:
                return _failed(
                    source_revision,
                    f"no RAMP task reaches the junction {e['fromNode']} of {e['id']}",
                )
            tid = dev_task_by_edge[e["id"]]
            tasks[tid].dependencies.append(ramp_task)
            ramp_task_by_entry[e["toNode"]] = tid
            start_node_by_edge[e["id"]] = str(e["fromNode"])

        # -- Phase 20C.2B shafts: sink collar → deeper, then station drives ---- #
        # A shaft is sunk from its SHAFT_COLLAR (a surface node) segment by
        # segment; a station drive starts once the sinking task reaches its
        # SHAFT_STATION and is excavated FROM the station toward the level
        # node (rule 174). Level development stays rooted at the ramp access
        # (rule 85) — a shaft adds connectivity, never a second root.
        shaft_by_from: dict[str, dict[str, Any]] = {}
        for e in edges:
            if e["type"] == "SHAFT":
                if e["fromNode"] in shaft_by_from:
                    return _failed(source_revision, f"shaft chain branches at {e['fromNode']}")
                shaft_by_from[e["fromNode"]] = e
        shaft_task_by_station: dict[str, str] = {}
        collar_ids = sorted(n["id"] for n in node_list if n["type"] == "SHAFT_COLLAR")
        for cid in collar_ids:
            cursor = cid
            prev_shaft_task: str | None = None
            walked_shaft: set[str] = set()
            while cursor in shaft_by_from:
                if cursor in walked_shaft:
                    return _failed(source_revision, f"shaft chain from {cid} contains a cycle")
                walked_shaft.add(cursor)
                e = shaft_by_from.pop(cursor)
                tid = dev_task_by_edge[e["id"]]
                if prev_shaft_task is not None:
                    tasks[tid].dependencies.append(prev_shaft_task)
                shaft_task_by_station[e["toNode"]] = tid
                start_node_by_edge[e["id"]] = str(e["fromNode"])
                prev_shaft_task = tid
                cursor = e["toNode"]
        if shaft_by_from:
            leftovers = sorted(e["id"] for e in shaft_by_from.values())
            return _failed(
                source_revision, f"shaft edges are not reachable from a SHAFT_COLLAR: {leftovers}"
            )
        for e in sorted(
            (e for e in edges if e["type"] == "SHAFT_STATION_ACCESS"), key=lambda e: e["id"]
        ):
            sink_task = shaft_task_by_station.get(e["fromNode"])
            if sink_task is None:
                return _failed(
                    source_revision,
                    f"no SHAFT sinking task reaches the station {e['fromNode']} of {e['id']}",
                )
            tid = dev_task_by_edge[e["id"]]
            tasks[tid].dependencies.append(sink_task)
            start_node_by_edge[e["id"]] = str(e["fromNode"])

        # -- level-development access precedence (§7, rule 85) --------------- #
        level_edges = [e for e in edges if e["type"] in ("DRIFT", "CROSSCUT")]
        by_level: dict[str, list[dict[str, Any]]] = {}
        for e in level_edges:
            level_id = nodes[e["toNode"]].get("levelId") or nodes[e["fromNode"]].get("levelId")
            if level_id is None:
                return _failed(source_revision, f"development edge {e['id']} has no level id")
            by_level.setdefault(str(level_id), []).append(e)

        for level_id in sorted(by_level):
            entry_id = level_entry_id(level_id)
            if entry_id not in nodes:
                return _failed(source_revision, f"missing LEVEL_ENTRY node for {level_id}")
            ramp_task = ramp_task_by_entry.get(entry_id)
            if ramp_task is None:
                return _failed(source_revision, f"no RAMP task establishes access to {entry_id}")
            devs = sorted(by_level[level_id], key=lambda e: str(e["id"]))
            adjacency: dict[str, list[tuple[str, dict[str, Any]]]] = {}
            for e in devs:
                adjacency.setdefault(e["fromNode"], []).append((e["toNode"], e))
                adjacency.setdefault(e["toNode"], []).append((e["fromNode"], e))
            for neigh in adjacency.values():
                neigh.sort(key=lambda t: (str(t[1]["id"]), t[0]))
            # deterministic Dijkstra: duration weights, (dist, nodeId) heap
            dist: dict[str, float] = {entry_id: 0.0}
            pred_edge: dict[str, dict[str, Any] | None] = {entry_id: None}
            heap: list[tuple[float, str]] = [(0.0, entry_id)]
            visited: set[str] = set()
            while heap:
                du, u = heapq.heappop(heap)
                if u in visited:
                    continue
                visited.add(u)
                for v, e in adjacency.get(u, []):
                    w = tasks[dev_task_by_edge[e["id"]]].duration_days
                    nd = du + w
                    if v not in dist or nd < dist[v] - DAY_TOLERANCE:
                        dist[v] = nd
                        pred_edge[v] = e
                        heapq.heappush(heap, (nd, v))
            for e in devs:
                a, b = e["fromNode"], e["toNode"]
                if a not in dist and b not in dist:
                    return _failed(
                        source_revision,
                        f"development edge {e['id']} is unreachable from {entry_id} "
                        "— required development cannot be accessed (rule 85)",
                    )
                # launch endpoint: reached first (deterministic (dist, id) order)
                candidates = [(dist[n], n) for n in (a, b) if n in dist]
                _, launch = min(candidates)
                launch_pred = pred_edge.get(launch)
                tid = dev_task_by_edge[e["id"]]
                if launch == entry_id or launch_pred is None:
                    dep = ramp_task
                    start_node_by_edge[e["id"]] = str(launch)
                elif launch_pred["id"] == e["id"]:
                    # the edge itself established access to this endpoint: its
                    # OTHER endpoint's predecessor provides the launch access
                    other = a if launch == b else b
                    other_pred = pred_edge.get(other)
                    dep = (
                        ramp_task
                        if other == entry_id or other_pred is None
                        else dev_task_by_edge[other_pred["id"]]
                    )
                    start_node_by_edge[e["id"]] = str(other)
                else:
                    dep = dev_task_by_edge[launch_pred["id"]]
                    start_node_by_edge[e["id"]] = str(launch)
                if dep != tid:
                    tasks[tid].dependencies.append(dep)

        # -- production schedule from the method plan (Phase 21B/C) ---------- #
        # The CROSSCUT development tasks terminating at each access node and
        # the development task of every physical edge are the validated
        # context a method may depend on; the plan returns its task graph.
        cc_task_by_access: dict[str, list[str]] = {}
        for e in edges:
            if e["type"] == "CROSSCUT":
                cc_task_by_access.setdefault(e["toNode"], []).append(dev_task_by_edge[e["id"]])
        spec_or_failure = plan.production_schedule(
            self.scenario,
            stopes_payload,
            ProductionScheduleContext(
                nodes=nodes,
                development_task_by_edge=dict(dev_task_by_edge),
                crosscut_tasks_by_access_node=cc_task_by_access,
                schedule=sch,
            ),
        )
        if isinstance(spec_or_failure, str):
            return _failed(source_revision, spec_or_failure)
        spec: ProductionScheduleSpec = spec_or_failure
        for pt in spec.tasks:
            if not (pt.duration_days > 0.0 and math.isfinite(pt.duration_days)):
                return _failed(source_revision, f"non-positive duration for {pt.id}")
            for dep in pt.dependencies:
                if dep not in tasks:
                    return _failed(
                        source_revision,
                        f"production task {pt.id} depends on unknown task {dep}",
                    )
            add_failure = add_task(
                TimelineTask(
                    id=pt.id,
                    task_type=pt.task_type,
                    target_kind=pt.target_kind,
                    target_id=pt.target_id,
                    duration_days=pt.duration_days,
                    start_day=0.0,
                    end_day=0.0,
                    dependencies=list(pt.dependencies),
                    basis=pt.basis,
                )
            )
            if add_failure is not None:
                return _failed(source_revision, add_failure)

        # -- earliest-start over a validated DAG (§4, §16) ------------------- #
        solve_failure = solve_earliest_start(tasks)
        if solve_failure is not None:
            return _failed(source_revision, solve_failure)

        # -- development timelines + chainage (rules 31/83) ------------------ #
        developments: list[DevelopmentTimeline] = []
        total_dev_len = 0.0
        for e in edges:
            ref = e["geometryRef"]
            points, resolve_failure = _resolve_centerline(
                ref, smoothed_payload, levels_payload, accesses_payload, shafts_payload
            )
            if points is None:
                return _failed(
                    source_revision,
                    f"edge {e['id']} geometryRef does not resolve: {resolve_failure}",
                )
            fractions, total = _chainage(points)
            if (
                len(fractions) < 2
                or fractions[0] != 0.0
                or fractions[-1] != 1.0
                or any(b < a for a, b in pairwise(fractions))
                or not all(math.isfinite(f) for f in fractions)
            ):
                return _failed(source_revision, f"invalid chainage fractions for edge {e['id']}")
            if abs(total - float(e["length3d"])) > LENGTH_SYNC_TOLERANCE:
                return _failed(
                    source_revision,
                    f"owning centerline of edge {e['id']} measures {total:.6f} m but "
                    f"the network edge declares {float(e['length3d']):.6f} m "
                    f"(> {LENGTH_SYNC_TOLERANCE:.0e} tolerance, rule 83)",
                )
            total_dev_len += total
            task = tasks[dev_task_by_edge[e["id"]]]
            # Phase 20C.1-V (rule 174): progress direction from the excavation
            # start node — the owning centerline endpoint welded to that node
            # is the fraction-0 end of progress; the other endpoint is the face
            start_id = start_node_by_edge.get(e["id"])
            if start_id is None or start_id not in nodes:
                return _failed(source_revision, f"edge {e['id']} has no excavation start node")
            start_pos = np.asarray(nodes[start_id]["position"], dtype=np.float64)
            pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
            d_first = float(np.linalg.norm(pts[0] - start_pos))
            d_last = float(np.linalg.norm(pts[-1] - start_pos))
            if min(d_first, d_last) > START_NODE_WELD_TOLERANCE:
                return _failed(
                    source_revision,
                    f"edge {e['id']}: excavation start node {start_id} is "
                    f"{min(d_first, d_last):.3f} m from both centerline endpoints "
                    f"(> {START_NODE_WELD_TOLERANCE} m, rule 174)",
                )
            direction: Literal[1, -1] = 1 if d_first <= d_last else -1
            developments.append(
                DevelopmentTimeline(
                    edge_id=e["id"],
                    edge_type=str(e["type"]),
                    geometry_ref=GeometryRef(
                        artifact=str(ref["artifact"]), segment_index=int(ref["segmentIndex"])
                    ),
                    task_id=task.id,
                    transitions=[
                        StateTransition(day=task.start_day, state=ObjectState.DEVELOPING),
                        StateTransition(day=task.end_day, state=ObjectState.ACTIVE),
                    ],
                    progress_start_day=task.start_day,
                    progress_end_day=task.end_day,
                    point_chainage_fractions=fractions,
                    excavation_start_node=start_id,
                    progress_direction=direction,
                )
            )

        # -- production state machines (§13, rule 84) ------------------------ #
        # Every transition is bound to a solved task boundary named by the plan.
        def unit_transitions(unit_transitions_spec: Any) -> list[StateTransition] | str:
            out: list[StateTransition] = []
            for tr in unit_transitions_spec:
                task = tasks.get(tr.task_id)
                if task is None:
                    return f"state transition references unknown task {tr.task_id}"
                day = task.start_day if tr.boundary == "start" else task.end_day
                out.append(StateTransition(day=day, state=tr.state))
            return out

        stope_timelines: list[StopeTimeline] = []
        production_units: list[ProductionUnitTimeline] = []
        for unit_spec in spec.units:
            transitions = unit_transitions(unit_spec.transitions)
            if isinstance(transitions, str):
                return _failed(source_revision, transitions)
            if spec.target_kind == "STOPE":
                stope_timelines.append(
                    StopeTimeline(stope_id=unit_spec.unit_id, transitions=transitions)
                )
            else:
                production_units.append(
                    ProductionUnitTimeline(unit_id=unit_spec.unit_id, transitions=transitions)
                )
        production_objects = stope_timelines if spec.target_kind == "STOPE" else production_units

        task_list = [tasks[tid] for tid in sorted(tasks)]
        dev_tasks = [t for t in task_list if t.target_kind == "DEVELOPMENT"]
        prod_tasks = [t for t in task_list if t.target_kind == spec.target_kind]
        # -- aggregate identity verification before SUCCESS (blocker 2) ------ #
        dev_targets = [d.edge_id for d in developments]
        unit_targets = [u.unit_id for u in spec.units]
        n_units = len(unit_id_list)
        if (
            len(dev_tasks) != len(edges)
            or len(developments) != len(edges)
            or len(prod_tasks) != spec.tasks_per_unit * n_units
            or len(production_objects) != n_units
            or len(task_list) != len(dev_tasks) + len(prod_tasks)
        ):
            return _failed(
                source_revision,
                "aggregate task/object counts do not match the input artifacts: "
                f"devTasks={len(dev_tasks)} devObjects={len(developments)} "
                f"edges={len(edges)} {unit_noun}Tasks={len(prod_tasks)} "
                f"{unit_noun}Objects={len(production_objects)} {unit_noun}s={n_units}",
            )
        if len(set(dev_targets)) != len(dev_targets) or set(dev_targets) != set(edge_ids):
            return _failed(
                source_revision, "development timeline targets are not unique or unresolved"
            )
        if len(set(unit_targets)) != len(unit_targets) or set(unit_targets) != set(unit_id_list):
            return _failed(
                source_revision, f"{unit_noun} timeline targets are not unique or unresolved"
            )
        end_day = max((t.end_day for t in task_list), default=0.0)
        stoping_starts = [t.start_day for t in prod_tasks if t.task_type is TaskType.STOPING]
        is_stope = spec.target_kind == "STOPE"
        metrics = TimelineMetrics(
            task_count=len(task_list),
            development_task_count=len(dev_tasks),
            stope_task_count=len(prod_tasks) if is_stope else 0,
            development_object_count=len(developments),
            stope_object_count=len(stope_timelines),
            total_development_length3d=total_dev_len,
            total_scheduled_tonnes=spec.scheduled_tonnes,
            ramp_completion_day=max(
                (tasks[dev_task_by_edge[e["id"]]].end_day for e in ramp_edges), default=0.0
            ),
            first_stoping_day=min(stoping_starts) if stoping_starts else None,
            end_day=end_day,
            production_task_count=None if is_stope else len(prod_tasks),
            production_object_count=None if is_stope else len(production_units),
            production_target_kind=None if is_stope else spec.target_kind,
        )
        production_block = (
            None
            if is_stope
            else ProductionTimeline(
                method=self.scenario.mining.method.value,
                target_kind=spec.target_kind,
                units=production_units,
            )
        )
        return TimelinePayload(
            status="SUCCESS",
            failure_reason=None,
            source_revision=source_revision,
            start_day=0.0,
            end_day=end_day,
            tasks=task_list,
            developments=developments,
            stopes=stope_timelines,
            metrics=metrics,
            production=production_block,
        )
