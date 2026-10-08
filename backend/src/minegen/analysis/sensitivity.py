"""Sensitivity and schedule what-if (hardening PR-2 H3 §8.3) — READ-ONLY.

Every result is a WHAT-IF OVERRIDE, NOT A SCENARIO VALUE: nothing here is
persisted, no scenario field, ``economics.json`` or ``timeline.json`` is
touched, and no optimizer exists — the perturbations are an explicit finite
grid (±10 / 20 / 30 % by default) over nine declared parameters:

ECONOMIC (the Planning Cashflow is recomputed from the current authoritative
quantities and timing):
    gross revenue per mined tonne · development cost · mining cost ·
    processing cost · backfill cost · initial capital · discount rate

SCHEDULE (the existing ``MineTimelineBuilder`` is rerun IN MEMORY with the
scaled ``ScheduleConfig`` rates — the same builder, the same inputs, never a
temporary artifact):
    development rate (every development advance rate) ·
    mining rate (stoping and mucking tonnes per day)

Outputs per case: Planning NPV, Planning IRR (typed), mine duration and the
first production day, with plain deltas against the unperturbed base. The
revenue authority stays "Gross revenue per mined tonne" (rule 199): no
commodity price, grade, recovery, payability, royalty or tax exists.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Final, Literal

from pydantic import Field

from minegen.analysis.builder import (
    AnalysisInputs,
    _development,
    _production,
    _schedule,
    economics_ledger,
)
from minegen.analysis.cashflow import build_buckets
from minegen.analysis.economics import EconomicsConfig, production_rate
from minegen.analysis.integrity import AnalysisSourceInconsistentError, verify_timeline
from minegen.analysis.irr import planning_irr
from minegen.analysis.models import (
    ECONOMICS_DISCLAIMER,
    AnalysisSources,
    Availability,
    PlanningIrr,
    not_configured_irr,
)
from minegen.core.enums import TaskType
from minegen.core.models import ApiModel, ScheduleConfig
from minegen.scheduling.builder import MineTimelineBuilder
from minegen.scheduling.models import TimelinePayload, TimelineTask

__all__ = [
    "DEFAULT_PERTURBATIONS_PCT",
    "PARAMETERS",
    "WHAT_IF_LABEL",
    "SensitivityCase",
    "SensitivityInputs",
    "SensitivityPayload",
    "WhatIfFactors",
    "WhatIfOutcome",
    "build_sensitivity",
    "evaluate_what_if",
]

WHAT_IF_LABEL: Final[Literal["WHAT-IF OVERRIDE — NOT SCENARIO VALUE"]] = (
    "WHAT-IF OVERRIDE — NOT SCENARIO VALUE"
)
WHAT_IF_NOTICE = (
    "Overrides are evaluated in memory and never persisted: the scenario document, "
    "economics.json and timeline.json are unchanged."
)
DEFAULT_PERTURBATIONS_PCT: tuple[float, ...] = (-30.0, -20.0, -10.0, 10.0, 20.0, 30.0)

ParameterKind = Literal["ECONOMIC", "SCHEDULE"]

Factor = float


class WhatIfFactors(ApiModel):
    """Multiplicative overrides (1.0 = the scenario / economics value)."""

    gross_revenue_per_mined_tonne: Factor = Field(default=1.0, gt=0.0, le=10.0)
    development_cost: Factor = Field(default=1.0, gt=0.0, le=10.0)
    mining_cost: Factor = Field(default=1.0, gt=0.0, le=10.0)
    processing_cost: Factor = Field(default=1.0, gt=0.0, le=10.0)
    backfill_cost: Factor = Field(default=1.0, gt=0.0, le=10.0)
    initial_capital: Factor = Field(default=1.0, gt=0.0, le=10.0)
    discount_rate: Factor = Field(default=1.0, gt=0.0, le=10.0)
    development_rate: Factor = Field(default=1.0, gt=0.0, le=10.0)
    mining_rate: Factor = Field(default=1.0, gt=0.0, le=10.0)

    def is_base(self) -> bool:
        return all(getattr(self, k) == 1.0 for k, _, _ in PARAMETERS)

    def reschedules(self) -> bool:
        return self.development_rate != 1.0 or self.mining_rate != 1.0


#: (factor field, user-facing label, kind) — a fixed, declared order
PARAMETERS: tuple[tuple[str, str, ParameterKind], ...] = (
    ("gross_revenue_per_mined_tonne", "Gross revenue per mined tonne", "ECONOMIC"),
    ("development_cost", "Development cost", "ECONOMIC"),
    ("mining_cost", "Mining cost", "ECONOMIC"),
    ("processing_cost", "Processing cost", "ECONOMIC"),
    ("backfill_cost", "Backfill cost", "ECONOMIC"),
    ("initial_capital", "Initial capital", "ECONOMIC"),
    ("discount_rate", "Discount rate", "ECONOMIC"),
    ("development_rate", "Development rate", "SCHEDULE"),
    ("mining_rate", "Mining rate", "SCHEDULE"),
)


class ParameterSpec(ApiModel):
    key: str
    label: str
    kind: ParameterKind


class WhatIfOutcome(ApiModel):
    label: Literal["WHAT-IF OVERRIDE — NOT SCENARIO VALUE"] = WHAT_IF_LABEL
    status: Literal["AVAILABLE", "NOT_AVAILABLE", "FAILED"]
    reason: str | None
    factors: WhatIfFactors
    #: true when the MineTimelineBuilder was rerun in memory for this case
    schedule_rebuilt: bool
    planning_npv: float | None
    planning_irr: PlanningIrr
    mine_duration_days: float | None
    first_production_day: float | None
    end_day: float | None
    undiscounted_net_cashflow: float | None
    #: plain subtraction against the unperturbed base (null when either side is null)
    npv_delta: float | None = None
    mine_duration_delta_days: float | None = None
    first_production_delta_days: float | None = None


class SensitivityCase(ApiModel):
    parameter: str
    label: str
    kind: ParameterKind
    perturbation_pct: float
    factor: float
    outcome: WhatIfOutcome


class SensitivityPayload(ApiModel):
    status: Literal["SUCCESS"] = "SUCCESS"
    label: Literal["WHAT-IF OVERRIDE — NOT SCENARIO VALUE"] = WHAT_IF_LABEL
    notice: str = WHAT_IF_NOTICE
    sources: AnalysisSources
    availability: Availability
    reason: str | None
    revenue_model: Literal["GROSS_REVENUE_PER_MINED_TONNE"] = "GROSS_REVENUE_PER_MINED_TONNE"
    perturbations_pct: list[float]
    parameters: list[ParameterSpec]
    base: WhatIfOutcome
    cases: list[SensitivityCase]
    disclaimer: str = ECONOMICS_DISCLAIMER


@dataclass(frozen=True)
class SensitivityInputs:
    """The analysis inputs plus the owning-centerline documents the timeline
    builder needs for an in-memory reschedule (raw camelCase dicts, exactly
    what ``DesignService.generate_timeline`` passes)."""

    analysis: AnalysisInputs
    ramp_payload: dict[str, Any] | None
    levels_payload: dict[str, Any] | None
    accesses_payload: dict[str, Any] | None
    shafts_payload: dict[str, Any] | None


def scaled_economics(config: EconomicsConfig, f: WhatIfFactors) -> EconomicsConfig:
    dev = config.development_costs
    prod = config.production_costs
    return config.model_copy(
        update={
            "development_costs": dev.model_copy(
                update={k: getattr(dev, k) * f.development_cost for k in dev.__class__.model_fields}
            ),
            "production_costs": prod.model_copy(
                update={k: getattr(prod, k) * f.mining_cost for k in prod.__class__.model_fields}
            ),
            "processing_cost_per_tonne": config.processing_cost_per_tonne * f.processing_cost,
            "backfill_cost_per_m3": config.backfill_cost_per_m3 * f.backfill_cost,
            "initial_capital_cost": config.initial_capital_cost * f.initial_capital,
            "gross_revenue_per_mined_tonne": config.gross_revenue_per_mined_tonne
            * f.gross_revenue_per_mined_tonne,
            "annual_discount_rate": config.annual_discount_rate * f.discount_rate,
        }
    )


def scaled_schedule(schedule: ScheduleConfig, f: WhatIfFactors) -> ScheduleConfig:
    """Development rate scales EVERY development advance rate; mining rate
    scales the stoping and mucking tonnes per day. Fixed durations (stope
    preparation, backfill cure) and the backfill placement rate are untouched."""
    return schedule.model_copy(
        update={
            "ramp_advance_m_per_day": schedule.ramp_advance_m_per_day * f.development_rate,
            "level_access_advance_m_per_day": schedule.level_access_advance_m_per_day
            * f.development_rate,
            "drift_advance_m_per_day": schedule.drift_advance_m_per_day * f.development_rate,
            "crosscut_advance_m_per_day": schedule.crosscut_advance_m_per_day * f.development_rate,
            "shaft_sink_m_per_day": schedule.shaft_sink_m_per_day * f.development_rate,
            "shaft_station_access_advance_m_per_day": (
                schedule.shaft_station_access_advance_m_per_day * f.development_rate
            ),
            "stoping_tonnes_per_day": schedule.stoping_tonnes_per_day * f.mining_rate,
            "mucking_tonnes_per_day": schedule.mucking_tonnes_per_day * f.mining_rate,
        }
    )


def _unavailable(factors: WhatIfFactors, reason: str, rebuilt: bool = False) -> WhatIfOutcome:
    return WhatIfOutcome(
        status="NOT_AVAILABLE",
        reason=reason,
        factors=factors,
        schedule_rebuilt=rebuilt,
        planning_npv=None,
        planning_irr=not_configured_irr(),
        mine_duration_days=None,
        first_production_day=None,
        end_day=None,
        undiscounted_net_cashflow=None,
    )


def evaluate_what_if(inputs: SensitivityInputs, factors: WhatIfFactors) -> WhatIfOutcome:
    a = inputs.analysis
    development, network = _development(a)
    production, payload, units = _production(a)
    schedule, timeline, per_unit = _schedule(a, network, payload)
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
        return _unavailable(factors, f"SOURCE_NOT_AVAILABLE: requires {', '.join(missing)}")
    assert network is not None and payload is not None and timeline is not None
    rebuilt = False
    if factors.reschedules():
        if (
            a.network is None
            or a.production is None
            or inputs.ramp_payload is None
            or inputs.levels_payload is None
        ):
            return _unavailable(
                factors,
                "SOURCE_NOT_AVAILABLE: the in-memory reschedule needs the network, production, "
                "effective ramp and level artifacts",
            )
        scenario = a.scenario.model_copy(
            update={"schedule": scaled_schedule(a.scenario.schedule, factors)}
        )
        what_if: TimelinePayload = MineTimelineBuilder(scenario).build(
            a.network.raw,
            a.production.raw,
            inputs.ramp_payload,
            inputs.levels_payload,
            "what-if",
            accesses_payload=inputs.accesses_payload,
            shafts_payload=inputs.shafts_payload,
        )
        if what_if.status != "SUCCESS":
            return WhatIfOutcome(
                status="FAILED",
                reason=f"in-memory reschedule FAILED: {what_if.failure_reason}",
                factors=factors,
                schedule_rebuilt=True,
                planning_npv=None,
                planning_irr=not_configured_irr(),
                mine_duration_days=None,
                first_production_day=None,
                end_day=None,
                undiscounted_net_cashflow=None,
            )
        try:
            per_unit = verify_timeline(a.scenario.mining.method, what_if, network, payload)
        except AnalysisSourceInconsistentError as exc:  # pragma: no cover - builder contract
            return WhatIfOutcome(
                status="FAILED",
                reason=f"in-memory reschedule is not consistent: {exc}",
                factors=factors,
                schedule_rebuilt=True,
                planning_npv=None,
                planning_irr=not_configured_irr(),
                mine_duration_days=None,
                first_production_day=None,
                end_day=None,
                undiscounted_net_cashflow=None,
            )
        timeline = what_if
        rebuilt = True
    tasks: list[TimelineTask] = timeline.tasks
    stoping_starts = [t.start_day for t in tasks if t.task_type is TaskType.STOPING]
    duration = timeline.end_day - timeline.start_day
    first_production = min(stoping_starts) if stoping_starts else None
    config = a.economics
    npv: float | None = None
    net: float | None = None
    irr = not_configured_irr()
    if config is not None and production_rate(config, a.scenario.mining.method) is not None:
        scaled = scaled_economics(config, factors)
        ledger, breakdown = economics_ledger(
            scaled, network, payload, units, timeline, per_unit, scaled.cashflow_bucket_days
        )
        buckets = build_buckets(ledger, scaled.annual_discount_rate)
        npv = math.fsum(b.discounted_net_cashflow for b in buckets)
        net = breakdown.undiscounted_net_cashflow
        irr = planning_irr(buckets)
    return WhatIfOutcome(
        status="AVAILABLE",
        reason=None if config is not None else "Planning economics is not configured.",
        factors=factors,
        schedule_rebuilt=rebuilt,
        planning_npv=npv,
        planning_irr=irr,
        mine_duration_days=duration,
        first_production_day=first_production,
        end_day=timeline.end_day,
        undiscounted_net_cashflow=net,
    )


def _with_deltas(outcome: WhatIfOutcome, base: WhatIfOutcome) -> WhatIfOutcome:
    def delta(x: float | None, y: float | None) -> float | None:
        return None if x is None or y is None else x - y

    return outcome.model_copy(
        update={
            "npv_delta": delta(outcome.planning_npv, base.planning_npv),
            "mine_duration_delta_days": delta(outcome.mine_duration_days, base.mine_duration_days),
            "first_production_delta_days": delta(
                outcome.first_production_day, base.first_production_day
            ),
        }
    )


def build_sensitivity(
    inputs: SensitivityInputs, perturbations_pct: tuple[float, ...] = DEFAULT_PERTURBATIONS_PCT
) -> SensitivityPayload:
    for p in perturbations_pct:
        if not (-99.0 <= p <= 900.0) or p == 0.0:
            raise ValueError("perturbations must be non-zero percentages in [-99, 900]")
    a = inputs.analysis
    sources = AnalysisSources(
        scenario_revision=a.scenario_revision,
        network_revision=a.network.revision if a.network else None,
        production_revision=a.production.revision if a.production else None,
        timeline_revision=a.timeline.revision if a.timeline else None,
        economics_revision=a.economics_revision,
    )
    base = evaluate_what_if(inputs, WhatIfFactors())
    parameters = [ParameterSpec(key=k, label=lbl, kind=kind) for k, lbl, kind in PARAMETERS]
    if base.status != "AVAILABLE":
        return SensitivityPayload(
            sources=sources,
            availability="NOT_AVAILABLE",
            reason=base.reason,
            perturbations_pct=list(perturbations_pct),
            parameters=parameters,
            base=base,
            cases=[],
        )
    cases: list[SensitivityCase] = []
    for key, label, kind in PARAMETERS:
        for pct in perturbations_pct:
            factor = 1.0 + pct / 100.0
            factors = WhatIfFactors(**{key: factor})
            outcome = _with_deltas(evaluate_what_if(inputs, factors), base)
            cases.append(
                SensitivityCase(
                    parameter=key,
                    label=label,
                    kind=kind,
                    perturbation_pct=pct,
                    factor=factor,
                    outcome=outcome,
                )
            )
    availability: Availability = "AVAILABLE" if a.economics is not None else "NOT_CONFIGURED"
    return SensitivityPayload(
        sources=sources,
        availability=availability,
        reason=None
        if a.economics is not None
        else "Planning economics is not configured; schedule outputs only.",
        perturbations_pct=list(perturbations_pct),
        parameters=parameters,
        base=base,
        cases=cases,
    )
