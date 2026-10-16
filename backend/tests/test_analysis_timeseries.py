"""Hardening PR-2 H3 §6 — the analysis time series projection
(``analysis/timeseries.py``): bucketed excavated development rock, planned
mined tonnes, backfill, retained pillars and the economics series, from the
SAME task windows and linear allocation as the Planning Cashflow; host-rock
density is optional with no default; nothing is persisted."""

from __future__ import annotations

import copy
import math
from dataclasses import replace
from typing import Any

import pytest

from minegen.analysis.builder import build_analysis
from minegen.analysis.cashflow import bucket_count
from minegen.analysis.timeseries import (
    DEFAULT_BUCKET_DAYS,
    DEVELOPMENT_ROCK_VOCABULARY,
    build_timeseries,
)
from minegen.core.models import GeologyConfig, Scenario
from tests import analysis_support as fx


def _dump(payload: Any) -> dict[str, Any]:
    out: dict[str, Any] = payload.model_dump(mode="json", by_alias=True)
    return out


def _with_density(scenario: Scenario, density: float | None) -> Scenario:
    return scenario.model_copy(
        update={
            "geology": GeologyConfig.model_validate(
                {**scenario.geology.model_dump(by_alias=True), "hostRockDensity": density}
            )
        }
    )


def test_quantities_reconcile_with_the_analysis_totals_and_the_cashflow_ledger() -> None:
    inputs = fx.inputs()
    analysis = build_analysis(inputs)
    series = build_timeseries(inputs, 30.0)
    doc = _dump(series)
    assert doc["status"] == "SUCCESS" and doc["availability"] == "AVAILABLE"
    assert doc["bucketDays"] == 30.0
    assert doc["bucketCount"] == bucket_count(fx.END_DAY, 30.0) == len(doc["buckets"])
    assert (
        doc["developmentRockVocabulary"]
        == DEVELOPMENT_ROCK_VOCABULARY
        == ("Excavated development rock")
    )
    assert "waste" not in str(doc).lower()
    totals = doc["totals"]
    dev = analysis.development.totals
    prod = analysis.production
    assert dev is not None and prod.total_planned_mined_tonnes is not None
    assert math.isclose(totals["developmentLengthM"], dev.total_development_length_m, rel_tol=1e-9)
    assert math.isclose(
        totals["developmentExcavationM3"], dev.gross_development_volume_m3, rel_tol=1e-9
    )
    assert math.isclose(totals["productionTonnes"], prod.total_planned_mined_tonnes, rel_tol=1e-9)
    # Longhole: no backfill, no cemented fill, no retained pillar
    assert totals["backfillM3"] == 0.0 and totals["cementedBackfillM3"] == 0.0
    assert doc["retained"]["availability"] == "AVAILABLE" and doc["retained"]["pillarCount"] == 0
    # the economics series IS the cashflow ledger at the same resolution
    assert doc["economics"]["availability"] == "AVAILABLE"
    cash = analysis.economics.cashflow
    assert len(cash) == len(doc["buckets"])
    for b, c in zip(doc["buckets"], cash, strict=True):
        q = b["bucket"]
        cost = (
            c.development_cost
            + c.production_mining_cost
            + c.processing_cost
            + c.backfill_cost
            + c.fixed_operating_cost
            + c.initial_capital_cost
        )
        assert math.isclose(q["cost"], cost, rel_tol=1e-9, abs_tol=1e-9)
        assert math.isclose(q["revenue"], c.revenue, rel_tol=1e-9, abs_tol=1e-9)
        assert math.isclose(q["netCashflow"], c.net_cashflow, rel_tol=1e-9, abs_tol=1e-9)
        assert math.isclose(
            b["cumulativeCashflow"], c.cumulative_cashflow, rel_tol=1e-9, abs_tol=1e-9
        )
    # cumulative rows are running sums of the bucket rows; the last one is the totals
    running = 0.0
    for b in doc["buckets"]:
        running += b["bucket"]["developmentLengthM"]
        assert math.isclose(b["cumulative"]["developmentLengthM"], running, rel_tol=1e-9)
    assert doc["buckets"][-1]["cumulative"] == totals


def test_bucket_resolution_is_the_callers_and_totals_are_resolution_invariant() -> None:
    inputs = fx.inputs()
    fine = _dump(build_timeseries(inputs, 7.0))
    coarse = _dump(build_timeseries(inputs, 60.0))
    assert fine["bucketCount"] == bucket_count(fx.END_DAY, 7.0) > coarse["bucketCount"]
    for key in ("developmentLengthM", "developmentExcavationM3", "productionTonnes", "cost"):
        assert math.isclose(fine["totals"][key], coarse["totals"][key], rel_tol=1e-9, abs_tol=1e-9)
    with pytest.raises(ValueError):
        build_timeseries(inputs, 0.0)
    assert DEFAULT_BUCKET_DAYS == 30.0


