"""Phase 22A/B — the analysis projection on the hand-built mine
(``tests/analysis_support.py``): development quantities (A-1, A-2), the
declared-metrics cross-check (A-3), production summaries (A-4…A-6), ratios
(A-7), schedule KPIs (A-8), partial availability (A-9), typed inconsistency
(A-10), determinism (A-11), and the planning economics (B-6…B-20)."""

from __future__ import annotations

import copy
import json
import math
from typing import Any

import pytest

from minegen.analysis.builder import build_analysis
from minegen.analysis.cashflow import DAYS_PER_YEAR, allocate_linear, bucket_count
from minegen.analysis.economics import EconomicsConfig, canonical_json, config_revision
from minegen.analysis.integrity import AnalysisSourceInconsistentError
from minegen.analysis.models import ECONOMICS_DISCLAIMER
from minegen.core.enums import EdgeType, MiningMethodType
from tests import analysis_support as fx


def _dump(payload: Any) -> dict[str, Any]:
    out: dict[str, Any] = payload.model_dump(mode="json", by_alias=True)
    return out


# --------------------------------------------------------------------------- #
# 22A development
# --------------------------------------------------------------------------- #


def test_a1_a2_development_lengths_and_gross_volume_from_edges() -> None:
    dev = build_analysis(fx.inputs()).development
    assert dev.availability == "AVAILABLE" and dev.totals is not None
    by_type = {c.edge_type: c for c in dev.categories}
    assert [c.edge_type for c in dev.categories] == list(EdgeType)  # fixed enum order
    assert (by_type[EdgeType.RAMP].edge_count, by_type[EdgeType.RAMP].total_length_m) == (2, 150.0)
    assert by_type[EdgeType.RAMP].gross_excavation_volume_m3 == 100.0 * 20 + 50.0 * 20
    assert by_type[EdgeType.DRIFT].gross_excavation_volume_m3 == 40.0 * 16
    assert by_type[EdgeType.SHAFT].edge_count == 0
    t = dev.totals
    assert t.total_development_length_m == 230.0
    assert t.gross_development_volume_m3 == 3000.0 + 600.0 + 640.0 + 160.0
    assert (t.ramp_length_m, t.level_access_length_m, t.drift_length_m, t.crosscut_length_m) == (
        150.0,
        30.0,
        40.0,
        10.0,
    )
    assert (t.shaft_length_m, t.shaft_station_access_length_m) == (0.0, 0.0)
    assert dev.cross_check is not None and dev.cross_check.max_count_difference == 0
    assert dev.cross_check.max_length_difference_m <= dev.cross_check.tolerance_m


@pytest.mark.parametrize(
    ("field", "value"),
    [("totalRampLength3d", 151.0), ("driftEdgeCount", 2), ("edgeCount", 4)],
)
def test_a3_declared_metrics_mismatch_is_typed_and_never_overwritten(
    field: str, value: Any
) -> None:
    net = fx.network_doc()
    net["metrics"][field] = value
    with pytest.raises(AnalysisSourceInconsistentError, match=field):
        build_analysis(fx.inputs(network=net))


def test_a3_network_reference_defects_are_typed() -> None:
    net = fx.network_doc()
    net["edges"][0]["toNode"] = "NOPE"
    with pytest.raises(AnalysisSourceInconsistentError, match="unknown node"):
        build_analysis(fx.inputs(network=net))
    net = fx.network_doc()
    net["edges"].append(copy.deepcopy(net["edges"][0]))
    net["metrics"]["edgeCount"] += 1
    net["metrics"]["totalRampLength3d"] += 100.0
    with pytest.raises(AnalysisSourceInconsistentError, match="duplicate edge ids"):
        build_analysis(fx.inputs(network=net))


# --------------------------------------------------------------------------- #
# 22A production
# --------------------------------------------------------------------------- #


