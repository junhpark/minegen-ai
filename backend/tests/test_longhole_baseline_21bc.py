"""Phase 21B/C Longhole regression gate (directive §39, §52).

The Longhole path — levels, stopes, MineNetwork, MineTimeline — must be
unchanged by the multi-method migration. The baseline was captured ONCE on
the pinned pre-migration HEAD (PR #46 merge commit) by
``scripts/phase21bc_capture_baseline.py`` and is never regenerated for this
Phase; the two-tier comparator of Phase 21A judges every case (HARD exact,
NUMERIC 1e-10, digests advisory). A difference is BLOCKING and is reported,
never absorbed.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from minegen.core.models import Scenario, ScenarioCreate
from minegen.layout.search import LayoutSearchResult, LayoutV2Search
from minegen.world.synthetic_world import SyntheticWorld, generate_world
from tests.conftest import small_scenario
from tests.phase21a_parity_support import (
    PARITY_ABS_TOL,
    PARITY_REL_TOL,
    legacy_chain,
    parity_differences,
    reduce,
)
from tests.phase21bc_baseline_support import (
    layout_full_chain,
    legacy_welded_chain,
    reduce_full,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "phase21bc" / "longhole_baseline.json"
#: PR #46 merge commit — the pre-migration main this baseline was captured on
PRE_MIGRATION_HEAD = "70526063e3a61cda41af283ac7fa578ba0805d77"
SECTIONS = ("levels", "stopes", "network", "timeline")


@pytest.fixture(scope="module")
def baseline() -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert doc["metadata"]["phase"] == "21B/C pre-migration"
    assert doc["metadata"]["capturedAtHead"] == PRE_MIGRATION_HEAD, (
        "the 21B/C longhole baseline must stay the one captured on the pre-migration "
        f"HEAD {PRE_MIGRATION_HEAD}; re-capturing it is never an implicit step"
    )
    return doc["cases"]


@pytest.fixture(scope="module")
def default_world() -> tuple[Scenario, SyntheticWorld]:
    sc = Scenario(**ScenarioCreate(name="phase21bc-default").model_dump())
    return sc, generate_world(sc)


def _assert_case(
    expected: dict[str, Any],
    actual: dict[str, Any],
    name: str,
    record_property: Callable[[str, object], None],
) -> None:
    assert set(expected) == set(actual), f"{name}: captured sections differ"
    assert actual.get("winnerId") == expected.get("winnerId"), f"{name}: layout winner changed"
    diffs = [
        line
        for section in SECTIONS
        if section in expected
        for line in parity_differences(expected[section], actual[section], section)
    ]
    assert not diffs, (
        f"{name}: Longhole baseline BROKEN (rel {PARITY_REL_TOL:g} / abs {PARITY_ABS_TOL:g}) — "
        f"{len(diffs)} difference(s):\n  " + "\n  ".join(diffs[:40])
    )
    for section in SECTIONS:
        key = f"{section}Digest"
        if key in expected:
            identical = actual[key] == expected[key]
            record_property(f"{name}.{key}.byteIdentical", identical)
            if not identical:
                print(
                    f"[baseline advisory] {name}: {key} differs while the two-tier gate "
                    "passes — floating-point last-digit noise, not a Longhole change"
                )


def test_legacy_default_levels_and_stopes_are_unchanged(
    baseline: dict[str, Any],
    default_world: tuple[Scenario, SyntheticWorld],
    record_property: Callable[[str, object], None],
) -> None:
    sc, world = default_world
    actual = reduce(legacy_chain(sc, world, (60.0, 35.0, 10.0)))
    assert actual["stopes"]["status"] == "SUCCESS"
    _assert_case(baseline["LEGACY_DEFAULT"], actual, "LEGACY_DEFAULT", record_property)


def test_legacy_welded_chain_through_the_timeline_is_unchanged(
    baseline: dict[str, Any],
    default_world: tuple[Scenario, SyntheticWorld],
    record_property: Callable[[str, object], None],
) -> None:
    sc, world = default_world
    actual = reduce_full(legacy_welded_chain(sc, world, [(25.0, 60.0), (25.0, 35.0), (25.0, 10.0)]))
    assert actual["timeline"]["status"] == "SUCCESS"
    assert actual["network"]["status"] == "SUCCESS"
    _assert_case(baseline["LEGACY_WELDED"], actual, "LEGACY_WELDED", record_property)


def test_layout_chain_through_the_timeline_is_unchanged(
    baseline: dict[str, Any], record_property: Callable[[str, object], None]
) -> None:
    sc = small_scenario()
    actual = reduce_full(layout_full_chain(sc, generate_world(sc)))
    assert actual["timeline"]["status"] == "SUCCESS"
    _assert_case(baseline["LAYOUT_SMALL"], actual, "LAYOUT_SMALL", record_property)


def test_warped_longhole_levels_and_typed_boundary_are_unchanged(
    baseline: dict[str, Any],
    warped_301: tuple[Scenario, SyntheticWorld],
    warped_301_search: tuple[LayoutV2Search, LayoutSearchResult],
    record_property: Callable[[str, object], None],
) -> None:
    sc, world = warped_301
    actual = reduce_full(layout_full_chain(sc, world))
    assert actual["stopes"]["typedBoundary"] == "ExactDistanceRequiredError"
    _assert_case(baseline["WARPED_LONGHOLE"], actual, "WARPED_LONGHOLE", record_property)
