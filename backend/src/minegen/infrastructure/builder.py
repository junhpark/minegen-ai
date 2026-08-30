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
from minegen.infrastructure.coverage import (
    CommunicationCoverageModel,
    NetworkDistanceThresholdModel,
)
from minegen.infrastructure.models import (
    SOLVER_ID,
    CommunicationAsset,
    CommunicationMetrics,
    CommunicationModelSummary,
    CommunicationPayload,
    DemandCoverage,
    PlacementProblem,
)
from minegen.infrastructure.network_domain import (
    DomainValidationError,
    InfrastructureNetworkDomain,
    UnsupportedEdgeTypeError,
)
from minegen.infrastructure.solver import solve_connected_greedy, validate_coverage_relations


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


class CommunicationBuilder:
    """Builds ``communication.json`` from network + owning centerlines."""

    def __init__(
        self,
        scenario: Scenario,
        coverage_model: CommunicationCoverageModel | None = None,
    ) -> None:
        self.scenario = scenario
        self.config = scenario.infrastructure.communication
        # replaceable strategy (rule 88): defaults to the v0.1 planning proxy
        self.coverage_model: CommunicationCoverageModel = (
            coverage_model
            if coverage_model is not None
            else NetworkDistanceThresholdModel(
                float(self.config.coverage_range_m), float(self.config.backhaul_range_m)
            )
        )

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
        # -- shared infrastructure network domain (rule 93) ------------------- #
        # integrity gates, owning-geometry resolution, deterministic sampling
        # and network-geodesic distance machinery are shared with Phase 12;
        # the builder never reimplements them
        try:
            domain = InfrastructureNetworkDomain.build(
                network_payload, smoothed_payload, levels_payload
            )
        except UnsupportedEdgeTypeError as exc:
            return _failed(
                source_revision,
                f"UNSUPPORTED_COMMUNICATION_EDGE_TYPE: edge {exc.edge_id} has type "
                f"{exc.edge_type} — RAISE/SHAFT communication planning is deferred "
                "until owning geometry exists",
            )
        except DomainValidationError as exc:
            return _failed(source_revision, str(exc))

        # -- deterministic sampling (§10–§11, rule 89) ------------------------ #
        cand_rows = domain.sample(float(cfg.candidate_spacing_m), "COMM:CAND")
        demand_rows = domain.sample(float(cfg.demand_spacing_m), "COMM:DEMAND")
        candidates = domain.candidates_from_rows(cand_rows)
        demands = domain.demands_from_rows(demand_rows)

        # -- network-geodesic distances (§12–§13, rule 88) -------------------- #
        cand_demand = domain.pairwise(cand_rows, demand_rows)
        cand_cand = domain.pairwise(cand_rows, cand_rows)

        # -- coverage model + placement problem (§14–§17) --------------------- #
        # delegation, not reimplementation (rule 88): the strategy owns the
        # conversion from geodesic distances to coverage/backhaul relations
        cand_ids = [r[0] for r in cand_rows]
        demand_ids = [r[0] for r in demand_rows]
        coverage_sets = self.coverage_model.coverage_sets(cand_ids, demand_ids, cand_demand)
        backhaul_graph = self.coverage_model.backhaul_graph(cand_ids, cand_cand)
        relation_failure = validate_coverage_relations(coverage_sets, cand_ids, demand_ids)
        if relation_failure is not None:
            return _failed(source_revision, relation_failure)
        portal_candidate = f"COMM:CAND:NODE:{domain.portal_id}"
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
        # eligibility is strategy-owned (blocker 1): a router can serve a
        # demand iff the coverage model says it covers it. For
        # NETWORK_DISTANCE_THRESHOLD_V0_1 this is exactly
        # geodesic <= coverageRangeM + 1e-6, so behaviour is unchanged.
        demand_index = {did: j for j, did in enumerate(demand_ids)}
        eligible: dict[int, list[int]] = {j: [] for j in range(len(demand_ids))}
        for i, cid in enumerate(selected_ids):  # id-ordered => deterministic
            for did in coverage_sets.get(cid, []):
                eligible[demand_index[did]].append(i)
        coverage_rows: list[DemandCoverage] = []
        covered_count = 0
        serving_distances: list[float] = []
        for j, did in enumerate(demand_ids):
            col = sel_dist[:, j]
            best_i = -1
            best_d = math.inf
            for i in eligible[j]:  # id-ordered => deterministic ties
                d = float(col[i])
                if d < best_d - 1e-15:
                    best_d = d
                    best_i = i
            if best_i >= 0:
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
            total_network_length3d=domain.total_network_length3d,
        )
        payload = CommunicationPayload(
            status="SUCCESS",
            failure_reason=None,
            source_revision=source_revision,
            model=CommunicationModelSummary(
                asset_type=AssetType.MESH_ROUTER,
                coverage_model=self.coverage_model.model_id,
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
        gate_failure = _success_gates(payload, problem)
        if gate_failure is not None:
            return _failed(source_revision, gate_failure)
        return payload


def _success_gates(payload: CommunicationPayload, problem: PlacementProblem) -> str | None:
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
            serving = asset_by_id[row.serving_asset_id]
            # strategy-owned serving gate: the model must say the serving
            # router covers this demand (for the v0.1 threshold model this is
            # exactly geodesic <= coverageRangeM + 1e-6)
            if row.demand_id not in problem.candidate_coverage_sets.get(serving.candidate_id, []):
                return (
                    f"demand {row.demand_id} serving router is outside the coverage model relation"
                )
            if row.network_distance_m is None or not math.isfinite(row.network_distance_m):
                return f"demand {row.demand_id} serving distance is not finite"
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
