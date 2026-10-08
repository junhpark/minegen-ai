"""Analysis time series (hardening PR-2 H3 §6) — ONE read-only projection of
the persisted mine into fixed day buckets:

    GET …/analysis/timeseries?bucketDays=<n>

Quantities come ONLY from geometry (network edge lengths and analytic
cross-sections, production unit tonnes, backfill volumes) and timing ONLY from
the MineTimeline task windows — exactly the Planning Cashflow convention
(``analysis/cashflow.py``): an amount attached to a task interval is spread
linearly over that interval and allocated to the buckets by overlap fraction.

* development length / gross excavation volume → the DEVELOPMENT task of the
  edge (``Excavated development rock`` — never "waste"); development tonnes
  ONLY when ``scenario.geology.hostRockDensity`` is declared (no default:
  absent → ``NOT_CONFIGURED`` and ``null`` cells, never 2.7 t/m³);
* planned mined tonnes → the STOPING task of each production unit (the
  excavation of the unit; pillars and backfill are never production);
* backfill volume (Cut & Fill) → the BACKFILL task of the cut, the cemented
  sill-mat fills reported separately;
* retained pillars (Room & Pillar pillars, Cut & Fill rib pillars) are never
  scheduled: they are reported as totals, never per bucket;
* cost / revenue / net / cumulative cashflow → the SAME ledger
  ``builder.economics_ledger`` builds for the Planning Cashflow, at the
  requested bucket resolution — ``NOT_CONFIGURED`` without ``economics.json``.

No persistence, no invalidation, no scenario mutation; the service wraps the
projection in the bound-snapshot protocol (``READ_SNAPSHOT_CHANGED``). The
frontend renders these series and never re-sums timeline tasks itself.
"""

from __future__ import annotations

import math
from typing import Final, Literal

from minegen.analysis.builder import (
    AnalysisInputs,
    _development,
    _production,
    _schedule,
    economics_ledger,
)
from minegen.analysis.cashflow import COLUMNS, BucketLedger, allocate_linear, bucket_count
from minegen.analysis.economics import production_rate
from minegen.analysis.models import ECONOMICS_DISCLAIMER, AnalysisSources, Availability
from minegen.core.enums import TaskType
from minegen.core.models import ApiModel
from minegen.mining.models import CutFillPayload, RoomPillarPayload

__all__ = [
    "DEFAULT_BUCKET_DAYS",
    "DEVELOPMENT_ROCK_VOCABULARY",
    "TimeseriesBucket",
    "TimeseriesPayload",
    "build_timeseries",
]

#: display default when the caller names no resolution and no economics
#: document declares one — a presentation choice, never an engineering value
DEFAULT_BUCKET_DAYS = 30.0
#: directive §6: development rock is EXCAVATED DEVELOPMENT ROCK, never "waste"
DEVELOPMENT_ROCK_VOCABULARY: Final[Literal["Excavated development rock"]] = (
    "Excavated development rock"
)

QUANTITY_COLUMNS = (
    "development_length_m",
    "development_excavation_m3",
    "production_tonnes",
    "backfill_m3",
    "cemented_backfill_m3",
)


class TimeseriesQuantities(ApiModel):
    """One bucket's quantities (or the running cumulative)."""

    development_length_m: float
    development_excavation_m3: float
    #: ``null`` unless ``scenario.geology.hostRockDensity`` is declared
    development_tonnes: float | None
    production_tonnes: float
    backfill_m3: float
    cemented_backfill_m3: float
    #: economics — ``null`` unless configured and available
    cost: float | None
    revenue: float | None
    net_cashflow: float | None


class TimeseriesBucket(ApiModel):
    index: int
    start_day: float
    end_day: float
    bucket: TimeseriesQuantities
    cumulative: TimeseriesQuantities
    #: cumulative net cashflow at the bucket end (``null`` when not configured)
    cumulative_cashflow: float | None


class DevelopmentTonnesStatus(ApiModel):
    status: Literal["AVAILABLE", "NOT_CONFIGURED"]
    host_rock_density: float | None
    reason: str | None


class RetainedSection(ApiModel):
    """Retained in-situ material (Room & Pillar pillars, Cut & Fill rib
    pillars): never scheduled, never production — totals only."""

    availability: Availability
    reason: str | None
    pillar_count: int | None
    pillar_volume_m3: float | None
    pillar_tonnes_equivalent: float | None


