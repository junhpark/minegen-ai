"""Phase 19 WARPED_VEIN world-only geometry suite — SMOKE subset pinned
against the committed baseline (HARD CONTRACT only; metrics are reported by
the explicit command ``python -m minegen.regression warped-vein``)."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from minegen.regression.warped_vein import (
    SMOKE_SEEDS,
    WarpedVeinCase,
    load_report,
    run_case,
)

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden"
BASELINE = GOLDEN_DIR / "phase19_warped_vein.json"


def test_warped_vein_baseline_is_committed() -> None:
    report = load_report(BASELINE)
    assert report["caseCount"] == len(report["cases"]) >= 10
    assert all(c["contract"]["realized"] for c in report["cases"])
    assert all(c["contract"]["meshWatertight"] for c in report["cases"])
    assert all(c["contract"]["planformConnectedComponents"] == 1 for c in report["cases"])
    assert "reserve" not in report["semantics"].split("never")[0]


@pytest.mark.parametrize("seed", SMOKE_SEEDS)
def test_warped_vein_smoke_contract_matches_baseline(seed: int) -> None:
    baseline = {c["key"]: c for c in load_report(BASELINE)["cases"]}
    record = run_case(WarpedVeinCase(seed))
    assert record["contract"] == baseline[record["key"]]["contract"], record["notes"]
    base_metrics = baseline[record["key"]]["metrics"]
    for name in ("volumeM3", "minInteriorThickness", "maxInteriorThickness", "midSurfaceRange"):
        assert math.isclose(record["metrics"][name], base_metrics[name], rel_tol=1e-9), name