def test_a4_longhole_production_summary() -> None:
    prod = build_analysis(fx.inputs()).production
    assert prod.availability == "AVAILABLE"
    assert prod.method is MiningMethodType.LONGHOLE_OPEN_STOPING
    assert prod.production_object_count == 2
    assert prod.total_production_volume_m3 == 1600.0
    assert prod.total_planned_mined_tonnes == 4000.0
    assert prod.weighted_mean_grade_proxy == (1000 * 4.0 + 3000 * 2.0) / 4000
    assert prod.detail is not None and prod.detail.kind == "LONGHOLE_OPEN_STOPING"
    assert (prod.detail.stope_count, prod.detail.level_interval_count) == (2, 1)


def test_a4_production_vocabulary_never_claims_reserves() -> None:
    doc = json.dumps(_dump(build_analysis(fx.inputs()))).lower()
    for forbidden in ("reserve", "resource", "recoverable", "provenTonnes", "economicgrade"):
        assert forbidden.lower() not in doc.replace("resource/reserve estimate", ""), forbidden


def test_a4_production_method_disagreement_is_typed() -> None:
    with pytest.raises(AnalysisSourceInconsistentError, match="mining method"):
        build_analysis(fx.inputs(method=MiningMethodType.CUT_AND_FILL, with_timeline=False))


def test_a4_duplicate_production_ids_are_typed() -> None:
    st = fx.stopes_doc()
    st["stopes"][1]["id"] = st["stopes"][0]["id"]
    with pytest.raises(AnalysisSourceInconsistentError, match="duplicate production ids"):
        build_analysis(fx.inputs(stopes=st, with_timeline=False))


def test_a4_failed_production_is_not_available_with_its_reason() -> None:
    st = fx.stopes_doc()
    st.update({"status": "FAILED", "failureReason": "UNSUPPORTED_METHOD: reserved", "stopes": []})
    st["metrics"] = None
    prod = build_analysis(fx.inputs(stopes=st, with_timeline=False)).production
    assert prod.availability == "NOT_AVAILABLE"
    assert prod.reason is not None and "UNSUPPORTED_METHOD" in prod.reason
    assert prod.total_planned_mined_tonnes is None and prod.detail is None


# --------------------------------------------------------------------------- #
# 22A ratios / schedule / availability
# --------------------------------------------------------------------------- #


def test_a7_ratios_and_null_when_tonnes_are_zero() -> None:
    r = build_analysis(fx.inputs()).ratios
    assert r.availability == "AVAILABLE"
    assert r.development_metres_per_kt == 230.0 / 4.0
    assert r.gross_development_m3_per_kt == 4400.0 / 4.0
    st = fx.stopes_doc()
    for s in st["stopes"]:
        s["tonnes"] = 0.0
    st["metrics"]["totalTonnes"] = 0.0
    tl = fx.timeline_doc()
    for t in tl["tasks"]:
        if t["taskType"] in ("STOPING", "MUCKING"):
            t["basis"]["quantity"] = 0.0
    tl["metrics"]["totalScheduledTonnes"] = 0.0
    r = build_analysis(fx.inputs(stopes=st, timeline=tl)).ratios
    assert r.development_metres_per_kt is None and r.gross_development_m3_per_kt is None
    assert r.reason is not None and "zero" in r.reason
    r = build_analysis(fx.inputs(with_stopes=False, with_timeline=False)).ratios
    assert r.availability == "NOT_AVAILABLE" and r.reason == "requires production"


def test_a8_schedule_kpis_from_the_timeline() -> None:
    s = build_analysis(fx.inputs()).schedule
    assert s.availability == "AVAILABLE"
    assert (s.task_count, s.development_task_count, s.production_task_count) == (15, 5, 10)
    assert (s.start_day, s.end_day, s.mine_duration_days) == (0.0, 120.0, 120.0)
    assert s.ramp_completion_day == 30.0
    assert s.first_production_day == 50.0  # min STOPING start, generic


