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
BASELINE = GOLDEN_DIR / "phase20a_layout_v2.json"


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
    assert by_key["WARPED_VEIN-301"]["contract"]["clearanceBasis"] == "CONSERVATIVE"
    assert by_key["WARPED_VEIN-301"]["metrics"]["clearanceErrorBound"] > 0
    assert all(c["contract"]["candidateCount"] == 68 for c in report["cases"])
    assert "optimality" in report["semantics"]


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
