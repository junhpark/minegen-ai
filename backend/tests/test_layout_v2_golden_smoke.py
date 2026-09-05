"""Phase 20A layout-v2 golden suite — SMOKE subset pinned against the
committed baseline (HARD CONTRACT exact; metrics within tolerance). The
full suite and its comparison are run by the explicit command
``python -m minegen.regression layout-v2``."""

from __future__ import annotations

from pathlib import Path

import pytest

from minegen.regression.layout_v2 import (
    CONTRACT_COLUMNS,
    CONTRACT_NESTED,
    METRIC_COLUMNS,
    METRIC_NESTED,
    SMOKE_KEYS,
    _close,
    case_by_key,
    load_report,
    run_case,
)

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden"
BASELINE = GOLDEN_DIR / "phase20b1_layout_v2.json"


def test_layout_v2_baseline_is_committed() -> None:
    report = load_report(BASELINE)
    assert report["caseCount"] == len(report["cases"]) >= 3
    keys = {c["key"] for c in report["cases"]}
    assert set(SMOKE_KEYS) <= keys
    by_key = {c["key"]: c for c in report["cases"]}
    # mandatory scenarios (directive §47) and their headline contracts
    assert by_key["TABULAR-REFERENCE"]["contract"]["clearanceBasis"] == "EXACT"
    assert by_key["TABULAR-REFERENCE"]["contract"]["status"] == "SUCCESS"
    assert by_key["WARPED_VEIN-301"]["contract"]["orebodyType"] == "WARPED_VEIN"
    assert by_key["WARPED_VEIN-301"]["contract"]["clearanceBasis"] == "COARSE_CONSERVATIVE"
    assert by_key["WARPED_VEIN-301"]["metrics"]["clearanceErrorBound"] > 0
    assert all(c["contract"]["candidateCount"] == 68 for c in report["cases"])
    assert "optimality" in report["semantics"]
    # Phase 20B: every winner has an explicit access branch per level (§23)
    ref = by_key["TABULAR-REFERENCE"]
    assert ref["contract"]["winnerAccessibleLevels"] == ref["contract"]["serviceableLevelCount"]
    assert ref["contract"]["winnerAccessFailures"] == {}
    assert (
        len(ref["metrics"]["winnerJunctionChainages"]) == ref["contract"]["serviceableLevelCount"]
    )
    assert ref["metrics"]["winnerTotalAccessLength"] > 0
    assert ref["contract"]["miningMethod"] == "LONGHOLE_OPEN_STOPING"
    assert by_key["ACCESS-INFEASIBLE"]["contract"]["status"] == "NO_FEASIBLE_CANDIDATE"
    assert "LEVEL_ACCESS_INFEASIBLE" in {
        r
        for rs in by_key["ACCESS-INFEASIBLE"]["contract"]["candidateFailureReasons"].values()
        for r in rs
    }
    caf = by_key["CUT_AND_FILL"]
    assert caf["contract"]["miningMethod"] == "CUT_AND_FILL"
    assert caf["contract"]["status"] == "SUCCESS"
    assert caf["contract"]["winnerAccessibleLevels"] == caf["contract"]["serviceableLevelCount"]
    # closeout v3: preferred access length recorded; the reach screen is a
    # heuristic — the irregular case has reach-exceeded levels yet SUCCESS
    assert ref["contract"]["winnerPreferredAccessSource"] == "DEFAULT_6X_TUNNEL_WIDTH"
    assert ref["metrics"]["winnerPreferredAccessLength"] == 30.0
    assert all(
        r["contract"]["cheapFeasibleCount"] >= len(r["contract"]["shortlist"])
        for r in report["cases"]
    )
    irregular = by_key["IRREGULAR-REACH-EXCEEDED"]
    assert irregular["contract"]["status"] == "SUCCESS"
    assert irregular["contract"]["winnerReachExceededLevels"]
    assert (
        irregular["contract"]["winnerAccessibleLevels"]
        == (irregular["contract"]["serviceableLevelCount"])
    )
    assert "LEVEL_SERVICE_INFEASIBLE" not in {
        r
        for cid, rs in irregular["contract"]["candidateFailureReasons"].items()
        for r in rs
        if not cid.startswith("LONGITUDINAL")
    }
    # the physically infeasible implicit body stays an explicit failure
    assert by_key["WARPED_VEIN-307"]["contract"]["status"] == "NO_FEASIBLE_CANDIDATE"


@pytest.mark.parametrize("key", SMOKE_KEYS)
def test_layout_v2_smoke_matches_baseline(key: str) -> None:
    baseline = {c["key"]: c for c in load_report(BASELINE)["cases"]}[key]
    record = run_case(case_by_key(key))
    for c in (*CONTRACT_COLUMNS, *CONTRACT_NESTED):
        assert record["contract"].get(c) == baseline["contract"].get(c), c
    for m in (*METRIC_COLUMNS, *METRIC_NESTED):
        assert _close(record["metrics"].get(m), baseline["metrics"].get(m), 1e-6, 1e-6), (
            m,
            record["metrics"].get(m),
            baseline["metrics"].get(m),
        )
