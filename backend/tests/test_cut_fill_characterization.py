"""H2-CF Cut & Fill schedule characterization (hardening PR-2, C2).

``tests/fixtures/h2cf/cut_fill_characterization_after.json`` records the
Cut & Fill chain of the small scenario under the H2-CF block / panel
structure (captured by ``scripts/h2cf_capture_cut_fill_characterization.py``
on the PR-2 branch); ``…_before.json`` records the SAME chain on the PR-2
baseline (main ``1bd68c8``) and is the documented comparison input
(``docs/findings/h2cf-cut-fill-characterization.md``), never a gate. The
``after`` record is a refactor net for the schedule: counts, task ids,
dependency graph, concurrency and cure durations are HARD (exact); days are
NUMERIC (1e-9).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from minegen.core.enums import MiningMethodType
from minegen.world.synthetic_world import generate_world
from tests.conftest import small_scenario
from tests.phase21a_parity_support import with_method
from tests.phase21bc_baseline_support import layout_full_chain

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "h2cf"
AFTER = FIXTURES / "cut_fill_characterization_after.json"
BEFORE = FIXTURES / "cut_fill_characterization_before.json"
NUMERIC_KEYS = {"rampCompletionDay", "firstStopingDay", "endDay"}


def _characterize(case: dict[str, Any]) -> dict[str, Any]:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "h2cf_capture",
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "h2cf_capture_cut_fill_characterization.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.characterize(case)  # type: ignore[no-any-return]


@pytest.fixture(scope="module")
def current() -> dict[str, Any]:
    sc = with_method(small_scenario(), MiningMethodType.CUT_AND_FILL)
    return _characterize(layout_full_chain(sc, generate_world(sc)))


def _compare(expected: Any, actual: Any, path: str, out: list[str]) -> None:
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(expected) != set(actual):
            got = sorted(actual) if isinstance(actual, dict) else actual
            out.append(f"{path}: keys {sorted(expected)} vs {got}")
            return
        for k in expected:
            _compare(expected[k], actual[k], f"{path}.{k}", out)
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            out.append(f"{path}: {expected!r} vs {actual!r}")
            return
        for i, (e, a) in enumerate(zip(expected, actual, strict=True)):
            _compare(e, a, f"{path}[{i}]", out)
    elif (
        isinstance(expected, float)
        and not isinstance(expected, bool)
        and path.rsplit(".", 1)[-1] in NUMERIC_KEYS
    ):
        if not (
            isinstance(actual, (int, float))
            and math.isclose(expected, actual, rel_tol=1e-9, abs_tol=1e-9)
        ):
            out.append(f"{path}: {expected!r} vs {actual!r}")
    elif expected != actual:
        out.append(f"{path}: {expected!r} vs {actual!r}")


def test_after_record_matches_the_current_schedule(current: dict[str, Any]) -> None:
    expected = json.loads(AFTER.read_text(encoding="utf-8"))
    for meta in ("label", "generatedFromGitSha"):
        expected.pop(meta, None)
    diffs: list[str] = []
    _compare(expected, current, "$", diffs)
    assert not diffs, "\n".join(diffs)


def test_before_record_documents_the_superseded_single_chain() -> None:
    """The before record is read-only evidence: the pre-H2-CF schedule was
    ONE global chain (every PREP after the previous CURE, one cut at a time,
    production only after the ramp reached the bottom)."""
    before = json.loads(BEFORE.read_text(encoding="utf-8"))
    after = json.loads(AFTER.read_text(encoding="utf-8"))
    assert before["generatedFromGitSha"].startswith("1bd68c8")
    assert before["timeline"]["maxConcurrentCuts"] == 1
    assert before["timeline"]["maxConcurrentPanels"] is None
    assert before["production"]["panelCount"] == 0 and before["production"]["blockCount"] == 0
    assert before["timeline"]["firstStopingDay"] >= before["timeline"]["rampCompletionDay"]
    assert after["timeline"]["maxConcurrentPanels"] == 2
    assert after["timeline"]["firstStopingDay"] < after["timeline"]["rampCompletionDay"]
    assert after["production"]["cementedBackfillCount"] > 0
    assert after["timeline"]["cureDurations"] == [7.0, 28.0]
    # the ore mined is the same body: identical total volume / tonnes
    assert math.isclose(
        before["production"]["totalGeometricVolumeM3"],
        after["production"]["totalGeometricVolumeM3"],
        rel_tol=1e-9,
    )
    assert math.isclose(
        before["production"]["totalTonnes"], after["production"]["totalTonnes"], rel_tol=1e-9
    )
