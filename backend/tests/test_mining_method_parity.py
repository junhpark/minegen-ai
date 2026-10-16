"""Phase 21A — Longhole parity gate (directive §14 / §15 / §39 / §40).

The committed fixture ``tests/fixtures/phase21a/longhole_parity.json`` was
captured by ``scripts/phase21a_capture_parity.py`` on the PRE-migration
code (its ``metadata.capturedAtHead``, pinned). The migrated code rebuilds
the same four cases and must reproduce their structural summaries under the
two-tier gate of ``phase21a_parity_support.parity_differences`` — HARD
(structure, ids, counts, indices, strings, bools) exact, NUMERIC (floats)
within 1e-10 — while the whole-payload canonical-JSON digests are recorded
as an advisory property (cross-runner float noise, never a gate).

Never regenerate the fixture to make this pass (§14), and never widen the
tolerance for it: a Longhole change is BLOCKING and is reported, not absorbed.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from minegen.core.enums import MiningMethodType
from minegen.core.models import Scenario, ScenarioCreate
from minegen.layout.search import LayoutSearchResult, LayoutV2Search
from minegen.world.synthetic_world import SyntheticWorld, generate_world
from tests.conftest import small_scenario
from tests.phase21a_parity_support import (
    PARITY_ABS_TOL,
    PARITY_REL_TOL,
    layout_chain,
    legacy_chain,
    parity_differences,
    reduce,
    with_method,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "phase21a" / "longhole_parity.json"
#: the pre-migration main HEAD the baseline was captured on (PR #45 merge).
#: Pinned so the baseline can never be silently re-captured on a later HEAD
#: (PR #46 review S3): a new baseline is an explicit, reviewed decision.
PRE_MIGRATION_HEAD = "39c293e71790b6ec490275a24bb8735631334e4e"


@pytest.fixture(scope="module")
def baseline() -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert doc["metadata"]["phase"] == "21A pre-migration"
    assert doc["metadata"]["capturedAtHead"] == PRE_MIGRATION_HEAD, (
        "the longhole parity baseline must stay the one captured on the pre-migration "
        f"HEAD {PRE_MIGRATION_HEAD}; re-capturing it is never an implicit step"
    )
    return doc["cases"]


@pytest.fixture(scope="module")
def small() -> tuple[Scenario, SyntheticWorld]:
    sc = small_scenario()
    return sc, generate_world(sc)


def _assert_case(
    expected: dict[str, Any],
    actual: dict[str, Any],
    name: str,
    record_property: Callable[[str, object], None],
) -> None:
    """Two-tier parity gate (PR #46 review): HARD (structure, ids, counts,
    strings) exact + NUMERIC (floats) within the documented tolerance are
    the GATE; the full canonical-JSON digests are recorded as an ADVISORY
    observation (cross-runner last-digit float noise must never read as a
    Longhole regression, and a fixture is never regenerated for it)."""
    assert actual.get("winnerId") == expected.get("winnerId"), f"{name}: layout winner changed"
    diffs = [
        *parity_differences(expected["levels"], actual["levels"], "levels"),
        *parity_differences(expected.get("stopes"), actual.get("stopes"), "stopes"),
    ]
    assert not diffs, (
        f"{name}: Longhole parity BROKEN (rel {PARITY_REL_TOL:g} / abs {PARITY_ABS_TOL:g}) — "
        f"{len(diffs)} difference(s):\n  " + "\n  ".join(diffs[:40])
    )
    for key in ("levelsDigest", "stopesDigest"):
        identical = actual[key] == expected[key]
        record_property(f"{name}.{key}.byteIdentical", identical)
        if not identical:
            print(
                f"[parity advisory] {name}: {key} differs from the baseline while the two-tier "
                "gate passes — floating-point last-digit noise, not a Longhole change"
            )


def test_parity_gate_is_exact_on_structure_and_tolerant_on_float_noise() -> None:
    """The gate itself: ids / counts / strings / bools are HARD, floats absorb
    last-digit noise only, and a real change (moved station, different count,
    re-derived coordinate) is still reported with its path."""
    base = {
        "status": "SUCCESS",
        "metrics": {"crosscutCount": 3, "totalDriftLength3d": 1085.4613279254309},
        "stations": [{"id": "CROSSCUT:L01:S+00", "stationU": 0.0, "valid": True}],
    }
    noise = json.loads(json.dumps(base))
    noise["metrics"]["totalDriftLength3d"] = 1085.4613279254306  # the observed CI delta
    noise["stations"][0]["stationU"] = 1e-14
    assert parity_differences(base, noise) == []
    for mutate, needle in (
        (lambda d: d["metrics"].__setitem__("crosscutCount", 2), "metrics.crosscutCount"),
        (lambda d: d["stations"][0].__setitem__("id", "CROSSCUT:L01:S+01"), "stations[0].id"),
        (lambda d: d["stations"][0].__setitem__("valid", False), "stations[0].valid"),
        (lambda d: d["stations"][0].__setitem__("stationU", 1e-6), "stations[0].stationU"),
        (lambda d: d["metrics"].__setitem__("totalDriftLength3d", 1085.4614), "totalDriftLength3d"),
        (lambda d: d["stations"].append({"id": "x"}), "stations: length"),
        (lambda d: d.__setitem__("extra", 1), "unexpected keys"),
        (lambda d: d["metrics"].__setitem__("crosscutCount", 3.0), "metrics.crosscutCount"),
    ):
        doc = json.loads(json.dumps(base))
        mutate(doc)
        diffs = parity_differences(base, doc)
        assert diffs and any(needle in line for line in diffs), (needle, diffs)


def test_tabular_legacy_chain_is_unchanged(
    baseline: dict[str, Any], record_property: Callable[[str, object], None]
) -> None:
    sc = Scenario(**ScenarioCreate(name="phase21a-default").model_dump())
    actual = reduce(legacy_chain(sc, generate_world(sc), (60.0, 35.0, 10.0)))
    assert actual["levels"]["productionDevelopment"]["status"] == "IMPLEMENTED"
    assert actual["stopes"]["status"] == "SUCCESS"
    _assert_case(baseline["TABULAR_LEGACY"], actual, "TABULAR_LEGACY", record_property)


def test_tabular_layout_chain_is_unchanged(
    baseline: dict[str, Any],
    small: tuple[Scenario, SyntheticWorld],
    record_property: Callable[[str, object], None],
) -> None:
    sc, world = small
    actual = reduce(layout_chain(sc, world))
    assert actual["levels"]["entrySource"] == "LEVEL_ACCESS"
    assert actual["levels"]["productionDevelopment"]["status"] == "IMPLEMENTED"
    assert actual["stopes"]["status"] == "SUCCESS"
    _assert_case(baseline["TABULAR_LAYOUT"], actual, "TABULAR_LAYOUT", record_property)


def test_cut_and_fill_unsupported_boundary_is_superseded_by_phase_21bc(
    baseline: dict[str, Any], small: tuple[Scenario, SyntheticWorld]
) -> None:
    """RETIRED assertion (directive 21B/C §39). The Phase 21A fixture recorded
    CUT_AND_FILL as the reserved-method boundary (generic backbone,
    UNSUPPORTED_METHOD, FAILED stopes). Phase 21B implements Cut & Fill, so
    that behaviour is INTENTIONALLY superseded: the historical record stays in
    the fixture (never rewritten), the current behaviour is pinned by
    ``tests/test_cut_fill.py``, and this test documents the hand-over —
    the reserved boundary itself moved to SUBLEVEL_CAVING / SHRINKAGE_STOPING
    (``tests/test_mining_method_registry.py``)."""
    historical = baseline["CUT_AND_FILL"]
    assert historical["levels"]["productionDevelopment"]["status"] == "UNSUPPORTED_METHOD"
    assert historical["stopes"]["status"] == "FAILED"
    sc, world = small
    current = layout_chain(with_method(sc, MiningMethodType.CUT_AND_FILL), world)
    levels = current["levels"]
    assert levels["status"] == "SUCCESS"
    assert levels["productionDevelopment"]["status"] == "IMPLEMENTED"
    # H2-CF: one production access per strike panel (4 × 50 m over 200 m)
    assert levels["metrics"]["stationsPerLevel"] == 4 and levels["metrics"]["stationPitch"] == 0.0
    production = current["stopes"]  # the active production payload (CutFillPayload)
    assert production["status"] == "SUCCESS" and production["method"] == "CUT_AND_FILL"
    assert production["cuts"] and "stopes" not in production
    # the Longhole cases of the same fixture stay the live gate
    assert baseline["TABULAR_LAYOUT"]["levels"]["productionDevelopment"]["status"] == "IMPLEMENTED"


def test_warped_longhole_levels_are_unchanged_and_the_stope_boundary_stays_typed(
    baseline: dict[str, Any],
    warped_301: tuple[Scenario, SyntheticWorld],
    warped_301_search: tuple[LayoutV2Search, LayoutSearchResult],
    record_property: Callable[[str, object], None],
) -> None:
    sc, world = warped_301
    actual = reduce(layout_chain(sc, world))
    levels = actual["levels"]
    assert levels["developmentGeometry"] == "SECTION_FOOTWALL_OFFSET_TRACE"
    assert levels["productionDevelopment"]["status"] == "IMPLEMENTED"
    excluded = [e for lv in levels["levels"] for e in (lv["excludedStations"] or [])]
    assert all(e["reason"] == "NO_PERPENDICULAR_ORE_SUPPORT" for e in excluded)
    # Case B: the Longhole stope path stops at the typed Phase 09 boundary
    assert actual["stopes"]["typedBoundary"] == "ExactDistanceRequiredError"
    _assert_case(baseline["WARPED_LONGHOLE"], actual, "WARPED_LONGHOLE", record_property)