def test_a8_first_production_cross_check_and_timeline_targets() -> None:
    tl = fx.timeline_doc()
    tl["metrics"]["firstStopingDay"] = 49.0
    with pytest.raises(AnalysisSourceInconsistentError, match="firstStopingDay"):
        build_analysis(fx.inputs(timeline=tl))
    tl = fx.timeline_doc()
    tl["tasks"][0]["targetId"] = "RAMP:404"
    with pytest.raises(AnalysisSourceInconsistentError, match="unknown network edge"):
        build_analysis(fx.inputs(timeline=tl))
    tl = fx.timeline_doc()
    tl["tasks"][-1]["targetId"] = "STOPE:Z"
    with pytest.raises(AnalysisSourceInconsistentError, match="unknown production object"):
        build_analysis(fx.inputs(timeline=tl))
    tl = fx.timeline_doc()
    tl["tasks"][0]["basis"]["quantity"] = 99.0
    with pytest.raises(AnalysisSourceInconsistentError, match="edge length3d"):
        build_analysis(fx.inputs(timeline=tl))
    tl = fx.timeline_doc()
    stoping = next(t for t in tl["tasks"] if t["taskType"] == "STOPING")
    stoping["basis"]["quantity"] += 1.0
    with pytest.raises(AnalysisSourceInconsistentError, match="production tonnes"):
        build_analysis(fx.inputs(timeline=tl))
    tl = fx.timeline_doc()
    tl["tasks"] = [t for t in tl["tasks"] if t["id"] != "TASK:MUCKING:STOPE:B"]
    for t in tl["tasks"]:
        t["dependencies"] = [d for d in t["dependencies"] if d != "TASK:MUCKING:STOPE:B"]
    tl["metrics"]["taskCount"] -= 1
    with pytest.raises(AnalysisSourceInconsistentError, match="no MUCKING task"):
        build_analysis(fx.inputs(timeline=tl))
    tl = fx.timeline_doc()
    tl["tasks"][3]["dependencies"] = ["TASK:NOPE"]
    with pytest.raises(AnalysisSourceInconsistentError, match="unknown task"):
        build_analysis(fx.inputs(timeline=tl))


def test_a8_timeline_without_its_owners_is_inconsistent_not_partial() -> None:
    with pytest.raises(AnalysisSourceInconsistentError, match=r"network\.json is absent"):
        build_analysis(fx.inputs(with_network=False))
    with pytest.raises(AnalysisSourceInconsistentError, match=r"stopes\.json is absent"):
        build_analysis(fx.inputs(with_stopes=False))


def test_a9_missing_sources_are_a_partial_analysis() -> None:
    p = build_analysis(fx.inputs_without_config(with_stopes=False, with_timeline=False))
    assert p.status == "SUCCESS"
    assert p.development.availability == "AVAILABLE"
    assert p.production.availability == "NOT_AVAILABLE"
    assert p.production.reason == "stopes.json not generated"
    assert p.schedule.availability == "NOT_AVAILABLE"
    assert p.schedule.reason == "timeline.json not generated"
    assert p.ratios.availability == "NOT_AVAILABLE"
    assert p.economics.availability == "NOT_CONFIGURED"
    assert p.economics.reason == "Planning economics is not configured."
    assert p.sources.production_revision is None and p.sources.economics_revision is None
    # no world: every derived section is NOT_AVAILABLE, nothing is refused
    p = build_analysis(fx.inputs(world_generated=False))
    assert {s.availability for s in (p.development, p.production, p.schedule)} == {"NOT_AVAILABLE"}
    assert p.economics.availability == "NOT_AVAILABLE"
    assert p.economics.reason is not None and p.economics.reason.startswith("SOURCE_NOT_AVAILABLE")


def test_a11_determinism_same_inputs_same_json() -> None:
    a = json.dumps(_dump(build_analysis(fx.inputs())), sort_keys=True)
    b = json.dumps(_dump(build_analysis(fx.inputs())), sort_keys=True)
    assert a == b
    assert "timestamp" not in a.lower() and "generatedAt" not in a


# --------------------------------------------------------------------------- #
# 22B economics config
# --------------------------------------------------------------------------- #


def test_b2_config_revision_is_deterministic_and_content_only() -> None:
    a = EconomicsConfig.model_validate(fx.config_doc())
    b = EconomicsConfig.model_validate(dict(reversed(list(fx.config_doc().items()))))
    assert config_revision(a) == config_revision(b) and len(config_revision(a)) == 64
    assert canonical_json(a) == canonical_json(b)
    c = fx.config_doc()
    c["grossRevenuePerMinedTonne"] = 6.0
    assert config_revision(EconomicsConfig.model_validate(c)) != config_revision(a)


