"""Phase 11 — Communication OSP builder (rules 87–92).

Deterministic connected communication placement baseline on the validated
MineNetwork. The core invariant (rule 88): coverage and backhaul use the
shortest PHYSICAL path distance through the MineNetwork
(network-geodesic distance along RAMP/DRIFT/CROSSCUT developments), never
Euclidean through-rock distance. ``NETWORK_DISTANCE_THRESHOLD_V0_1`` is an
explicit planning proxy — no RSSI/dBm/frequency/antenna/Fresnel/ray-tracing
is computed and none is claimed.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from minegen.core.enums import AssetType
from minegen.core.models import Scenario
from minegen.infrastructure.models import (
    COVERAGE_MODEL_ID,
    SOLVER_ID,
    CandidateSite,
    CommunicationAsset,
    CommunicationMetrics,
    CommunicationModelSummary,
    CommunicationPayload,
    DemandCoverage,
    DemandPoint,
    PlacementProblem,
)
from minegen.infrastructure.solver import solve_connected_greedy

LENGTH_SYNC_TOLERANCE = 1e-6  # m — recomputed centerline vs edge.length3d
ENDPOINT_TOLERANCE = 1e-6  # m — centerline ends vs from/to node positions
DISTANCE_TOLERANCE = 1e-6  # m — documented coverage/backhaul comparison slack

_SUPPORTED_EDGE_TYPES = ("RAMP", "DRIFT", "CROSSCUT")
_OWNING_ARTIFACT = {
    "RAMP": "decline_smoothed.json",
    "DRIFT": "levels.json",
    "CROSSCUT": "levels.json",
}


def _failed(source_revision: str, reason: str) -> CommunicationPayload:
    return CommunicationPayload(
        status="FAILED",
        failure_reason=reason,
        source_revision=source_revision,
        model=None,
        candidates=[],
        demands=[],
        selected_assets=[],
        demand_coverage=[],
        metrics=None,
    )


class _EdgeGeometry:
    """Resolved owning-centerline geometry for one physical edge."""

    def __init__(self, points: np.ndarray) -> None:
        self.points = points
        seg = np.linalg.norm(np.diff(points, axis=0), axis=1)
        self.cum = np.concatenate([[0.0], np.cumsum(seg)])
        self.length = float(self.cum[-1])

    def position_at(self, chainage: float) -> tuple[float, float, float]:
        c = min(max(chainage, 0.0), self.length)
        i = int(np.searchsorted(self.cum, c, side="right") - 1)
        i = min(max(i, 0), len(self.cum) - 2)
        span = self.cum[i + 1] - self.cum[i]
        t = 0.0 if span <= 0 else (c - self.cum[i]) / span
        p = self.points[i] + (self.points[i + 1] - self.points[i]) * t
        return (float(p[0]), float(p[1]), float(p[2]))


class CommunicationBuilder:
    """Builds ``communication.json`` from network + owning centerlines."""

    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario
        self.config = scenario.infrastructure.communication

    def build(
        self,
        network_payload: dict[str, Any],
        smoothed_payload: dict[str, Any],
        levels_payload: dict[str, Any],
        source_revision: str,
    ) -> CommunicationPayload:
        cfg = self.config
        # -- supported asset gate (§2): never silently substitute ------------ #
        if cfg.asset_type is not AssetType.MESH_ROUTER:
            return _failed(
                source_revision,
                f"UNSUPPORTED_COMMUNICATION_ASSET_TYPE: {cfg.asset_type.value} is "
                "reserved — Phase 11 v0.1 implements MESH_ROUTER only",
            )
        # -- prerequisite gates (§6) ----------------------------------------- #
        if network_payload.get("status") != "SUCCESS":
            return _failed(
                source_revision,
                f"prerequisite network artifact status {network_payload.get('status')!r} "
                "is not consumable",
            )
        validation = network_payload.get("validation") or {}
        if not (validation.get("connected") and validation.get("synchronized")):
            return _failed(
                source_revision,
                "network validation is not connected+synchronized — communication "
                "planning requires a physically connected, synchronized MineNetwork",
            )

        # -- network integrity gate (§7) ------------------------------------- #
        node_list = network_payload.get("nodes") or []
        edge_list = network_payload.get("edges") or []
        node_ids = [n["id"] for n in node_list]
        if len(set(node_ids)) != len(node_ids):
            dup = sorted({i for i in node_ids if node_ids.count(i) > 1})[:3]
            return _failed(source_revision, f"duplicate network node ids: {dup}")
        edge_ids = [e["id"] for e in edge_list]
        if len(set(edge_ids)) != len(edge_ids):
            dup = sorted({i for i in edge_ids if edge_ids.count(i) > 1})[:3]
            return _failed(source_revision, f"duplicate network edge ids: {dup}")
        portal_ids = [n["id"] for n in node_list if n.get("type") == "PORTAL"]
        if len(portal_ids) != 1:
            return _failed(
                source_revision, f"expected exactly one PORTAL node, got {len(portal_ids)}"
            )
        portal_id = portal_ids[0]
        nodes = {n["id"]: n for n in node_list}
        for e in edge_list:
            if e.get("type") not in _SUPPORTED_EDGE_TYPES:
                return _failed(
                    source_revision,
                    f"UNSUPPORTED_COMMUNICATION_EDGE_TYPE: edge {e.get('id')} has type "
                    f"{e.get('type')} — RAISE/SHAFT communication planning is deferred "
                    "until owning geometry exists",
                )
            for endpoint in (e.get("fromNode"), e.get("toNode")):
                if endpoint not in nodes:
                    return _failed(
                        source_revision, f"edge {e['id']} references missing node {endpoint}"
                    )
            length = e.get("length3d")
            if not isinstance(length, (int, float)) or not math.isfinite(length) or length <= 0:
                return _failed(
                    source_revision, f"edge {e['id']} has non-positive length3d {length!r}"
                )

        # -- owning geometry resolution + orientation (§8) -------------------- #
        geometries: dict[str, _EdgeGeometry] = {}
        for e in edge_list:
            expected_artifact = _OWNING_ARTIFACT[e["type"]]
            ref = e.get("geometryRef")
            if not isinstance(ref, dict):
                return _failed(source_revision, f"edge {e['id']} geometryRef is not an object")
            artifact = ref.get("artifact")
            if artifact != expected_artifact:
                return _failed(
                    source_revision,
                    f"edge {e['id']} of type {e['type']} must be owned by "
                    f"{expected_artifact}, geometryRef points to {artifact!r}",
                )
            raw_index = ref.get("segmentIndex")
            if not isinstance(raw_index, int) or isinstance(raw_index, bool) or raw_index < 0:
                return _failed(
                    source_revision,
                    f"edge {e['id']} segmentIndex {raw_index!r} is not a non-negative integer",
                )
            owners = (
                smoothed_payload.get("segments")
                if artifact == "decline_smoothed.json"
                else levels_payload.get("developments")
            )
            container = (
                "effectiveCenterline" if artifact == "decline_smoothed.json" else "centerline"
            )
            if not isinstance(owners, list) or raw_index >= len(owners):
                count = len(owners) if isinstance(owners, list) else 0
                return _failed(
                    source_revision,
                    f"edge {e['id']} segmentIndex {raw_index} is out of range for "
                    f"{artifact} ({count} entries)",
                )
            owner = owners[raw_index]
            centerline = owner.get(container) if isinstance(owner, dict) else None
            raw_points = centerline.get("points") if isinstance(centerline, dict) else None
            if not isinstance(raw_points, list) or len(raw_points) < 6:
                return _failed(
                    source_revision,
                    f"edge {e['id']} owning centerline is missing or has < 2 points",
                )
            pts = np.asarray(raw_points, dtype=np.float64).reshape(-1, 3)
            if not np.all(np.isfinite(pts)):
                return _failed(
                    source_revision, f"edge {e['id']} owning centerline has non-finite points"
                )
            geom = _EdgeGeometry(pts)
            if abs(geom.length - float(e["length3d"])) > LENGTH_SYNC_TOLERANCE:
                return _failed(
                    source_revision,
                    f"edge {e['id']} owning centerline measures {geom.length:.6f} m but "
                    f"the edge declares {float(e['length3d']):.6f} m (> 1e-6 tolerance)",
                )
            # orientation: the Phase 07/08 contract stores centerlines in
            # canonical fromNode -> toNode direction (verified against the
            # accepted default: worst end deviation 1.4e-14 m)
            from_pos = np.asarray(nodes[e["fromNode"]]["position"], dtype=np.float64)
            to_pos = np.asarray(nodes[e["toNode"]]["position"], dtype=np.float64)
            if (
                float(np.linalg.norm(pts[0] - from_pos)) > ENDPOINT_TOLERANCE
                or float(np.linalg.norm(pts[-1] - to_pos)) > ENDPOINT_TOLERANCE
            ):
                return _failed(
                    source_revision,
                    f"edge {e['id']} centerline orientation does not match the canonical "
                    "fromNode->toNode contract within 1e-6 m",
                )
            geometries[e["id"]] = geom

        # -- deterministic sampling (§10–§11, rule 89) ------------------------ #
        node_order = sorted(nodes)
        edge_order = sorted(e["id"] for e in edge_list)
        edges_by_id = {e["id"]: e for e in edge_list}

        def sample(
            spacing: float, prefix: str
        ) -> list[tuple[str, str | None, str | None, float | None, tuple[float, float, float]]]:
            out: list[
                tuple[str, str | None, str | None, float | None, tuple[float, float, float]]
            ] = []
            for nid in node_order:
                p = nodes[nid]["position"]
                out.append(
                    (
                        f"{prefix}:NODE:{nid}",
                        nid,
                        None,
                        None,
                        (float(p[0]), float(p[1]), float(p[2])),
                    )
                )
            for eid in edge_order:
                geom = geometries[eid]
                k = 1
                while k * spacing < geom.length - 1e-12:
                    c = k * spacing
                    out.append((f"{prefix}:EDGE:{eid}:P{k}", None, eid, c, geom.position_at(c)))
                    k += 1
            return out

        cand_rows = sample(float(cfg.candidate_spacing_m), "COMM:CAND")
        demand_rows = sample(float(cfg.demand_spacing_m), "COMM:DEMAND")
        candidates = [
            CandidateSite(
                id=cid,
                location_kind="NODE" if nid is not None else "EDGE",
                node_id=nid,
                edge_id=eid,
                chainage_m=ch,
                position=pos,
                eligible=True,
            )
            for cid, nid, eid, ch, pos in cand_rows
        ]
        demands = [
            DemandPoint(
                id=did,
                location_kind="NODE" if nid is not None else "EDGE",
                node_id=nid,
                edge_id=eid,
                chainage_m=ch,
                position=pos,
                weight=1.0,
            )
            for did, nid, eid, ch, pos in demand_rows
        ]

        # -- network-geodesic distances (§12–§13, rule 88) -------------------- #
        node_index = {nid: i for i, nid in enumerate(node_order)}
        n_nodes = len(node_order)
        node_dist = np.full((n_nodes, n_nodes), np.inf, dtype=np.float64)
        adjacency: dict[int, list[tuple[int, float]]] = {i: [] for i in range(n_nodes)}
        for e in edge_list:
            a = node_index[e["fromNode"]]
            b = node_index[e["toNode"]]
            w = float(e["length3d"])
            adjacency[a].append((b, w))
            adjacency[b].append((a, w))
        import heapq

        for src in range(n_nodes):
            dist = node_dist[src]
            dist[src] = 0.0
            heap = [(0.0, src)]
            done = np.zeros(n_nodes, dtype=bool)
            while heap:
                d, u = heapq.heappop(heap)
                if done[u]:
                    continue
                done[u] = True
                for v, w in adjacency[u]:
                    nd = d + w
                    if nd < dist[v]:
                        dist[v] = nd
                        heapq.heappush(heap, (nd, v))
        if not np.all(np.isfinite(node_dist)):
            return _failed(
                source_revision, "network is not physically connected (infinite geodesic)"
            )

        def anchors(nid: str | None, eid: str | None, ch: float | None) -> list[tuple[int, float]]:
            if nid is not None:
                return [(node_index[nid], 0.0)]
            assert eid is not None and ch is not None
            e = edges_by_id[eid]
            return [
                (node_index[e["fromNode"]], float(ch)),
                (node_index[e["toNode"]], float(e["length3d"]) - float(ch)),
            ]

        def loc_distance(
            a: tuple[str | None, str | None, float | None],
            b: tuple[str | None, str | None, float | None],
        ) -> float:
            best = math.inf
            if a[1] is not None and a[1] == b[1]:  # same edge: direct chainage
                assert a[2] is not None and b[2] is not None
                best = abs(a[2] - b[2])
            for na, oa in anchors(*a):
                for nb, ob in anchors(*b):
                    best = min(best, oa + float(node_dist[na, nb]) + ob)
            return best

        def pairwise(
            rows_a: list[tuple[str, str | None, str | None, float | None, Any]],
            rows_b: list[tuple[str, str | None, str | None, float | None, Any]],
        ) -> np.ndarray:
            def pack(rows: list[Any]) -> tuple[np.ndarray, np.ndarray]:
                idx = np.empty((2, len(rows)), dtype=np.int64)
                off = np.empty((2, len(rows)), dtype=np.float64)
                for j, (_rid, nid, eid, ch, _pos) in enumerate(rows):
                    anc = anchors(nid, eid, ch)
                    if len(anc) == 1:
                        anc = [anc[0], anc[0]]
                    for k in (0, 1):
                        idx[k, j], off[k, j] = anc[k][0], anc[k][1]
                return idx, off

            ia, oa = pack(rows_a)
            ib, ob = pack(rows_b)
            out = np.full((len(rows_a), len(rows_b)), np.inf, dtype=np.float64)
            for k in (0, 1):
                for m in (0, 1):
                    combo = node_dist[ia[k]][:, ib[m]] + oa[k][:, None] + ob[m][None, :]
                    np.minimum(out, combo, out=out)
            # same-edge direct chainage correction
            by_edge_a: dict[str, list[int]] = {}
            for j, (_rid, _nid, eid, _ch, _pos) in enumerate(rows_a):
                if eid is not None:
                    by_edge_a.setdefault(eid, []).append(j)
            for j2, (_rid, _nid, eid, ch, _pos) in enumerate(rows_b):
                if eid is None:
                    continue
                for j1 in by_edge_a.get(eid, []):
                    direct = abs(float(rows_a[j1][3]) - float(ch))  # type: ignore[arg-type]
                    if direct < out[j1, j2]:
                        out[j1, j2] = direct
            return out

        cand_demand = pairwise(cand_rows, demand_rows)
        cand_cand = pairwise(cand_rows, cand_rows)

        # -- coverage model + placement problem (§14–§17) --------------------- #
        cov_r = float(cfg.coverage_range_m) + DISTANCE_TOLERANCE
        bh_r = float(cfg.backhaul_range_m) + DISTANCE_TOLERANCE
        cand_ids = [r[0] for r in cand_rows]
        demand_ids = [r[0] for r in demand_rows]
        coverage_sets = {
            cand_ids[i]: sorted(demand_ids[j] for j in np.flatnonzero(cand_demand[i] <= cov_r))
            for i in range(len(cand_ids))
        }
        backhaul_graph: dict[str, list[str]] = {cid: [] for cid in cand_ids}
        bh_mask = cand_cand <= bh_r
        np.fill_diagonal(bh_mask, False)
        for i in range(len(cand_ids)):
            backhaul_graph[cand_ids[i]] = sorted(cand_ids[j] for j in np.flatnonzero(bh_mask[i]))
        portal_candidate = f"COMM:CAND:NODE:{portal_id}"
        problem = PlacementProblem(
            candidates=candidates,
            demands=demands,
            candidate_coverage_sets=coverage_sets,
            candidate_backhaul_graph=backhaul_graph,
            required_coverage_fraction=float(cfg.required_coverage_fraction),
            mandatory_candidate_ids=[portal_candidate],
        )

        # -- deterministic connected-greedy baseline (§18, rule 90) ----------- #
        solution = solve_connected_greedy(problem)
        if solution.status != "SUCCESS":
            return _failed(
                source_revision,
                solution.failure_reason or "placement solve failed",
            )
        selected_ids = sorted(solution.selected_candidate_ids)
        selected_set = set(selected_ids)
        cand_index = {cid: i for i, cid in enumerate(cand_ids)}
        cand_by_id = {c.id: c for c in candidates}

        # -- final backhaul BFS tree rooted at PORTAL (§19) ------------------- #
        from collections import deque

        parent: dict[str, str | None] = {portal_candidate: None}
        hop: dict[str, int] = {portal_candidate: 0}
        queue = deque([portal_candidate])
        while queue:
            cur = queue.popleft()
            for nxt in backhaul_graph[cur]:
                if nxt in selected_set and nxt not in parent:
                    parent[nxt] = cur
                    hop[nxt] = hop[cur] + 1
                    queue.append(nxt)
        if set(parent) != selected_set:
            missing = sorted(selected_set - set(parent))[:3]
            return _failed(
                source_revision,
                f"selected routers are not connected to the PORTAL root: {missing}",
            )
        assets = [
            CommunicationAsset(
                id=f"COMM:ASSET:{cid}",
                asset_type=AssetType.MESH_ROUTER,
                candidate_id=cid,
                position=cand_by_id[cid].position,
                backhaul_parent_asset_id=(
                    None if parent[cid] is None else f"COMM:ASSET:{parent[cid]}"
                ),
                hop_count=hop[cid],
            )
            for cid in selected_ids
        ]

        # -- demand assignment (§20) ------------------------------------------ #
        sel_rows = [cand_index[cid] for cid in selected_ids]
        sel_dist = cand_demand[sel_rows]  # |selected| x |demands|
        coverage_rows: list[DemandCoverage] = []
        covered_count = 0
        serving_distances: list[float] = []
        for j, did in enumerate(demand_ids):
            col = sel_dist[:, j]
            best_i = -1
            best_d = math.inf
            for i in range(len(selected_ids)):  # id-ordered => deterministic ties
                d = float(col[i])
                if d < best_d - 1e-15:
                    best_d = d
                    best_i = i
            if best_i >= 0 and best_d <= cov_r:
                covered_count += 1
                serving_distances.append(best_d)
                coverage_rows.append(
                    DemandCoverage(
                        demand_id=did,
                        covered=True,
                        serving_asset_id=f"COMM:ASSET:{selected_ids[best_i]}",
                        network_distance_m=best_d,
                    )
                )
            else:
                coverage_rows.append(
                    DemandCoverage(
                        demand_id=did,
                        covered=False,
                        serving_asset_id=None,
                        network_distance_m=None,
                    )
                )

        coverage_fraction = covered_count / len(demand_ids) if demand_ids else 1.0
        backhaul_links = sum(1 for a in assets if a.backhaul_parent_asset_id is not None)
        metrics = CommunicationMetrics(
            candidate_count=len(candidates),
            demand_count=len(demands),
            selected_asset_count=len(assets),
            covered_demand_count=covered_count,
            uncovered_demand_count=len(demand_ids) - covered_count,
            coverage_fraction=coverage_fraction,
            mean_serving_distance_m=(
                float(np.mean(serving_distances)) if serving_distances else None
            ),
            max_serving_distance_m=(
                float(np.max(serving_distances)) if serving_distances else None
            ),
            backhaul_link_count=backhaul_links,
            max_backhaul_hop_count=max(hop.values()) if hop else 0,
            total_network_length3d=float(math.fsum(float(e["length3d"]) for e in edge_list)),
        )
        payload = CommunicationPayload(
            status="SUCCESS",
            failure_reason=None,
            source_revision=source_revision,
            model=CommunicationModelSummary(
                asset_type=AssetType.MESH_ROUTER,
                coverage_model=COVERAGE_MODEL_ID,
                solver=SOLVER_ID,
                optimality_claim=False,
                coverage_range_m=float(cfg.coverage_range_m),
                backhaul_range_m=float(cfg.backhaul_range_m),
                required_coverage_fraction=float(cfg.required_coverage_fraction),
            ),
            candidates=candidates,
            demands=demands,
            selected_assets=assets,
            demand_coverage=coverage_rows,
            metrics=metrics,
        )
        gate_failure = _success_gates(payload, problem, cov_r)
        if gate_failure is not None:
            return _failed(source_revision, gate_failure)
        return payload


def _success_gates(
    payload: CommunicationPayload, problem: PlacementProblem, cov_r: float
) -> str | None:
    """§22 hard gates: any violation is a typed failure, never a silent pass."""
    cand_ids = [c.id for c in payload.candidates]
    demand_ids = [d.id for d in payload.demands]
    asset_ids = [a.id for a in payload.selected_assets]
    if len(set(cand_ids)) != len(cand_ids):
        return "candidate ids are not unique"
    if len(set(demand_ids)) != len(demand_ids):
        return "demand ids are not unique"
    if len(set(asset_ids)) != len(asset_ids):
        return "selected asset ids are not unique"
    cand_set = set(cand_ids)
    selected_candidates = [a.candidate_id for a in payload.selected_assets]
    if len(set(selected_candidates)) != len(selected_candidates):
        return "a candidate is selected more than once"
    for a in payload.selected_assets:
        if a.candidate_id not in cand_set:
            return f"asset {a.id} references unknown candidate {a.candidate_id}"
    roots = [a for a in payload.selected_assets if a.backhaul_parent_asset_id is None]
    if len(roots) != 1 or roots[0].hop_count != 0:
        return f"expected exactly one hop-0 PORTAL root, got {len(roots)}"
    if roots[0].candidate_id not in problem.mandatory_candidate_ids:
        return "root asset is not the mandatory PORTAL candidate"
    asset_by_id = {a.id: a for a in payload.selected_assets}
    bh = problem.candidate_backhaul_graph
    for a in payload.selected_assets:
        if a.backhaul_parent_asset_id is None:
            continue
        p = asset_by_id.get(a.backhaul_parent_asset_id)
        if p is None:
            return f"asset {a.id} has a dangling backhaul parent"
        if p.candidate_id not in bh.get(a.candidate_id, []):
            return f"asset {a.id} parent is not backhaul-reachable"
        if a.hop_count != p.hop_count + 1:
            return f"asset {a.id} hop count is inconsistent with its parent"
    selected_asset_set = set(asset_ids)
    covered = 0
    for row in payload.demand_coverage:
        if row.covered:
            covered += 1
            if row.serving_asset_id not in selected_asset_set:
                return f"demand {row.demand_id} is served by an unselected router"
            if row.network_distance_m is None or row.network_distance_m > cov_r:
                return f"demand {row.demand_id} serving distance exceeds coverage range"
        elif row.serving_asset_id is not None:
            return f"uncovered demand {row.demand_id} has a serving asset"
    m = payload.metrics
    if m is None:
        return "metrics missing on SUCCESS payload"
    fraction = covered / len(demand_ids) if demand_ids else 1.0
    if fraction < problem.required_coverage_fraction - 1e-12:
        return (
            f"achieved coverage {fraction:.6f} is below the configured target "
            f"{problem.required_coverage_fraction:.6f}"
        )
    if (
        m.candidate_count != len(cand_ids)
        or m.demand_count != len(demand_ids)
        or m.selected_asset_count != len(asset_ids)
        or m.covered_demand_count != covered
        or m.uncovered_demand_count != len(demand_ids) - covered
        or len(payload.demand_coverage) != len(demand_ids)
        or m.backhaul_link_count != len(asset_ids) - 1
    ):
        return "metrics do not exactly agree with the serialized arrays"
    for a in payload.selected_assets:
        if not all(math.isfinite(v) for v in a.position):
            return f"asset {a.id} has a non-finite position"
    return None
