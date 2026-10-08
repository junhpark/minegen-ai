"""Hardening PR-2 H3 §8.2–8.3 — Planning IRR (typed, mid-bucket convention,
bisection) and the read-only sensitivity / what-if grid over the analysis
support fixtures. Nothing is persisted: these are pure projections."""

from __future__ import annotations

import copy
import math
from dataclasses import replace
from typing import Any

import pytest

from minegen.analysis.builder import build_analysis
from minegen.analysis.cashflow import DAYS_PER_YEAR
from minegen.analysis.irr import npv_at, planning_irr
from minegen.analysis.models import CashflowBucket
from minegen.analysis.sensitivity import (
    DEFAULT_PERTURBATIONS_PCT,
    PARAMETERS,
    WHAT_IF_LABEL,
    SensitivityInputs,
    WhatIfFactors,
    build_sensitivity,
    evaluate_what_if,
    scaled_economics,
    scaled_schedule,
)
from tests import analysis_support as fx


def _bucket(i: int, net: float, width: float = 30.0) -> CashflowBucket:
    return CashflowBucket(
        index=i,
        start_day=i * width,
        end_day=(i + 1) * width,
        development_cost=0.0,
        production_mining_cost=0.0,
        processing_cost=0.0,
        backfill_cost=0.0,
        fixed_operating_cost=0.0,
        initial_capital_cost=max(0.0, -net),
        revenue=max(0.0, net),
        net_cashflow=net,
        cumulative_cashflow=0.0,
        discounted_net_cashflow=net,
    )


def _dump(payload: Any) -> dict[str, Any]:
    out: dict[str, Any] = payload.model_dump(mode="json", by_alias=True)
    return out


# --------------------------------------------------------------------------- #
# Planning IRR
# --------------------------------------------------------------------------- #


def test_irr_is_defined_for_one_sign_change_and_solves_the_mid_bucket_npv() -> None:
    buckets = [_bucket(0, -1000.0), _bucket(1, 400.0), _bucket(2, 400.0), _bucket(3, 400.0)]
    irr = planning_irr(buckets)
    assert irr.status == "DEFINED" and irr.reason is None and irr.annual_rate is not None
    assert math.isfinite(irr.annual_rate)
    # the root of the SAME discounting convention as the Baseline Planning NPV
    assert abs(npv_at(buckets, irr.annual_rate)) < 1e-6
    manual = math.fsum(
        b.net_cashflow
        / (1.0 + irr.annual_rate) ** (0.5 * (b.start_day + b.end_day) / DAYS_PER_YEAR)
        for b in buckets
    )
    assert abs(manual) < 1e-6
    assert irr.convention == "MID_BUCKET_MIDPOINT" and irr.name == "Planning IRR"
    assert irr.bracket == (-0.99, 10.0)
    doc = _dump(irr)
    assert "nan" not in str(doc).lower() and "inf" not in str(doc).lower()


def test_irr_is_typed_not_defined_without_or_with_multiple_sign_changes() -> None:
    none = planning_irr([_bucket(0, -10.0), _bucket(1, -5.0), _bucket(2, 0.0)])
    assert none.status == "NOT_DEFINED" and none.reason == "NO_SIGN_CHANGE"
    assert none.annual_rate is None
    positive = planning_irr([_bucket(0, 10.0), _bucket(1, 5.0)])
    assert positive.status == "NOT_DEFINED" and positive.reason == "NO_SIGN_CHANGE"
    multi = planning_irr([_bucket(0, -10.0), _bucket(1, 30.0), _bucket(2, -30.0), _bucket(3, 20.0)])
    assert multi.status == "NOT_DEFINED" and multi.reason == "MULTIPLE_SIGN_CHANGES"
    assert multi.annual_rate is None
    # zeros never count as a sign change
    zeros = planning_irr([_bucket(0, -10.0), _bucket(1, 0.0), _bucket(2, 0.0), _bucket(3, 15.0)])
    assert zeros.status == "DEFINED"
    assert planning_irr([]).status == "NOT_DEFINED"