@pytest.mark.parametrize(
    "mutation",
    [
        {"currencyCode": "usd"},
        {"currencyCode": "US"},
        {"currencyCode": "USDT"},
        {"processingCostPerTonne": -1.0},
        {"processingCostPerTonne": float("nan")},
        {"initialCapitalCost": float("inf")},
        {"cashflowBucketDays": 0.0},
        {"annualDiscountRate": -0.1},
        {"version": 2},
        {"metalPrice": 1000.0},
    ],
)
def test_b3_b4_invalid_config_is_rejected(mutation: dict[str, Any]) -> None:
    doc = fx.config_doc()
    doc.update(mutation)
    with pytest.raises(ValueError):
        EconomicsConfig.model_validate(doc)


# --------------------------------------------------------------------------- #
# 22B costs, cashflow and NPV (hand-calculated)
# --------------------------------------------------------------------------- #

DEV_COST = 150 * 10.0 + 30 * 8.0 + 40 * 6.0 + 10 * 5.0  # 2 030
MINING = 4000 * 2.0  # 8 000
PROCESSING = 4000 * 1.0  # 4 000
FIXED = 120 * 10.0  # 1 200
CAPEX = 500.0
REVENUE = 4000 * 5.0  # 20 000
#: per 30-day bucket, from the task windows in ``analysis_support``
EXPECTED_BUCKETS = [
    # dev, mining, processing, fixed, capex, revenue
    (1000.0 + 500.0 + 240.0, 0.0, 0.0, 300.0, 500.0, 0.0),
    (240.0 + 50.0, 2000.0, 0.0, 300.0, 0.0, 0.0),
    (0.0, 6000.0, 1000.0, 300.0, 0.0, 5000.0),
    (0.0, 0.0, 3000.0, 300.0, 0.0, 15000.0),
]


def test_b6_b10_cost_summary_and_reconciliation() -> None:
    e = build_analysis(fx.inputs()).economics
    assert e.availability == "AVAILABLE" and e.summary is not None
    s = e.summary
    assert s.development_cost == DEV_COST
    assert s.production_mining_cost == MINING  # the ACTIVE method's rate (2/t), not 3 or 4
    assert s.processing_cost == PROCESSING
    assert s.backfill_cost == 0.0  # Longhole: backfill cost is Cut & Fill only
    assert s.fixed_operating_cost == FIXED
    assert s.initial_capital_cost == CAPEX
    assert s.total_cost == DEV_COST + MINING + PROCESSING + FIXED + CAPEX
    assert s.total_revenue == REVENUE
    assert s.undiscounted_net_cashflow == REVENUE - s.total_cost == 4270.0
    assert e.currency_code == "USD" and e.disclaimer == ECONOMICS_DISCLAIMER
    assert e.revenue_model == "GROSS_REVENUE_PER_MINED_TONNE"


def test_b11_overlap_allocation_is_linear_and_sums_to_one() -> None:
    assert allocate_linear(25.0, 35.0, 30.0, 4) == [(0, 0.5), (1, 0.5)]
    parts = allocate_linear(10.0, 100.0, 30.0, 4)
    assert [i for i, _ in parts] == [0, 1, 2, 3]
    assert math.isclose(sum(f for _, f in parts), 1.0)
    assert math.isclose(parts[0][1], 20 / 90) and math.isclose(parts[3][1], 10 / 90)
    # a point event lands in the bucket containing its day; the mine end day
    # (an exact bucket boundary) lands in the LAST bucket
    assert allocate_linear(0.0, 0.0, 30.0, 4) == [(0, 1.0)]
    assert allocate_linear(120.0, 120.0, 30.0, 4) == [(3, 1.0)]
    assert bucket_count(120.0, 30.0) == 4 and bucket_count(121.0, 30.0) == 5
    assert bucket_count(0.0, 30.0) == 1