class TimeseriesEconomicsStatus(ApiModel):
    availability: Availability
    reason: str | None
    currency_code: str | None
    economics_revision: str | None


class TimeseriesPayload(ApiModel):
    status: Literal["SUCCESS"] = "SUCCESS"
    sources: AnalysisSources
    availability: Availability
    reason: str | None
    bucket_days: float
    bucket_count: int
    start_day: float | None
    end_day: float | None
    development_tonnes: DevelopmentTonnesStatus
    retained: RetainedSection
    economics: TimeseriesEconomicsStatus
    #: the final cumulative row (the mine totals at ``endDay``)
    totals: TimeseriesQuantities | None
    buckets: list[TimeseriesBucket]
    development_rock_vocabulary: Literal["Excavated development rock"] = DEVELOPMENT_ROCK_VOCABULARY
    allocation: Literal["LINEAR_OVER_TASK_WINDOW"] = "LINEAR_OVER_TASK_WINDOW"
    disclaimer: str = ECONOMICS_DISCLAIMER


def _quantities(
    cells: dict[str, list[float]],
    i: int,
    density: float | None,
    economics: tuple[list[float], list[float]] | None,
) -> TimeseriesQuantities:
    volume = cells["development_excavation_m3"][i]
    cost = economics[0][i] if economics is not None else None
    revenue = economics[1][i] if economics is not None else None
    return TimeseriesQuantities(
        development_length_m=cells["development_length_m"][i],
        development_excavation_m3=volume,
        development_tonnes=volume * density if density is not None else None,
        production_tonnes=cells["production_tonnes"][i],
        backfill_m3=cells["backfill_m3"][i],
        cemented_backfill_m3=cells["cemented_backfill_m3"][i],
        cost=cost,
        revenue=revenue,
        net_cashflow=(revenue - cost) if cost is not None and revenue is not None else None,
    )