def test_the_economics_section_carries_the_irr_of_its_own_cashflow() -> None:
    doc = _dump(build_analysis(fx.inputs()))
    eco = doc["economics"]
    assert eco["planningIrr"]["name"] == "Planning IRR"
    assert eco["planningIrr"]["status"] in ("DEFINED", "NOT_DEFINED")
    if eco["planningIrr"]["status"] == "DEFINED":
        rate = eco["planningIrr"]["annualRate"]
        assert math.isfinite(rate)
        buckets = [CashflowBucket.model_validate(b) for b in eco["cashflow"]]
        assert abs(npv_at(buckets, rate)) < 1e-6
    unconfigured = _dump(build_analysis(fx.inputs_without_config()))
    assert unconfigured["economics"]["planningIrr"] == {
        "status": "NOT_CONFIGURED",
        "annualRate": None,
        "reason": None,
        "convention": "MID_BUCKET_MIDPOINT",
        "bracket": [-0.99, 10.0],
        "name": "Planning IRR",
    }


# --------------------------------------------------------------------------- #
# sensitivity / what-if
# --------------------------------------------------------------------------- #


def _inputs(**kw: Any) -> SensitivityInputs:
    """The support fixtures carry no ramp / levels document: economic what-ifs
    run; schedule what-ifs are NOT_AVAILABLE unless the test supplies them."""
    return SensitivityInputs(
        analysis=fx.inputs(**kw),
        ramp_payload=None,
        levels_payload=None,
        accesses_payload=None,
        shafts_payload=None,
    )


def test_base_what_if_reproduces_the_analysis_economics_exactly() -> None:
    analysis = build_analysis(fx.inputs())
    base = evaluate_what_if(_inputs(), WhatIfFactors())
    assert base.status == "AVAILABLE" and base.schedule_rebuilt is False
    assert base.label == WHAT_IF_LABEL == "WHAT-IF OVERRIDE — NOT SCENARIO VALUE"
    s = analysis.economics.summary
    assert s is not None and base.planning_npv is not None
    assert math.isclose(base.planning_npv, s.npv, rel_tol=1e-12, abs_tol=1e-9)
    assert math.isclose(base.undiscounted_net_cashflow or 0.0, s.undiscounted_net_cashflow)
    assert base.planning_irr == analysis.economics.planning_irr
    assert base.mine_duration_days == analysis.schedule.mine_duration_days
    assert base.first_production_day == analysis.schedule.first_production_day


def test_economic_factors_scale_exactly_the_declared_assumption() -> None:
    cfg = fx.inputs().economics
    assert cfg is not None
    scaled = scaled_economics(cfg, WhatIfFactors(gross_revenue_per_mined_tonne=1.2))
    assert math.isclose(
        scaled.gross_revenue_per_mined_tonne, cfg.gross_revenue_per_mined_tonne * 1.2
    )
    assert scaled.development_costs == cfg.development_costs
    assert scaled.processing_cost_per_tonne == cfg.processing_cost_per_tonne
    dev = scaled_economics(cfg, WhatIfFactors(development_cost=0.7)).development_costs
    assert math.isclose(dev.ramp_per_m, cfg.development_costs.ramp_per_m * 0.7)
    assert math.isclose(dev.raise_per_m, cfg.development_costs.raise_per_m * 0.7)
    # revenue up → NPV up by exactly the discounted extra revenue; no persistence of anything
    base = evaluate_what_if(_inputs(), WhatIfFactors())
    up = evaluate_what_if(_inputs(), WhatIfFactors(gross_revenue_per_mined_tonne=1.1))
    assert up.planning_npv is not None and base.planning_npv is not None
    assert up.planning_npv > base.planning_npv
    assert up.mine_duration_days == base.mine_duration_days  # economics never move time
    capex = evaluate_what_if(_inputs(), WhatIfFactors(initial_capital=2.0))
    assert capex.planning_npv is not None
    # capital sits in bucket 0: the delta is the extra capital discounted at
    # the first bucket's midpoint (the SAME mid-bucket convention as the NPV)
    mid_factor = (1.0 + cfg.annual_discount_rate) ** (
        0.5 * cfg.cashflow_bucket_days / DAYS_PER_YEAR
    )
    assert math.isclose(
        base.planning_npv - capex.planning_npv, cfg.initial_capital_cost / mid_factor, rel_tol=1e-9
    )
    # a discount-rate factor of 0 is not a legal override (never a hidden default)
    with pytest.raises(ValueError):
        WhatIfFactors(discount_rate=0.0)


