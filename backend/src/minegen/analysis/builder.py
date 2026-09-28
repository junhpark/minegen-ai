"""The pure projection: validated sources → ``MineAnalysisPayload``
(Phase 22A/B). No file system, no generation, no persistence; the service
takes the snapshot, this module derives the numbers. Deterministic: fixed
enum ordering, chronological buckets, no timestamps."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from minegen.analysis.cashflow import BucketLedger, bucket_count, build_buckets
from minegen.analysis.economics import (
    CostBreakdown,
    EconomicsConfig,
    development_rate,
    production_rate,
)
from minegen.analysis.integrity import (
    DECLARED_LENGTH_TOLERANCE_M,
    AnalysisSourceInconsistentError,
    ProductionUnit,
    network_cross_check,
    production_units,
    verify_network,
    verify_production,
    verify_timeline,
)
from minegen.analysis.models import (
    AnalysisSources,
    CashflowBucket,
    CutFillProductionDetail,
    DevelopmentCategory,
    DevelopmentCrossCheck,
    DevelopmentSection,
    DevelopmentTotals,
    EconomicsSection,
    EconomicsSummary,
    LongholeProductionDetail,
    MineAnalysisPayload,
    PlanningRatios,
    ProductionDetail,
    ProductionSection,
    RoomPillarProductionDetail,
    ScheduleSection,
)
from minegen.core.enums import EdgeType, TaskType
from minegen.core.models import Scenario
from minegen.mining.models import (
    CutFillPayload,
    ProductionPayload,
    RoomPillarMetrics,
    RoomPillarPayload,
    StopesMetrics,
)
from minegen.network.models import NetworkPayload
from minegen.scheduling.models import TimelinePayload, TimelineTask

__all__ = ["AnalysisInputs", "SourceRead", "build_analysis"]


@dataclass(frozen=True)
class SourceRead:
    """One VALID artifact as the service hands it over: typed model, the raw
    document (the method-integrity helpers read camelCase dicts) and the
    file revision."""

    model: Any
    raw: dict[str, Any]
    revision: str


@dataclass(frozen=True)
class AnalysisInputs:
    scenario: Scenario
    scenario_revision: str
    #: ``None`` when the world is not generated — every derived artifact is
    #: then untrusted and NOT_AVAILABLE (a derived file is never read
    #: without a VALID world, AC-01F)
    world_generated: bool
    network: SourceRead | None
    production: SourceRead | None
    timeline: SourceRead | None
    economics: EconomicsConfig | None
    economics_revision: str | None


_NO_WORLD = "world not generated (POST …/world/generate first)"


def _absent(name: str) -> str:
    return f"{name} not generated"


def _failed(name: str, reason: str | None) -> str:
    return f"{name} is FAILED: {reason or 'no failure reason recorded'}"


# --------------------------------------------------------------------------- #
# Development
# --------------------------------------------------------------------------- #


def _development(inputs: AnalysisInputs) -> tuple[DevelopmentSection, NetworkPayload | None]:
    empty = DevelopmentSection(
        availability="NOT_AVAILABLE", reason=None, categories=[], totals=None, cross_check=None
    )
    if not inputs.world_generated:
        return empty.model_copy(update={"reason": _NO_WORLD}), None
    if inputs.network is None:
        return empty.model_copy(update={"reason": _absent("network.json")}), None
    network: NetworkPayload = inputs.network.model
    if network.status != "SUCCESS":
        return empty.model_copy(
            update={"reason": _failed("network.json", network.failure_reason)}
        ), None
    verify_network(network)
    categories: list[DevelopmentCategory] = []
    by_type: dict[EdgeType, tuple[int, float, float]] = {}
    for edge_type in EdgeType:
        edges = [e for e in network.edges if e.type is edge_type]
        length = math.fsum(e.length3d for e in edges)
        volume = math.fsum(e.length3d * e.cross_section.analytic_area for e in edges)
        by_type[edge_type] = (len(edges), length, volume)
        categories.append(
            DevelopmentCategory(
                edge_type=edge_type,
                edge_count=len(edges),
                total_length_m=length,
                gross_excavation_volume_m3=volume,
            )
        )
    totals = DevelopmentTotals(
        total_development_length_m=math.fsum(v[1] for v in by_type.values()),
        gross_development_volume_m3=math.fsum(v[2] for v in by_type.values()),
        ramp_length_m=by_type[EdgeType.RAMP][1],
        level_access_length_m=by_type[EdgeType.LEVEL_ACCESS][1],
        drift_length_m=by_type[EdgeType.DRIFT][1],
        crosscut_length_m=by_type[EdgeType.CROSSCUT][1],
        shaft_length_m=by_type[EdgeType.SHAFT][1],
        shaft_station_access_length_m=by_type[EdgeType.SHAFT_STATION_ACCESS][1],
    )
    max_len, max_count = network_cross_check(network)
    section = DevelopmentSection(
        availability="AVAILABLE",
        reason=None,
        categories=categories,
        totals=totals,
        cross_check=DevelopmentCrossCheck(
            tolerance_m=DECLARED_LENGTH_TOLERANCE_M,
            max_length_difference_m=max_len,
            max_count_difference=max_count,
        ),
    )
    return section, network


# --------------------------------------------------------------------------- #
# Production
# --------------------------------------------------------------------------- #


def _weighted_grade(units: list[ProductionUnit]) -> float | None:
    weighted = [(u.tonnes, u.grade_proxy) for u in units if u.grade_proxy is not None]
    mass = math.fsum(t for t, _ in weighted)
    if mass <= 0.0:
        return None
    return math.fsum(t * g for t, g in weighted) / mass


def _production_detail(payload: ProductionPayload) -> ProductionDetail:
    metrics = payload.metrics
    if metrics is None:
        raise AnalysisSourceInconsistentError("stopes.json is SUCCESS but carries no metrics")
    if isinstance(payload, CutFillPayload):
        return CutFillProductionDetail(
            cut_count=len(payload.cuts),
            lift_count=len(payload.lifts),
            backfill_count=len(payload.backfills),
            total_backfill_volume_m3=math.fsum(b.volume_m3 for b in payload.backfills),
        )
    if isinstance(payload, RoomPillarPayload):
        assert isinstance(metrics, RoomPillarMetrics)
        return RoomPillarProductionDetail(
            room_count=len(payload.rooms),
            extraction_unit_count=len(payload.extraction_units),
            pillar_count=len(payload.pillars),
            heading_count=sum(1 for u in payload.extraction_units if u.bench_index == 0),
            bench_count=sum(1 for u in payload.extraction_units if u.bench_index > 0),
            retained_pillar_volume_m3=math.fsum(p.geometric_volume_m3 for p in payload.pillars),
            retained_pillar_tonnes_equivalent=math.fsum(
                p.tonnes_equivalent for p in payload.pillars
            ),
            geometric_extraction_fraction=metrics.geometric_extraction_fraction,
        )
    assert isinstance(metrics, StopesMetrics)
    return LongholeProductionDetail(
        stope_count=len(payload.stopes),
        level_interval_count=metrics.level_interval_count,
    )


def _production(
    inputs: AnalysisInputs,
) -> tuple[ProductionSection, ProductionPayload | None, list[ProductionUnit]]:
    empty = ProductionSection(
        availability="NOT_AVAILABLE",
        reason=None,
        method=None,
        production_object_count=None,
        total_production_volume_m3=None,
        total_planned_mined_tonnes=None,
        weighted_mean_grade_proxy=None,
        detail=None,
    )
    if not inputs.world_generated:
        return empty.model_copy(update={"reason": _NO_WORLD}), None, []
    if inputs.production is None:
        return empty.model_copy(update={"reason": _absent("stopes.json")}), None, []
    payload: ProductionPayload = inputs.production.model
    if payload.status != "SUCCESS":
        return (
            empty.model_copy(
                update={
                    "reason": _failed("stopes.json", payload.failure_reason),
                    "method": inputs.scenario.mining.method,
                }
            ),
            None,
            [],
        )
    method = inputs.scenario.mining.method
    verify_production(method, payload, inputs.production.raw)
    units = production_units(payload)
    section = ProductionSection(
        availability="AVAILABLE",
        reason=None,
        method=method,
        production_object_count=len(units),
        total_production_volume_m3=math.fsum(u.volume_m3 for u in units),
        total_planned_mined_tonnes=math.fsum(u.tonnes for u in units),
        weighted_mean_grade_proxy=_weighted_grade(units),
        detail=_production_detail(payload),
    )
    return section, payload, units


# --------------------------------------------------------------------------- #
# Schedule
# --------------------------------------------------------------------------- #


def _schedule(
    inputs: AnalysisInputs,
    network: NetworkPayload | None,
    payload: ProductionPayload | None,
) -> tuple[ScheduleSection, TimelinePayload | None, dict[str, dict[TaskType, TimelineTask]]]:
    empty = ScheduleSection(
        availability="NOT_AVAILABLE",
        reason=None,
        task_count=None,
        development_task_count=None,
        production_task_count=None,
        start_day=None,
        end_day=None,
        mine_duration_days=None,
        ramp_completion_day=None,
        first_production_day=None,
    )
    if not inputs.world_generated:
        return empty.model_copy(update={"reason": _NO_WORLD}), None, {}
    if inputs.timeline is None:
        return empty.model_copy(update={"reason": _absent("timeline.json")}), None, {}
    timeline: TimelinePayload = inputs.timeline.model
    if timeline.status != "SUCCESS":
        return (
            empty.model_copy(update={"reason": _failed("timeline.json", timeline.failure_reason)}),
            None,
            {},
        )
    # a SUCCESS timeline claims the network and the production artifact it
    # was scheduled from: without a consumable owner it cannot be verified
    if network is None:
        raise AnalysisSourceInconsistentError(
            "timeline.json is SUCCESS but network.json is absent or not SUCCESS"
        )
    if payload is None:
        raise AnalysisSourceInconsistentError(
            "timeline.json is SUCCESS but stopes.json is absent or not SUCCESS"
        )
    per_unit = verify_timeline(inputs.scenario.mining.method, timeline, network, payload)
    tasks = timeline.tasks
    dev_tasks = [t for t in tasks if t.target_kind == "DEVELOPMENT"]
    stoping_starts = [t.start_day for t in tasks if t.task_type is TaskType.STOPING]
    metrics = timeline.metrics
    assert metrics is not None  # verify_timeline
    section = ScheduleSection(
        availability="AVAILABLE",
        reason=None,
        task_count=len(tasks),
        development_task_count=len(dev_tasks),
        production_task_count=len(tasks) - len(dev_tasks),
        start_day=timeline.start_day,
        end_day=timeline.end_day,
        mine_duration_days=timeline.end_day - timeline.start_day,
        ramp_completion_day=metrics.ramp_completion_day,
        first_production_day=min(stoping_starts) if stoping_starts else None,
    )
    return section, timeline, per_unit


# --------------------------------------------------------------------------- #
# Ratios
# --------------------------------------------------------------------------- #


def _ratios(development: DevelopmentSection, production: ProductionSection) -> PlanningRatios:
    if development.availability != "AVAILABLE" or production.availability != "AVAILABLE":
        missing = [
            name
            for name, section in (("development", development), ("production", production))
            if section.availability != "AVAILABLE"
        ]
        return PlanningRatios(
            availability="NOT_AVAILABLE",
            reason=f"requires {' and '.join(missing)}",
            development_metres_per_kt=None,
            gross_development_m3_per_kt=None,
        )
    assert development.totals is not None
    tonnes = production.total_planned_mined_tonnes or 0.0
    if tonnes <= 0.0:
        return PlanningRatios(
            availability="AVAILABLE",
            reason="planned mined tonnes are zero; ratios undefined",
            development_metres_per_kt=None,
            gross_development_m3_per_kt=None,
        )
    kt = tonnes / 1000.0
    return PlanningRatios(
        availability="AVAILABLE",
        reason=None,
        development_metres_per_kt=development.totals.total_development_length_m / kt,
        gross_development_m3_per_kt=development.totals.gross_development_volume_m3 / kt,
    )


# --------------------------------------------------------------------------- #
# Economics
# --------------------------------------------------------------------------- #


def _economics(
    inputs: AnalysisInputs,
    development: DevelopmentSection,
    production: ProductionSection,
    schedule: ScheduleSection,
    network: NetworkPayload | None,
    payload: ProductionPayload | None,
    units: list[ProductionUnit],
    timeline: TimelinePayload | None,
    per_unit: dict[str, dict[TaskType, TimelineTask]],
) -> EconomicsSection:
    config = inputs.economics
    empty = EconomicsSection(
        availability="NOT_CONFIGURED",
        reason="Planning economics is not configured.",
        economics_revision=inputs.economics_revision,
        currency_code=None,
        cashflow_bucket_days=None,
        annual_discount_rate=None,
        summary=None,
        cashflow=[],
    )
    if config is None:
        return empty
    configured = empty.model_copy(
        update={
            "currency_code": config.currency_code,
            "cashflow_bucket_days": config.cashflow_bucket_days,
            "annual_discount_rate": config.annual_discount_rate,
        }
    )
    missing = [
        name
        for name, section in (
            ("development", development),
            ("production", production),
            ("schedule", schedule),
        )
        if section.availability != "AVAILABLE"
    ]
    if missing:
        return configured.model_copy(
            update={
                "availability": "NOT_AVAILABLE",
                "reason": f"SOURCE_NOT_AVAILABLE: requires {', '.join(missing)}",
            }
        )
    assert network is not None and payload is not None and timeline is not None
    method = inputs.scenario.mining.method
    mining_rate = production_rate(config, method)
    if mining_rate is None:
        return configured.model_copy(
            update={
                "availability": "NOT_AVAILABLE",
                "reason": f"SOURCE_NOT_AVAILABLE: no production cost rate for {method.value}",
            }
        )
    dev_task_by_edge = {t.target_id: t for t in timeline.tasks if t.target_kind == "DEVELOPMENT"}
    ledger = BucketLedger(
        config.cashflow_bucket_days, bucket_count(timeline.end_day, config.cashflow_bucket_days)
    )

    # development: length × rate(edge type), linear over the development task
    dev_costs: list[float] = []
    for edge in network.edges:
        rate = development_rate(config, edge.type)
        if rate is None:
            raise AnalysisSourceInconsistentError(
                f"network edge {edge.id} has type {edge.type.value} with no development cost rate"
            )
        task = dev_task_by_edge[edge.id]  # verified by verify_timeline
        cost = edge.length3d * rate
        dev_costs.append(cost)
        ledger.add("development_cost", task.start_day, task.end_day, cost)

    # production: tonnes × rates over STOPING / MUCKING; backfill (Cut & Fill
    # only) over BACKFILL
    mining_costs: list[float] = []
    processing_costs: list[float] = []
    revenues: list[float] = []
    backfill_costs: list[float] = []
    backfill_volume_by_cut: dict[str, float] = (
        {b.source_cut_id: b.volume_m3 for b in payload.backfills}
        if isinstance(payload, CutFillPayload)
        else {}
    )
    for unit in units:
        tasks = per_unit[unit.id]
        stoping = tasks[TaskType.STOPING]
        mucking = tasks[TaskType.MUCKING]
        mining_cost = unit.tonnes * mining_rate
        processing_cost = unit.tonnes * config.processing_cost_per_tonne
        revenue = unit.tonnes * config.gross_revenue_per_mined_tonne
        mining_costs.append(mining_cost)
        processing_costs.append(processing_cost)
        revenues.append(revenue)
        ledger.add("production_mining_cost", stoping.start_day, stoping.end_day, mining_cost)
        ledger.add("processing_cost", mucking.start_day, mucking.end_day, processing_cost)
        ledger.add("revenue", mucking.start_day, mucking.end_day, revenue)
        if isinstance(payload, CutFillPayload):
            backfill = tasks[TaskType.BACKFILL]
            volume = backfill_volume_by_cut.get(unit.id)
            if volume is None:
                raise AnalysisSourceInconsistentError(f"cut {unit.id} has no backfill record")
            cost = volume * config.backfill_cost_per_m3
            backfill_costs.append(cost)
            ledger.add("backfill_cost", backfill.start_day, backfill.end_day, cost)

    duration = timeline.end_day - timeline.start_day
    fixed = duration * config.fixed_operating_cost_per_day
    ledger.add("fixed_operating_cost", timeline.start_day, timeline.end_day, fixed)
    ledger.add("initial_capital_cost", 0.0, 0.0, config.initial_capital_cost)

    breakdown = CostBreakdown(
        development_cost=math.fsum(dev_costs),
        production_mining_cost=math.fsum(mining_costs),
        processing_cost=math.fsum(processing_costs),
        backfill_cost=math.fsum(backfill_costs),
        fixed_operating_cost=fixed,
        initial_capital_cost=config.initial_capital_cost,
        total_revenue=math.fsum(revenues),
    )
    buckets: list[CashflowBucket] = build_buckets(ledger, config.annual_discount_rate)
    summary = EconomicsSummary(
        development_cost=breakdown.development_cost,
        production_mining_cost=breakdown.production_mining_cost,
        processing_cost=breakdown.processing_cost,
        backfill_cost=breakdown.backfill_cost,
        fixed_operating_cost=breakdown.fixed_operating_cost,
        initial_capital_cost=breakdown.initial_capital_cost,
        total_cost=breakdown.total_cost,
        total_revenue=breakdown.total_revenue,
        undiscounted_net_cashflow=breakdown.undiscounted_net_cashflow,
        npv=math.fsum(b.discounted_net_cashflow for b in buckets),
    )
    return configured.model_copy(
        update={
            "availability": "AVAILABLE",
            "reason": None,
            "summary": summary,
            "cashflow": buckets,
        }
    )


# --------------------------------------------------------------------------- #
# Payload
# --------------------------------------------------------------------------- #


def build_analysis(inputs: AnalysisInputs) -> MineAnalysisPayload:
    development, network = _development(inputs)
    production, payload, units = _production(inputs)
    schedule, timeline, per_unit = _schedule(inputs, network, payload)
    ratios = _ratios(development, production)
    economics = _economics(
        inputs, development, production, schedule, network, payload, units, timeline, per_unit
    )
    return MineAnalysisPayload(
        sources=AnalysisSources(
            scenario_revision=inputs.scenario_revision,
            network_revision=inputs.network.revision if inputs.network else None,
            production_revision=inputs.production.revision if inputs.production else None,
            timeline_revision=inputs.timeline.revision if inputs.timeline else None,
            economics_revision=inputs.economics_revision,
        ),
        development=development,
        production=production,
        schedule=schedule,
        ratios=ratios,
        economics=economics,
    )
