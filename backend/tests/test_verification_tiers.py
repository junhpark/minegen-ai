"""VA-01 §14–16: the verification-tier coverage invariants, pinned as a test.

collected(FULL) == collected(unfiltered pytest)
excludedFromFast ⊆ FULL and FAST ∪ excludedFromFast == FULL, FAST ∩ excluded = ∅

The tier expressions are owned by scripts/verify.py (single source of truth);
this test loads that module by path and runs the same collection the runner
uses. Marked slow (three collect-only passes ≈ 20–30 s), so FULL always
runs it and FAST is not taxed by it.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VERIFY = ROOT / "scripts" / "verify.py"

pytestmark = pytest.mark.slow


def _load_verify():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("verify", VERIFY)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_full_collects_the_entire_test_universe_and_fast_exclusions_are_in_full() -> None:
    verify = _load_verify()
    report = verify.collection_coverage(ROOT / "backend")
    assert report["missingFromFull"] == [], report["missingFromFull"]
    assert report["unexpectedInFull"] == [], report["unexpectedInFull"]
    assert report["excludedNotInFull"] == [], report["excludedNotInFull"]
    assert report["fastAndExcludedOverlap"] == [], report["fastAndExcludedOverlap"]
    assert report["collectedAll"] == report["collectedFull"] > 0
    assert report["collectedFast"] + report["excludedFromFast"] == report["collectedFull"]
    # this test itself is excluded from FAST (slow) and present in FULL
    me = (
        "tests/test_verification_tiers.py::"
        "test_full_collects_the_entire_test_universe_and_fast_exclusions_are_in_full"
    )
    assert me in set(report["excludedFromFastIds"])