def test_schedule_factors_scale_the_rates_and_need_the_owning_centerlines() -> None:
    sch = fx.inputs().scenario.schedule
    faster = scaled_schedule(sch, WhatIfFactors(development_rate=1.5))
    assert math.isclose(faster.ramp_advance_m_per_day, sch.ramp_advance_m_per_day * 1.5)
    assert math.isclose(faster.shaft_sink_m_per_day, sch.shaft_sink_m_per_day * 1.5)
    assert faster.stoping_tonnes_per_day == sch.stoping_tonnes_per_day
    assert faster.backfill_m3_per_day == sch.backfill_m3_per_day  # untouched
    mining = scaled_schedule(sch, WhatIfFactors(mining_rate=0.5))
    assert math.isclose(mining.stoping_tonnes_per_day, sch.stoping_tonnes_per_day * 0.5)
    assert math.isclose(mining.mucking_tonnes_per_day, sch.mucking_tonnes_per_day * 0.5)
    assert mining.stope_preparation_days == sch.stope_preparation_days
    # without the ramp / levels documents a reschedule is explicitly NOT_AVAILABLE
    outcome = evaluate_what_if(_inputs(), WhatIfFactors(development_rate=1.2))
    assert outcome.status == "NOT_AVAILABLE" and outcome.schedule_rebuilt is False
    assert "effective ramp" in (outcome.reason or "")


def test_sensitivity_grid_is_the_declared_parameters_times_the_perturbations() -> None:
    payload = build_sensitivity(_inputs())
    doc = _dump(payload)
    assert doc["label"] == WHAT_IF_LABEL and doc["base"]["label"] == WHAT_IF_LABEL
    assert doc["revenueModel"] == "GROSS_REVENUE_PER_MINED_TONNE"
    assert doc["perturbationsPct"] == list(DEFAULT_PERTURBATIONS_PCT)
    assert [p["key"] for p in doc["parameters"]] == [k for k, _, _ in PARAMETERS]
    assert any(p["label"] == "Gross revenue per mined tonne" for p in doc["parameters"])
    assert len(doc["cases"]) == len(PARAMETERS) * len(DEFAULT_PERTURBATIONS_PCT)
    for case in doc["cases"]:
        assert math.isclose(case["factor"], 1.0 + case["perturbationPct"] / 100.0)
        assert case["outcome"]["label"] == WHAT_IF_LABEL
        if case["kind"] == "ECONOMIC":
            assert case["outcome"]["status"] == "AVAILABLE"
            assert case["outcome"]["mineDurationDeltaDays"] == 0.0
            assert case["outcome"]["firstProductionDeltaDays"] == 0.0
        else:
            # the support fixtures carry no ramp document → typed NOT_AVAILABLE
            assert case["outcome"]["status"] == "NOT_AVAILABLE"
            assert case["outcome"]["npvDelta"] is None
    revenue_cases = [c for c in doc["cases"] if c["parameter"] == "gross_revenue_per_mined_tonne"]
    deltas = [c["outcome"]["npvDelta"] for c in revenue_cases]
    assert deltas == sorted(deltas)  # monotonic in the perturbation
    assert all(d < 0 for d in deltas[:3]) and all(d > 0 for d in deltas[3:])
    # no commodity vocabulary anywhere in the payload
    text = str(doc).lower()
    for word in ("gold", "copper", "recovery", "payab", "royalt", " tax"):
        assert word not in text, word
    with pytest.raises(ValueError):
        build_sensitivity(_inputs(), (0.0,))


def test_without_economics_the_grid_keeps_the_schedule_outputs_only() -> None:
    inputs = replace(_inputs(), analysis=fx.inputs_without_config())
    doc = _dump(build_sensitivity(inputs))
    assert doc["availability"] == "NOT_CONFIGURED"
    assert doc["base"]["status"] == "AVAILABLE" and doc["base"]["planningNpv"] is None
    assert doc["base"]["planningIrr"]["status"] == "NOT_CONFIGURED"
    assert doc["base"]["mineDurationDays"] == fx.END_DAY
    for case in doc["cases"]:
        assert case["outcome"]["planningNpv"] is None


def test_missing_sources_make_the_grid_not_available_never_a_refusal() -> None:
    doc = _dump(build_sensitivity(replace(_inputs(), analysis=fx.inputs(with_timeline=False))))
    assert doc["availability"] == "NOT_AVAILABLE" and doc["cases"] == []
    assert "schedule" in doc["reason"]
    tl = copy.deepcopy(fx.timeline_doc())
    tl["status"] = "FAILED"
    doc = _dump(build_sensitivity(replace(_inputs(), analysis=fx.inputs(timeline=tl))))
    assert doc["availability"] == "NOT_AVAILABLE"
