"""Phase 12 — Generic Sensor OSP builder (rules 93–98).

Deterministic monitoring-placement baseline for ``GAS_SENSOR`` on the
validated MineNetwork. Core invariants: monitoring coverage is a
network-geodesic LAYOUT proxy (rule 95 — never Euclidean through rock,
never gas transport/response/probability), placement is deterministic
greedy set cover with no optimality claim (rule 96), and sensors are a
static sibling artifact — communication feasibility, power feasibility and
installation timing are not modeled (rule 97).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from minegen.core.enums import AssetType
from minegen.core.models import Scenario
from minegen.infrastructure.coverage import (
    NetworkDistanceMonitoringThresholdModel,
    SensorCoverageModel,
)
from minegen.infrastructure.models import (
    CoveragePlacementProblem,
    SensorAsset,
    SensorDemandCoverage,
    SensorMetrics,
    SensorModelSummary,
    SensorPayload,
)
from minegen.infrastructure.network_domain import (
    DomainValidationError,
    InfrastructureNetworkDomain,
    UnsupportedEdgeTypeError,
)
from minegen.infrastructure.solver import solve_greedy_set_cover, validate_coverage_relations


def _failed(source_revision: str, reason: str) -> SensorPayload:
    return SensorPayload(
        status="FAILED",
        failure_reason=reason,
        source_revision=source_revision,
        model=None,
        candidates=[],
        demands=[],
        selected_sensors=[],
        demand_coverage=[],
        metrics=None,
    )


class SensorBuilder:
    """Builds ``sensors.json`` from network + owning centerlines."""

    def __init__(
        self,
        scenario: Scenario,
        coverage_model: SensorCoverageModel | None = None,
    ) -> None:
        self.scenario = scenario
        self.config = scenario.infrastructure.sensors
        # replaceable strategy (rule 95): defaults to the v0.1 layout proxy
        self.coverage_model: SensorCoverageModel = (
            coverage_model
            if coverage_model is not None
            else NetworkDistanceMonitoringThresholdModel(float(self.config.monitoring_range_m))
        )

    def build(
        self,
        network_payload: dict[str, Any],
        smoothed_payload: dict[str, Any],
        levels_payload: dict[str, Any],
        source_revision: str,
    ) -> SensorPayload:
        cfg = self.config
        # -- supported asset gate (§2): never silently substitute ------------ #
        if cfg.asset_type is not AssetType.GAS_SENSOR:
            return _failed(
                source_revision,
                f"UNSUPPORTED_SENSOR_ASSET_TYPE: {cfg.asset_type.value} is reserved — "
                "Phase 12 v0.1 implements GAS_SENSOR only",
            )
        # -- shared infrastructure network domain (rule 93) ------------------- #
        try:
            domain = InfrastructureNetworkDomain.build(
                network_payload, smoothed_payload, levels_payload
            )
        except UnsupportedEdgeTypeError as exc:
            return _failed(
                source_revision,
                f"UNSUPPORTED_SENSOR_EDGE_TYPE: edge {exc.edge_id} has type "
                f"{exc.edge_type} — RAISE/SHAFT sensor planning is deferred until "
                "owning geometry exists",
            )
        except DomainValidationError as exc:
            return _failed(source_revision, str(exc))

        # -- deterministic sampling (§13–§14, rule 93) ------------------------ #
        cand_rows = domain.sample(float(cfg.candidate_spacing_m), "SENSOR:CAND")
        demand_rows = domain.sample(float(cfg.demand_spacing_m), "SENSOR:DEMAND")
        candidates = domain.candidates_from_rows(cand_rows)
        demands = domain.demands_from_rows(demand_rows)

        # -- network-geodesic distances (§10, rule 95) ------------------------ #
        cand_demand = domain.pairwise(cand_rows, demand_rows)

        # -- monitoring coverage model + problem (§9, §15) -------------------- #
        cand_ids = [r[0] for r in cand_rows]
        demand_ids = [r[0] for r in demand_rows]
        coverage_sets = self.coverage_model.coverage_sets(cand_ids, demand_ids, cand_demand)
        # pre-solver relation gate: a strategy emitting ghost/duplicate ids
        # becomes typed FAILED, never a solver KeyError (PR #9 blocker 3)
        relation_failure = validate_coverage_relations(coverage_sets, cand_ids, demand_ids)
        if relation_failure is not None:
            return _failed(source_revision, relation_failure)
        # deterministic relation ordering regardless of strategy output order
        coverage_sets = {cid: sorted(dids) for cid, dids in coverage_sets.items()}
        problem = CoveragePlacementProblem(
            candidates=candidates,
            demands=demands,
            candidate_coverage_sets=coverage_sets,
            required_coverage_fraction=float(cfg.required_coverage_fraction),
        )

        # -- deterministic greedy set-cover baseline (§15, rule 96) ----------- #
        solution = solve_greedy_set_cover(problem)
        if solution.status != "SUCCESS":
            return _failed(source_revision, solution.failure_reason or "sensor placement failed")
        selected_ids = sorted(solution.selected_candidate_ids)
        cand_index = {cid: i for i, cid in enumerate(cand_ids)}
        cand_by_id = {c.id: c for c in candidates}
        sensors = [
            SensorAsset(
                id=f"SENSOR:ASSET:{cid}",
                asset_type=AssetType.GAS_SENSOR,
                candidate_id=cid,
                position=cand_by_id[cid].position,
            )
            for cid in selected_ids
        ]

        # -- monitoring assignment (§18) -------------------------------------- #
        # eligibility is strategy-owned: a sensor can serve a demand iff the
        # coverage model says it covers it; no hidden raw distance threshold
        sel_rows = [cand_index[cid] for cid in selected_ids]
        sel_dist = cand_demand[sel_rows]  # |selected| x |demands|
        demand_index = {did: j for j, did in enumerate(demand_ids)}
        eligible: dict[int, list[int]] = {j: [] for j in range(len(demand_ids))}
        for i, cid in enumerate(selected_ids):  # id-ordered => deterministic
            for did in coverage_sets.get(cid, []):
                eligible[demand_index[did]].append(i)
        coverage_rows: list[SensorDemandCoverage] = []
        covered_count = 0
        serving_distances: list[float] = []
        for j, did in enumerate(demand_ids):
            col = sel_dist[:, j]
            best_i = -1
            best_d = math.inf
            for i in eligible[j]:  # id-ordered => tie by smallest sensor id
                d = float(col[i])
                if d < best_d - 1e-15:
                    best_d = d
                    best_i = i
            if best_i >= 0:
                covered_count += 1
                serving_distances.append(best_d)
                coverage_rows.append(
                    SensorDemandCoverage(
                        demand_id=did,
                        covered=True,
                        serving_sensor_id=f"SENSOR:ASSET:{selected_ids[best_i]}",
                        network_distance_m=best_d,
                    )
                )
            else:
                coverage_rows.append(
                    SensorDemandCoverage(
                        demand_id=did,
                        covered=False,
                        serving_sensor_id=None,
                        network_distance_m=None,
                    )
                )

        coverage_fraction = covered_count / len(demand_ids) if demand_ids else 1.0
        metrics = SensorMetrics(
            candidate_count=len(candidates),
            demand_count=len(demands),
            selected_sensor_count=len(sensors),
            covered_demand_count=covered_count,
            uncovered_demand_count=len(demand_ids) - covered_count,
            coverage_fraction=coverage_fraction,
            mean_monitoring_distance_m=(
                float(np.mean(serving_distances)) if serving_distances else None
            ),
            max_monitoring_distance_m=(
                float(np.max(serving_distances)) if serving_distances else None
            ),
            total_network_length3d=domain.total_network_length3d,
        )
        payload = SensorPayload(
            status="SUCCESS",
            failure_reason=None,
            source_revision=source_revision,
            model=SensorModelSummary(
                asset_type=AssetType.GAS_SENSOR,
                coverage_model=self.coverage_model.model_id,
                solver="GREEDY_SET_COVER_V0_1",
                optimality_claim=False,
                monitoring_range_m=float(cfg.monitoring_range_m),
                required_coverage_fraction=float(cfg.required_coverage_fraction),
            ),
            candidates=candidates,
            demands=demands,
            selected_sensors=sensors,
            demand_coverage=coverage_rows,
            metrics=metrics,
        )
        gate_failure = _success_gates(payload, problem)
        if gate_failure is not None:
            return _failed(source_revision, gate_failure)
        return payload


def _success_gates(payload: SensorPayload, problem: CoveragePlacementProblem) -> str | None:
    """§21 hard gates: any violation is a typed failure, never a silent pass."""
    cand_ids = [c.id for c in payload.candidates]
    demand_ids = [d.id for d in payload.demands]
    sensor_ids = [a.id for a in payload.selected_sensors]
    if len(set(cand_ids)) != len(cand_ids):
        return "candidate ids are not unique"
    if len(set(demand_ids)) != len(demand_ids):
        return "demand ids are not unique"
    if len(set(sensor_ids)) != len(sensor_ids):
        return "selected sensor ids are not unique"
    cand_set = set(cand_ids)
    demand_set = set(demand_ids)
    selected_candidates = [a.candidate_id for a in payload.selected_sensors]
    if len(set(selected_candidates)) != len(selected_candidates):
        return "a candidate is selected more than once"
    for a in payload.selected_sensors:
        if a.candidate_id not in cand_set:
            return f"sensor {a.id} references unknown candidate {a.candidate_id}"
        if a.asset_type is not AssetType.GAS_SENSOR:
            return f"sensor {a.id} is not a GAS_SENSOR"
        if not all(math.isfinite(v) for v in a.position):
            return f"sensor {a.id} has a non-finite position"
    for cid, dids in problem.candidate_coverage_sets.items():
        if cid not in cand_set:
            return f"coverage model references unknown candidate {cid}"
        for did in dids:
            if did not in demand_set:
                return f"coverage model references unknown demand {did}"
    sensor_by_id = {a.id: a for a in payload.selected_sensors}
    covered = 0
    for row in payload.demand_coverage:
        if row.covered:
            covered += 1
            serving = sensor_by_id.get(row.serving_sensor_id or "")
            if serving is None:
                return f"demand {row.demand_id} is served by an unselected sensor"
            if row.demand_id not in problem.candidate_coverage_sets.get(serving.candidate_id, []):
                return (
                    f"demand {row.demand_id} serving sensor is outside the coverage model relation"
                )
            if row.network_distance_m is None or not math.isfinite(row.network_distance_m):
                return f"demand {row.demand_id} serving distance is not finite"
        elif row.serving_sensor_id is not None:
            return f"uncovered demand {row.demand_id} has a serving sensor"
    coverage_row_ids = [row.demand_id for row in payload.demand_coverage]
    if len(set(coverage_row_ids)) != len(coverage_row_ids):
        return "demandCoverage repeats a demand id"
    if set(coverage_row_ids) != demand_set or len(coverage_row_ids) != len(demand_ids):
        return "demandCoverage demand ids do not exactly match the demand array"
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
        or m.selected_sensor_count != len(sensor_ids)
        or m.covered_demand_count != covered
        or m.uncovered_demand_count != len(demand_ids) - covered
        or len(payload.demand_coverage) != len(demand_ids)
    ):
        return "metrics do not exactly agree with the serialized arrays"
    # monitoring statistics must equal the assignment-derived values
    serving_values = [
        row.network_distance_m
        for row in payload.demand_coverage
        if row.covered and row.network_distance_m is not None
    ]
    if m.coverage_fraction != fraction:
        return "coverageFraction does not equal the assignment-derived fraction"
    if not serving_values:
        if m.mean_monitoring_distance_m is not None or m.max_monitoring_distance_m is not None:
            return "monitoring statistics must be null when no demand is covered"
    else:
        if m.mean_monitoring_distance_m != float(np.mean(serving_values)):
            return "meanMonitoringDistanceM does not equal the assignment-derived mean"
        if m.max_monitoring_distance_m != float(np.max(serving_values)):
            return "maxMonitoringDistanceM does not equal the assignment-derived max"
    return None
