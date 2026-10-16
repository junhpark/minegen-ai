"""Typed DTOs of the mine analysis read model (Phase 22A/B).

Every section carries its own AVAILABILITY:

    AVAILABLE       the section was computed from VALID, mutually consistent
                    sources
    NOT_AVAILABLE   an authoritative source is absent or persisted FAILED
                    (``reason`` names it) — a NORMAL partial analysis, 200
    NOT_CONFIGURED  the user-authored economics assumptions do not exist yet

A present but malformed or mutually inconsistent source is never a section
state: it is a typed 409 refusal (``ANALYSIS_SOURCE_INCONSISTENT`` /
``ARTIFACT_MALFORMED`` / ``READ_SNAPSHOT_CHANGED``).

Vocabulary is fixed by the directive: "planned mined tonnes" come ONLY from
production geometry (stope / cut / extraction-unit solids × density), the
development volume is GROSS (junction overlap is not unioned) and the grade
figure is the Phase 09 PLANNING PROXY — never a resource, a reserve, a
recoverable or an economic grade. Revenue never uses the grade proxy.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from minegen.core.enums import EdgeType, MiningMethodType
from minegen.core.models import ApiModel

__all__ = [
    "ECONOMICS_DISCLAIMER",
    "AnalysisSources",
    "Availability",
    "CashflowBucket",
    "CutFillProductionDetail",
    "DevelopmentCategory",
    "DevelopmentCrossCheck",
    "DevelopmentSection",
    "DevelopmentTotals",
    "EconomicsSection",
    "EconomicsSummary",
    "LongholeProductionDetail",
    "MineAnalysisPayload",
    "PlanningRatios",
    "ProductionDetail",
    "ProductionSection",
    "RoomPillarProductionDetail",
    "ScheduleSection",
]

Availability = Literal["AVAILABLE", "NOT_AVAILABLE", "NOT_CONFIGURED"]

#: the fixed wording every economics payload carries (directive §29 / §55)
ECONOMICS_DISCLAIMER = (
    "Synthetic planning economics. Not a resource/reserve estimate or feasibility study."
)


class AnalysisSources(ApiModel):
    """The file revisions the analysis was computed from (``null`` = absent).
    They are provenance for the client's cache identity, never freshness
    proofs (AC-01F A12)."""

    scenario_revision: str
    network_revision: str | None
    production_revision: str | None
    timeline_revision: str | None
    economics_revision: str | None


# --------------------------------------------------------------------------- #
# Development (22A §12–14)
# --------------------------------------------------------------------------- #


class DevelopmentCategory(ApiModel):
    edge_type: EdgeType
    edge_count: int
    total_length_m: float
    #: Σ length3d × crossSection.analyticArea — GROSS, junctions not unioned
    gross_excavation_volume_m3: float


class DevelopmentTotals(ApiModel):
    total_development_length_m: float
    gross_development_volume_m3: float
    ramp_length_m: float
    level_access_length_m: float
    drift_length_m: float
    crosscut_length_m: float
    shaft_length_m: float
    shaft_station_access_length_m: float


class DevelopmentCrossCheck(ApiModel):
    """The declared ``NetworkMetrics`` re-derived from the edges: counts must
    agree exactly, lengths within ``toleranceM``. The declared metrics are
    never overwritten — a disagreement is a typed 409."""

    tolerance_m: float
    max_length_difference_m: float
    max_count_difference: int


class DevelopmentSection(ApiModel):
    availability: Availability
    reason: str | None
    categories: list[DevelopmentCategory]
    totals: DevelopmentTotals | None
    cross_check: DevelopmentCrossCheck | None


# --------------------------------------------------------------------------- #
# Production (22A §15–19)
# --------------------------------------------------------------------------- #


class LongholeProductionDetail(ApiModel):
    kind: Literal["LONGHOLE_OPEN_STOPING"] = "LONGHOLE_OPEN_STOPING"
    stope_count: int
    level_interval_count: int


class CutFillProductionDetail(ApiModel):
    kind: Literal["CUT_AND_FILL"] = "CUT_AND_FILL"
    cut_count: int
    lift_count: int
    backfill_count: int
    #: backfill is NOT production: reported separately, never added to the
    #: production volume
    total_backfill_volume_m3: float


class RoomPillarProductionDetail(ApiModel):
    kind: Literal["ROOM_AND_PILLAR"] = "ROOM_AND_PILLAR"
    room_count: int
    extraction_unit_count: int
    pillar_count: int
    heading_count: int
    bench_count: int
    #: retained in-situ material — never production, never mined tonnes
    retained_pillar_volume_m3: float
    retained_pillar_tonnes_equivalent: float
    geometric_extraction_fraction: float


ProductionDetail = LongholeProductionDetail | CutFillProductionDetail | RoomPillarProductionDetail


class ProductionSection(ApiModel):
    availability: Availability
    reason: str | None
    method: MiningMethodType | None
    production_object_count: int | None
    #: Σ geometricVolumeM3 of the production objects (stopes / cuts /
    #: extraction units) — pillars and backfills excluded
    total_production_volume_m3: float | None
    #: Σ tonnes of the production objects: PLANNED MINED tonnes from
    #: excavation geometry × density, never a resource or reserve
    total_planned_mined_tonnes: float | None
    #: tonnage-weighted Phase 09 planning grade proxy — informational only
    weighted_mean_grade_proxy: float | None
    detail: ProductionDetail | None = Field(default=None, discriminator="kind")


# --------------------------------------------------------------------------- #
# Schedule (22A §20–21)
# --------------------------------------------------------------------------- #


class ScheduleSection(ApiModel):
    availability: Availability
    reason: str | None
    task_count: int | None
    development_task_count: int | None
    production_task_count: int | None
    start_day: float | None
    end_day: float | None
    #: endDay − startDay of the precedence-only baseline (rule 82): a
    #: synthetic planning baseline, never a production forecast
    mine_duration_days: float | None
    ramp_completion_day: float | None
    #: min startDay over STOPING tasks (method-generic), cross-checked against
    #: the timeline's own ``firstStopingDay``
    first_production_day: float | None


class PlanningRatios(ApiModel):
    availability: Availability
    reason: str | None
    #: totalDevelopmentLengthM / (plannedMinedTonnes / 1000); null when tonnes = 0
    development_metres_per_kt: float | None
    gross_development_m3_per_kt: float | None


# --------------------------------------------------------------------------- #
# Economics (22B §31–41)
# --------------------------------------------------------------------------- #


class EconomicsSummary(ApiModel):
    development_cost: float
    production_mining_cost: float
    processing_cost: float
    backfill_cost: float
    fixed_operating_cost: float
    initial_capital_cost: float
    total_cost: float
    total_revenue: float
    undiscounted_net_cashflow: float
    #: Baseline Planning NPV — Σ discounted bucket net cashflows (mid-bucket
    #: convention)
    npv: float


class CashflowBucket(ApiModel):
    index: int
    start_day: float
    end_day: float
    development_cost: float
    production_mining_cost: float
    processing_cost: float
    backfill_cost: float
    fixed_operating_cost: float
    initial_capital_cost: float
    revenue: float
    net_cashflow: float
    cumulative_cashflow: float
    discounted_net_cashflow: float


#: hardening PR-2 H3 §8.2 — the bounded bisection bracket (annual rate)
IRR_MIN = -0.99
IRR_MAX = 10.0
IrrStatus = Literal["DEFINED", "NOT_DEFINED", "NOT_CONFIGURED"]
IrrReason = Literal["NO_SIGN_CHANGE", "MULTIPLE_SIGN_CHANGES"]


class PlanningIrr(ApiModel):
    """Planning IRR under the Baseline Planning NPV timing convention
    (mid-bucket): typed, never NaN / Infinity (rule 34). ``DEFINED`` only when
    the non-zero bucket net cashflows change sign exactly once; otherwise
    ``NOT_DEFINED`` with the reason; ``NOT_CONFIGURED`` without a cashflow."""

    status: IrrStatus
    annual_rate: float | None
    reason: IrrReason | None
    convention: Literal["MID_BUCKET_MIDPOINT"] = "MID_BUCKET_MIDPOINT"
    bracket: tuple[float, float] = (IRR_MIN, IRR_MAX)
    name: Literal["Planning IRR"] = "Planning IRR"


def not_configured_irr() -> PlanningIrr:
    return PlanningIrr(status="NOT_CONFIGURED", annual_rate=None, reason=None)


class EconomicsSection(ApiModel):
    availability: Availability
    reason: str | None
    economics_revision: str | None
    currency_code: str | None
    cashflow_bucket_days: float | None
    annual_discount_rate: float | None
    #: the ONE revenue model of v0.1: plannedMinedTonnes × grossRevenuePerMinedTonne
    revenue_model: Literal["GROSS_REVENUE_PER_MINED_TONNE"] = "GROSS_REVENUE_PER_MINED_TONNE"
    #: the discounting convention: each bucket's net cashflow is discounted at
    #: the bucket's midpoint day, year = midDay / 365.25
    npv_convention: Literal["MID_BUCKET_MIDPOINT"] = "MID_BUCKET_MIDPOINT"
    summary: EconomicsSummary | None
    cashflow: list[CashflowBucket]
    #: hardening PR-2 H3 §8.2 (additive): the Planning IRR of the cashflow
    #: under the same mid-bucket convention — typed, never NaN / Infinity
    planning_irr: PlanningIrr = Field(default_factory=not_configured_irr)
    disclaimer: str = ECONOMICS_DISCLAIMER


# --------------------------------------------------------------------------- #
# Payload
# --------------------------------------------------------------------------- #


class MineAnalysisPayload(ApiModel):
    """The whole read model. ``status`` is the projection's own status: the
    route answers a typed 409 for every failure, so a returned payload is
    always ``SUCCESS`` — partial availability is carried per section."""

    status: Literal["SUCCESS"] = "SUCCESS"
    sources: AnalysisSources
    development: DevelopmentSection
    production: ProductionSection
    schedule: ScheduleSection
    ratios: PlanningRatios
    economics: EconomicsSection