def build_timeseries(inputs: AnalysisInputs, bucket_days: float) -> TimeseriesPayload:
    if not bucket_days > 0.0:
        raise ValueError("bucketDays must be positive")
    development, network = _development(inputs)
    production, payload, units = _production(inputs)
    schedule, timeline, per_unit = _schedule(inputs, network, payload)
    sources = AnalysisSources(
        scenario_revision=inputs.scenario_revision,
        network_revision=inputs.network.revision if inputs.network else None,
        production_revision=inputs.production.revision if inputs.production else None,
        timeline_revision=inputs.timeline.revision if inputs.timeline else None,
        economics_revision=inputs.economics_revision,
    )
    density = inputs.scenario.geology.host_rock_density
    tonnes_status = DevelopmentTonnesStatus(
        status="AVAILABLE" if density is not None else "NOT_CONFIGURED",
        host_rock_density=density,
        reason=None
        if density is not None
        else "scenario.geology.hostRockDensity is not declared; development tonnes are not "
        "derived from any default density",
    )
    retained = RetainedSection(
        availability="NOT_AVAILABLE",
        reason=production.reason,
        pillar_count=None,
        pillar_volume_m3=None,
        pillar_tonnes_equivalent=None,
    )
    if payload is not None:
        pillars = (
            payload.pillars
            if isinstance(payload, RoomPillarPayload)
            else payload.rib_pillars
            if isinstance(payload, CutFillPayload)
            else []
        )
        retained = RetainedSection(
            availability="AVAILABLE",
            reason=None if pillars else "the active method retains no pillar",
            pillar_count=len(pillars),
            pillar_volume_m3=math.fsum(p.geometric_volume_m3 for p in pillars),
            pillar_tonnes_equivalent=math.fsum(p.tonnes_equivalent for p in pillars),
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
    economics_status = TimeseriesEconomicsStatus(
        availability="NOT_CONFIGURED" if inputs.economics is None else "NOT_AVAILABLE",
        reason="Planning economics is not configured." if inputs.economics is None else None,
        currency_code=inputs.economics.currency_code if inputs.economics else None,
        economics_revision=inputs.economics_revision,
    )
    if missing:
        reason = f"SOURCE_NOT_AVAILABLE: requires {', '.join(missing)}"
        return TimeseriesPayload(
            sources=sources,
            availability="NOT_AVAILABLE",
            reason=reason,
            bucket_days=bucket_days,
            bucket_count=0,
            start_day=None,
            end_day=None,
            development_tonnes=tonnes_status,
            retained=retained,
            economics=economics_status.model_copy(
                update={"reason": economics_status.reason or reason}
            ),
            totals=None,
            buckets=[],
        )
    assert network is not None and payload is not None and timeline is not None
    count = bucket_count(timeline.end_day, bucket_days)
    cells: dict[str, list[float]] = {c: [0.0] * count for c in QUANTITY_COLUMNS}

    def add(column: str, start: float, end: float, amount: float) -> None:
        if amount == 0.0:
            return
        for index, fraction in allocate_linear(start, end, bucket_days, count):
            cells[column][index] += amount * fraction

    dev_task_by_edge = {t.target_id: t for t in timeline.tasks if t.target_kind == "DEVELOPMENT"}
    for edge in network.edges:
        task = dev_task_by_edge[edge.id]  # verified by verify_timeline
        add("development_length_m", task.start_day, task.end_day, edge.length3d)
        add(
            "development_excavation_m3",
            task.start_day,
            task.end_day,
            edge.length3d * edge.cross_section.analytic_area,
        )
    backfills = (
        {b.source_cut_id: b for b in payload.backfills}
        if isinstance(payload, CutFillPayload)
        else {}
    )
    for unit in units:
        tasks = per_unit[unit.id]
        stoping = tasks[TaskType.STOPING]
        add("production_tonnes", stoping.start_day, stoping.end_day, unit.tonnes)
        if isinstance(payload, CutFillPayload):
            backfill = tasks[TaskType.BACKFILL]
            record = backfills[unit.id]  # verified by the method integrity check
            add("backfill_m3", backfill.start_day, backfill.end_day, record.volume_m3)
            if record.cemented:
                add("cemented_backfill_m3", backfill.start_day, backfill.end_day, record.volume_m3)

    economics: tuple[list[float], list[float]] | None = None
    config = inputs.economics
    if config is not None:
        if production_rate(config, inputs.scenario.mining.method) is None:
            economics_status = economics_status.model_copy(
                update={
                    "reason": "SOURCE_NOT_AVAILABLE: no production cost rate for "
                    f"{inputs.scenario.mining.method.value}"
                }
            )
        else:
            ledger: BucketLedger
            ledger, _breakdown = economics_ledger(
                config, network, payload, units, timeline, per_unit, bucket_days
            )
            cost = [math.fsum(ledger.cells[c][i] for c in COLUMNS[:-1]) for i in range(count)]
            revenue = list(ledger.cells["revenue"])
            economics = (cost, revenue)
            economics_status = economics_status.model_copy(
                update={"availability": "AVAILABLE", "reason": None}
            )

    cumulative_cells: dict[str, list[float]] = {}
    for column, values in cells.items():
        running = 0.0
        out: list[float] = []
        for v in values:
            running += v
            out.append(running)
        cumulative_cells[column] = out
    cumulative_economics: tuple[list[float], list[float]] | None = None
    if economics is not None:
        cost_c: list[float] = []
        rev_c: list[float] = []
        rc = rr = 0.0
        for c, r in zip(economics[0], economics[1], strict=True):
            rc += c
            rr += r
            cost_c.append(rc)
            rev_c.append(rr)
        cumulative_economics = (cost_c, rev_c)
    buckets: list[TimeseriesBucket] = []
    for i in range(count):
        cumulative = _quantities(cumulative_cells, i, density, cumulative_economics)
        buckets.append(
            TimeseriesBucket(
                index=i,
                start_day=i * bucket_days,
                end_day=(i + 1) * bucket_days,
                bucket=_quantities(cells, i, density, economics),
                cumulative=cumulative,
                cumulative_cashflow=cumulative.net_cashflow,
            )
        )
    return TimeseriesPayload(
        sources=sources,
        availability="AVAILABLE",
        reason=None,
        bucket_days=bucket_days,
        bucket_count=count,
        start_day=timeline.start_day,
        end_day=timeline.end_day,
        development_tonnes=tonnes_status,
        retained=retained,
        economics=economics_status,
        totals=buckets[-1].cumulative if buckets else None,
        buckets=buckets,
    )