def test_b12_b16_bucket_timing_fixed_opex_and_capex() -> None:
    e = build_analysis(fx.inputs()).economics
    assert [b.index for b in e.cashflow] == [0, 1, 2, 3]
    assert [(b.start_day, b.end_day) for b in e.cashflow] == [
        (0, 30),
        (30, 60),
        (60, 90),
        (90, 120),
    ]
    for b, (dev, mining, processing, fixed, capex, revenue) in zip(
        e.cashflow, EXPECTED_BUCKETS, strict=True
    ):
        assert math.isclose(b.development_cost, dev), b.index
        assert math.isclose(b.production_mining_cost, mining), b.index
        assert math.isclose(b.processing_cost, processing), b.index
        assert math.isclose(b.fixed_operating_cost, fixed), b.index
        assert b.initial_capital_cost == capex, b.index
        assert math.isclose(b.revenue, revenue), b.index
        assert b.backfill_cost == 0.0


def test_b17_b18_per_category_reconciliation_and_cumulative() -> None:
    e = build_analysis(fx.inputs()).economics
    assert e.summary is not None
    s = e.summary
    tol = 1e-9
    assert abs(math.fsum(b.development_cost for b in e.cashflow) - s.development_cost) < tol
    assert (
        abs(math.fsum(b.production_mining_cost for b in e.cashflow) - s.production_mining_cost)
        < tol
    )
    assert abs(math.fsum(b.processing_cost for b in e.cashflow) - s.processing_cost) < tol
    assert abs(math.fsum(b.backfill_cost for b in e.cashflow) - s.backfill_cost) < tol
    assert abs(math.fsum(b.fixed_operating_cost for b in e.cashflow) - s.fixed_operating_cost) < tol
    assert abs(math.fsum(b.initial_capital_cost for b in e.cashflow) - s.initial_capital_cost) < tol
    assert abs(math.fsum(b.revenue for b in e.cashflow) - s.total_revenue) < tol
    running = 0.0
    for b in e.cashflow:
        cost = math.fsum(
            [
                b.development_cost,
                b.production_mining_cost,
                b.processing_cost,
                b.backfill_cost,
                b.fixed_operating_cost,
                b.initial_capital_cost,
            ]
        )
        assert math.isclose(b.net_cashflow, b.revenue - cost)
        running += b.net_cashflow
        assert math.isclose(b.cumulative_cashflow, running)
    assert math.isclose(e.cashflow[-1].cumulative_cashflow, s.undiscounted_net_cashflow)
    assert [round(b.net_cashflow, 9) for b in e.cashflow] == [-2540.0, -2590.0, -2300.0, 11700.0]


def test_b19_npv_matches_the_hand_calculated_midpoint_convention() -> None:
    e = build_analysis(fx.inputs()).economics
    assert e.summary is not None
    nets = [-2540.0, -2590.0, -2300.0, 11700.0]
    mids = [15.0, 45.0, 75.0, 105.0]
    expected = sum(n / (1.1 ** (m / DAYS_PER_YEAR)) for n, m in zip(nets, mids, strict=True))
    assert math.isclose(e.summary.npv, expected, rel_tol=1e-12)
    for b, n, m in zip(e.cashflow, nets, mids, strict=True):
        assert math.isclose(b.discounted_net_cashflow, n / (1.1 ** (m / DAYS_PER_YEAR)))
    assert e.npv_convention == "MID_BUCKET_MIDPOINT"


def test_b20_zero_rate_npv_equals_undiscounted() -> None:
    cfg = fx.config_doc()
    cfg["annualDiscountRate"] = 0.0
    e = build_analysis(fx.inputs(config=cfg)).economics
    assert e.summary is not None
    assert math.isclose(e.summary.npv, e.summary.undiscounted_net_cashflow, rel_tol=1e-12)


def test_b_economics_requires_every_source_and_never_npv_without_timeline() -> None:
    e = build_analysis(fx.inputs(with_timeline=False)).economics
    assert e.availability == "NOT_AVAILABLE"
    assert e.reason == "SOURCE_NOT_AVAILABLE: requires schedule"
    assert e.summary is None and e.cashflow == []
    assert e.currency_code == "USD"  # the config itself is echoed
    e = build_analysis(fx.inputs_without_config()).economics
    assert e.availability == "NOT_CONFIGURED" and e.summary is None
