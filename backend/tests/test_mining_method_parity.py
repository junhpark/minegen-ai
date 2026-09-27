"""Phase 21A — Longhole parity gate (directive §14 / §15 / §39 / §40).

The committed fixture ``tests/fixtures/phase21a/longhole_parity.json`` was
captured by ``scripts/phase21a_capture_parity.py`` on the PRE-migration
code (its ``metadata.capturedAtHead``). The migrated code rebuilds the same
four cases and must reproduce them: canonical-JSON digests of the whole
``levels.json`` / ``stopes.json`` payloads (byte-identical contract) and,
so a difference is readable, the structural summaries.

Never regenerate the fixture to make this pass (§14): a Longhole change is
BLOCKING and is reported, not absorbed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from minegen.core.enums import MiningMethodType
from minegen.core.models import Scenario, ScenarioCreate
from minegen.layout.search import LayoutSearchResult, LayoutV2Search
from minegen.world.synthetic_world import SyntheticWorld, generate_world
from tests.conftest import small_scenario
from tests.phase21a_parity_support import layout_chain, legacy_chain, reduce, with_method

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "phase21a" / "longhole_parity.json"


@pytest.fixture(scope="module")
def baseline() -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert doc["metadata"]["phase"] == "21A pre-migration"
    return doc["cases"]


@pytest.fixture(scope="module")
def small() -> tuple[Scenario, SyntheticWorld]:
    sc = small_scenario()
    return sc, generate_world(sc)


def _assert_case(expected: dict[str, Any], actual: dict[str, Any], name: str) -> None:
    # readable structure first, then the byte-identical contract
    assert actual["levels"] == expected["levels"], f"{name}: levels summary changed"
    assert actual.get("stopes") == expected.get("stopes"), f"{name}: stopes summary changed"
    assert actual.get("winnerId") == expected.get("winnerId"), name
    assert actual["levelsDigest"] == expected["levelsDigest"], f"{name}: levels.json bytes changed"
    assert actual["stopesDigest"] == expected["stopesDigest"], f"{name}: stopes.json bytes changed"


def test_tabular_legacy_chain_is_unchanged(baseline: dict[str, Any]) -> None:
    sc = Scenario(**ScenarioCreate(name="phase21a-default").model_dump())
    actual = reduce(legacy_chain(sc, generate_world(sc), (60.0, 35.0, 10.0)))
    assert actual["levels"]["productionDevelopment"]["status"] == "IMPLEMENTED"
    assert actual["stopes"]["status"] == "SUCCESS"
    _assert_case(baseline["TABULAR_LEGACY"], actual, "TABULAR_LEGACY")


def test_tabular_layout_chain_is_unchanged(
    baseline: dict[str, Any], small: tuple[Scenario, SyntheticWorld]
) -> None:
    sc, world = small
    actual = reduce(layout_chain(sc, world))
    assert actual["levels"]["entrySource"] == "LEVEL_ACCESS"
    assert actual["levels"]["productionDevelopment"]["status"] == "IMPLEMENTED"
    assert actual["stopes"]["status"] == "SUCCESS"
    _assert_case(baseline["TABULAR_LAYOUT"], actual, "TABULAR_LAYOUT")


def test_cut_and_fill_boundary_is_unchanged(
    baseline: dict[str, Any], small: tuple[Scenario, SyntheticWorld]
) -> None:
    sc, world = small
    actual = reduce(layout_chain(with_method(sc, MiningMethodType.CUT_AND_FILL), world))
    levels = actual["levels"]
    assert levels["status"] == "SUCCESS"
    assert levels["productionDevelopment"]["status"] == "UNSUPPORTED_METHOD"
    assert levels["metrics"]["crosscutCount"] == 0 and levels["metrics"]["stationsPerLevel"] == 0
    assert all(d["id"].startswith("DRIFT:") for d in levels["stations"])
    assert actual["stopes"]["status"] == "FAILED"
    assert actual["stopes"]["failureReason"].startswith("UNSUPPORTED_METHOD")
    assert actual["stopes"]["stopes"] == []
    _assert_case(baseline["CUT_AND_FILL"], actual, "CUT_AND_FILL")


def test_warped_longhole_levels_are_unchanged_and_the_stope_boundary_stays_typed(
    baseline: dict[str, Any],
    warped_301: tuple[Scenario, SyntheticWorld],
    warped_301_search: tuple[LayoutV2Search, LayoutSearchResult],
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
    _assert_case(baseline["WARPED_LONGHOLE"], actual, "WARPED_LONGHOLE")
