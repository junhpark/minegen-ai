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
from typing import Any

import numpy as np

from minegen.core.enums import ObjectState, TaskType
from minegen.core.models import Scenario
from minegen.network.models import GeometryRef
from minegen.scheduling.models import (
    DevelopmentTimeline,
    StateTransition,
    StopeTimeline,
    TaskBasis,
    TimelineMetrics,
    TimelinePayload,
    TimelineTask,
)

LENGTH_SYNC_TOLERANCE = 1e-6  # m — recomputed centerline length vs edge scalar
DAY_TOLERANCE = 1e-9

_DEV_TASK_TYPE = {
    "RAMP": TaskType.DEVELOP_RAMP,
    "DRIFT": TaskType.DEVELOP_LEVEL,
    "CROSSCUT": TaskType.DEVELOP_CROSSCUT,
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

        nodes = {n["id"]: n for n in network_payload["nodes"]}
        edges = network_payload["edges"]

        # -- development tasks: exactly one per physical edge (rule 82) ------ #
        tasks: dict[str, TimelineTask] = {}
        dev_task_by_edge: dict[str, str] = {}
        rate_by_type = {
            "RAMP": (sch.ramp_advance_m_per_day, "m/day"),
            "DRIFT": (sch.drift_advance_m_per_day, "m/day"),
            "CROSSCUT": (sch.crosscut_advance_m_per_day, "m/day"),
        }
        for e in edges:
            etype = e["type"]
            if etype not in _DEV_TASK_TYPE:
                return _failed(
                    source_revision,
                    f"UNSUPPORTED_DEVELOPMENT_TYPE: edge {e['id']} has type {etype} — "
                    "RAISE/SHAFT scheduling is not implemented in Phase 10 and is "
                    "never silently ignored",
                )
            rate, rate_unit = rate_by_type[etype]
            length = float(e["length3d"])
            duration = length / float(rate)
            if not (duration > 0.0 and math.isfinite(duration)):
                return _failed(
                    source_revision, f"non-positive development duration for edge {e['id']}"
                )
            task_id = f"TASK:DEVELOP:{e['id']}"
            tasks[task_id] = TimelineTask(
                id=task_id,
                task_type=_DEV_TASK_TYPE[etype],
                target_kind="DEVELOPMENT",
                target_id=e["id"],
                duration_days=duration,
                start_day=0.0,
                end_day=0.0,
                dependencies=[],
                basis=TaskBasis(
                    quantity=length, quantity_unit="m", rate=float(rate), rate_unit=rate_unit
                ),
            )
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
        for e in chain:
            tid = dev_task_by_edge[e["id"]]
            if prev_task is not None:
                tasks[tid].dependencies.append(prev_task)
            ramp_task_by_entry[e["toNode"]] = tid
            prev_task = tid

        # -- level-development access precedence (§7, rule 85) --------------- #
        level_edges = [e for e in edges if e["type"] in ("DRIFT", "CROSSCUT")]
        by_level: dict[str, list[dict[str, Any]]] = {}
        for e in level_edges:
            level_id = nodes[e["toNode"]].get("levelId") or nodes[e["fromNode"]].get("levelId")
            if level_id is None:
                return _failed(source_revision, f"development edge {e['id']} has no level id")
            by_level.setdefault(str(level_id), []).append(e)

        for level_id in sorted(by_level):
            entry_id = f"LEVEL_ENTRY:{level_id}"
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
                else:
                    dep = dev_task_by_edge[launch_pred["id"]]
                if dep != tid:
                    tasks[tid].dependencies.append(dep)

        # -- stope access + five-task chains (§8–§9) ------------------------- #
        cc_task_by_access: dict[str, list[str]] = {}
        for e in edges:
            if e["type"] == "CROSSCUT":
                cc_task_by_access.setdefault(e["toNode"], []).append(dev_task_by_edge[e["id"]])
        stopes = stopes_payload["stopes"]
        stope_task_ids: dict[str, dict[str, str]] = {}
        for s in stopes:
            deps_access: list[str] = []
            for anchor_key in ("upperAccessNodeId", "lowerAccessNodeId"):
                anchor = s[anchor_key]
                if anchor not in nodes:
                    return _failed(
                        source_revision,
                        f"stope {s['id']} references access anchor {anchor} that does "
                        "not exist in the network",
                    )
                cc = cc_task_by_access.get(anchor, [])
                if len(cc) != 1:
                    return _failed(
                        source_revision,
                        f"access anchor {anchor} of stope {s['id']} must terminate "
                        f"exactly one CROSSCUT development, found {len(cc)}",
                    )
                deps_access.append(cc[0])
            tonnes = float(s["tonnes"])
            volume = float(s["geometricVolumeM3"])
            sid = s["id"]
            chain_spec = [
                (
                    f"TASK:PREP:{sid}",
                    TaskType.STOPE_PREPARATION,
                    float(sch.stope_preparation_days),
                    TaskBasis(
                        quantity=float(sch.stope_preparation_days),
                        quantity_unit="day",
                        rate=1.0,
                        rate_unit="day/day",
                    ),
                    sorted(deps_access),
                ),
                (
                    f"TASK:STOPING:{sid}",
                    TaskType.STOPING,
                    tonnes / float(sch.stoping_tonnes_per_day),
                    TaskBasis(
                        quantity=tonnes,
                        quantity_unit="t",
                        rate=float(sch.stoping_tonnes_per_day),
                        rate_unit="t/day",
                    ),
                    [f"TASK:PREP:{sid}"],
                ),
                (
                    f"TASK:MUCKING:{sid}",
                    TaskType.MUCKING,
                    tonnes / float(sch.mucking_tonnes_per_day),
                    TaskBasis(
                        quantity=tonnes,
                        quantity_unit="t",
                        rate=float(sch.mucking_tonnes_per_day),
                        rate_unit="t/day",
                    ),
                    [f"TASK:STOPING:{sid}"],
                ),
                (
                    f"TASK:BACKFILL:{sid}",
                    TaskType.BACKFILL,
                    volume / float(sch.backfill_m3_per_day),
                    TaskBasis(
                        quantity=volume,
                        quantity_unit="m3",
                        rate=float(sch.backfill_m3_per_day),
                        rate_unit="m3/day",
                    ),
                    [f"TASK:MUCKING:{sid}"],
                ),
                (
                    f"TASK:CURE:{sid}",
                    TaskType.CURE_BACKFILL,
                    float(sch.backfill_cure_days),
                    TaskBasis(
                        quantity=float(sch.backfill_cure_days),
                        quantity_unit="day",
                        rate=1.0,
                        rate_unit="day/day",
                    ),
                    [f"TASK:BACKFILL:{sid}"],
                ),
            ]
            ids: dict[str, str] = {}
            for tid, ttype, duration, basis, deps in chain_spec:
                if not (duration > 0.0 and math.isfinite(duration)):
                    return _failed(source_revision, f"non-positive duration for {tid}")
                tasks[tid] = TimelineTask(
                    id=tid,
                    task_type=ttype,
                    target_kind="STOPE",
                    target_id=sid,
                    duration_days=duration,
                    start_day=0.0,
                    end_day=0.0,
                    dependencies=list(deps),
                    basis=basis,
                )
                ids[ttype.value] = tid
            stope_task_ids[sid] = ids

        # -- earliest-start over a validated DAG (§4, §16) ------------------- #
        solve_failure = solve_earliest_start(tasks)
        if solve_failure is not None:
            return _failed(source_revision, solve_failure)

        # -- development timelines + chainage (rules 31/83) ------------------ #
        developments: list[DevelopmentTimeline] = []
        total_dev_len = 0.0
        for e in edges:
            ref = e["geometryRef"]
            artifact = ref["artifact"]
            idx = int(ref["segmentIndex"])
            if artifact == "decline_smoothed.json":
                points = smoothed_payload["segments"][idx]["effectiveCenterline"]["points"]
            elif artifact == "levels.json":
                points = levels_payload["developments"][idx]["centerline"]["points"]
            else:
                return _failed(
                    source_revision, f"edge {e['id']} references unknown artifact {artifact}"
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
            developments.append(
                DevelopmentTimeline(
                    edge_id=e["id"],
                    edge_type=str(e["type"]),
                    geometry_ref=GeometryRef(artifact=artifact, segment_index=idx),
                    task_id=task.id,
                    transitions=[
                        StateTransition(day=task.start_day, state=ObjectState.DEVELOPING),
                        StateTransition(day=task.end_day, state=ObjectState.ACTIVE),
                    ],
                    progress_start_day=task.start_day,
                    progress_end_day=task.end_day,
                    point_chainage_fractions=fractions,
                )
            )

        # -- stope state machines (§13, rule 84) ----------------------------- #
        stope_timelines: list[StopeTimeline] = []
        for s in stopes:
            ids = stope_task_ids[s["id"]]
            prep = tasks[ids[TaskType.STOPE_PREPARATION.value]]
            stoping = tasks[ids[TaskType.STOPING.value]]
            mucking = tasks[ids[TaskType.MUCKING.value]]
            backfill = tasks[ids[TaskType.BACKFILL.value]]
            cure = tasks[ids[TaskType.CURE_BACKFILL.value]]
            stope_timelines.append(
                StopeTimeline(
                    stope_id=s["id"],
                    transitions=[
                        StateTransition(day=prep.start_day, state=ObjectState.DEVELOPING),
                        StateTransition(day=stoping.start_day, state=ObjectState.ACTIVE),
                        StateTransition(day=stoping.end_day, state=ObjectState.MINED),
                        StateTransition(day=mucking.end_day, state=ObjectState.VOID),
                        StateTransition(day=backfill.end_day, state=ObjectState.BACKFILLED),
                        StateTransition(day=cure.end_day, state=ObjectState.CLOSED),
                    ],
                )
            )

        task_list = [tasks[tid] for tid in sorted(tasks)]
        dev_tasks = [t for t in task_list if t.target_kind == "DEVELOPMENT"]
        stope_tasks = [t for t in task_list if t.target_kind == "STOPE"]
        end_day = max((t.end_day for t in task_list), default=0.0)
        stoping_starts = [t.start_day for t in stope_tasks if t.task_type is TaskType.STOPING]
        metrics = TimelineMetrics(
            task_count=len(task_list),
            development_task_count=len(dev_tasks),
            stope_task_count=len(stope_tasks),
            development_object_count=len(developments),
            stope_object_count=len(stope_timelines),
            total_development_length3d=total_dev_len,
            total_scheduled_tonnes=float(math.fsum(float(s["tonnes"]) for s in stopes)),
            ramp_completion_day=max(
                (tasks[dev_task_by_edge[e["id"]]].end_day for e in ramp_edges), default=0.0
            ),
            first_stoping_day=min(stoping_starts) if stoping_starts else None,
            end_day=end_day,
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
        )