def test_development_tonnes_need_an_explicit_density_never_a_default() -> None:
    base = fx.inputs()
    absent = _dump(build_timeseries(base, 30.0))
    assert absent["developmentTonnes"] == {
        "status": "NOT_CONFIGURED",
        "hostRockDensity": None,
        "reason": absent["developmentTonnes"]["reason"],
    }
    assert "default" in absent["developmentTonnes"]["reason"]
    assert absent["totals"]["developmentTonnes"] is None
    assert all(b["bucket"]["developmentTonnes"] is None for b in absent["buckets"])
    # no 2.7 appears anywhere in the payload
    assert "2.7" not in str(absent)
    dense = replace(base, scenario=_with_density(base.scenario, 2.65))
    present = _dump(build_timeseries(dense, 30.0))
    assert present["developmentTonnes"]["status"] == "AVAILABLE"
    assert present["developmentTonnes"]["hostRockDensity"] == 2.65
    assert math.isclose(
        present["totals"]["developmentTonnes"],
        present["totals"]["developmentExcavationM3"] * 2.65,
        rel_tol=1e-9,
    )
    with pytest.raises(ValueError):
        _with_density(base.scenario, 0.0)


def test_without_economics_the_quantity_series_stay_and_the_money_cells_are_null() -> None:
    doc = _dump(build_timeseries(fx.inputs_without_config(), 30.0))
    assert doc["availability"] == "AVAILABLE"
    assert doc["economics"]["availability"] == "NOT_CONFIGURED"
    assert doc["economics"]["reason"] == "Planning economics is not configured."
    assert doc["totals"]["productionTonnes"] > 0.0
    for b in doc["buckets"]:
        assert b["bucket"]["cost"] is None and b["bucket"]["revenue"] is None
        assert b["bucket"]["netCashflow"] is None and b["cumulativeCashflow"] is None
    # the configured-but-absent default resolution is the economics bucket
    # width; here nothing is configured so the caller's value is used as is
    assert doc["bucketDays"] == 30.0


def test_missing_sources_are_a_partial_payload_never_a_refusal() -> None:
    no_timeline = _dump(build_timeseries(fx.inputs(with_timeline=False), 30.0))
    assert no_timeline["availability"] == "NOT_AVAILABLE"
    assert "schedule" in no_timeline["reason"]
    assert no_timeline["buckets"] == [] and no_timeline["totals"] is None
    assert no_timeline["bucketCount"] == 0
    # retained pillars are a production fact and survive a missing timeline
    assert no_timeline["retained"]["availability"] == "AVAILABLE"
    no_world = _dump(build_timeseries(fx.inputs(world_generated=False), 30.0))
    assert no_world["availability"] == "NOT_AVAILABLE"
    assert no_world["retained"]["availability"] == "NOT_AVAILABLE"
    assert no_world["economics"]["availability"] == "NOT_AVAILABLE"


def test_production_tonnes_follow_the_stoping_window_linearly() -> None:
    """One stope's tonnes land in the buckets its STOPING task overlaps, by
    overlap fraction — the Planning Cashflow allocation, never a point event."""
    tl = copy.deepcopy(fx.timeline_doc())
    sid = fx.STOPES[1][0]  # STOPE:B — the chain is re-timed as a whole
    windows = {
        "STOPING": (75.0, 105.0),
        "MUCKING": (105.0, 110.0),
        "BACKFILL": (110.0, 115.0),
        "CURE": (115.0, 120.0),
    }
    for name, (start, end) in windows.items():
        task = next(t for t in tl["tasks"] if t["id"] == f"TASK:{name}:{sid}")
        task["startDay"], task["endDay"], task["durationDays"] = start, end, end - start
    tonnes = fx.STOPES[1][1]
    doc = _dump(build_timeseries(fx.inputs(timeline=tl), 30.0))
    by_bucket = [b["bucket"]["productionTonnes"] for b in doc["buckets"]]
    assert math.isclose(math.fsum(by_bucket), math.fsum(s[1] for s in fx.STOPES), rel_tol=1e-9)
    # STOPE:A (STOPING 50–60) sits wholly in bucket 1 [30, 60); STOPE:B spreads
    # 15/30 into bucket 2 [60, 90) and 15/30 into bucket 3 [90, 120]
    assert math.isclose(by_bucket[1], fx.STOPES[0][1], rel_tol=1e-9)
    assert math.isclose(by_bucket[2], tonnes * 0.5, rel_tol=1e-9)
    assert math.isclose(by_bucket[3], tonnes * 0.5, rel_tol=1e-9)
    assert by_bucket[0] == 0.0
