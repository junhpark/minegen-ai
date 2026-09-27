"""Phase 21B/C Longhole regression gate (directive §39, §52).

The Longhole path — levels, stopes, MineNetwork, MineTimeline — must be
unchanged by the multi-method migration. The baseline was captured ONCE on
the pinned pre-migration HEAD (PR #46 merge commit) by
``scripts/phase21bc_capture_baseline.py`` and is never regenerated for this
Phase; the two-tier comparator of Phase 21A judges every case (HARD exact,
NUMERIC 1e-10, digests advisory). A difference is BLOCKING and is reported,
never absorbed.

ONE documented cross-runner artefact is classified, never absorbed silently
(PR #47 CI, measured): a sampled polyline carries ``ceil(length / 2 m) + 1``
points, so a piece whose length sits WITHIN FLOAT NOISE of an exact 2 m
multiple (LEGACY_WELDED ``DRIFT:L01:09``: 10.00000000000001 m on the capture
machine → 7 points, 10.0 m on the CI CPU → 6 points; the difference is the
last digit of one ``np.dot`` / ``np.linalg.norm``) flips its integer count by
exactly one between CPUs. Such a ``pointCount`` / ``fractionCount`` diff is
accepted ONLY when |Δ| == 1, both counts are the two sides of that boundary
and the piece's ``length3d / SAMPLE_SPACING`` is within 1e-9 of an integer;
it is recorded as a property and printed. Every other difference stays
BLOCKING and the production sampler is untouched.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from minegen.core.models import Scenario, ScenarioCreate
from minegen.layout.search import LayoutSearchResult, LayoutV2Search
from minegen.levels.builder import SAMPLE_SPACING
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
#: a sampled-count difference the comparator may classify as a cross-runner
#: sampling-boundary artefact (see the module docstring)
_COUNT_DIFF = re.compile(
    r"^(?:levels\.stations\[(?P<station>\d+)\]\.pointCount"
    r"|timeline\.developments\[(?P<development>\d+)\]\.fractionCount): "
    r"(?P<expected>\d+) != (?P<actual>\d+)$"
)
SAMPLING_BOUNDARY_TOL = 1e-9


def _piece_length(expected: dict[str, Any], match: re.Match[str]) -> float | None:
    """The authoritative length of the sampled piece a count diff names: a
    levels station's own ``length3d``, or — for a timeline development — the
    levels station / network edge carrying that ``edgeId``."""
    stations = expected.get("levels", {}).get("stations", [])
    if match.group("station") is not None:
        i = int(match.group("station"))
        return float(stations[i]["length3d"]) if i < len(stations) else None
    j = int(match.group("development"))
    developments = expected.get("timeline", {}).get("developments", [])
    if j >= len(developments):
        return None
    edge_id = developments[j]["edgeId"]
    for st in stations:
        if st.get("id") == edge_id:
            return float(st["length3d"])
    for e in expected.get("network", {}).get("edges", []):
        if e.get("id") == edge_id:
            return float(e["length3d"])
    return None


def sampling_boundary_artefacts(
    expected: dict[str, Any], diffs: list[str]
) -> tuple[list[str], list[str]]:
    """Split the comparator's differences into (blocking, artefacts). A
    difference is an artefact ONLY when it is a sampled point / fraction
    count, |Δ| == 1, the piece's ``length3d / SAMPLE_SPACING`` is within
    ``SAMPLING_BOUNDARY_TOL`` of an integer ``m`` and the two counts are
    exactly ``m + 1`` and ``m + 2`` (the two sides of the ``ceil``
    boundary). Nothing else is ever reclassified."""
    blocking: list[str] = []
    artefacts: list[str] = []
    for line in diffs:
        m = _COUNT_DIFF.match(line)
        if m is None:
            blocking.append(line)
            continue
        exp, act = int(m.group("expected")), int(m.group("actual"))
        length = _piece_length(expected, m)
        if length is None or abs(exp - act) != 1:
            blocking.append(line)
            continue
        ratio = length / SAMPLE_SPACING
        boundary = round(ratio)
        if abs(ratio - boundary) > SAMPLING_BOUNDARY_TOL or {exp, act} != {
            boundary + 1,
            boundary + 2,
        }:
            blocking.append(line)
            continue
        artefacts.append(f"{line} (length {length!r} m = {ratio!r} x {SAMPLE_SPACING:g} m)")
    return blocking, artefacts


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
    raw = [
        line
        for section in SECTIONS
        if section in expected
        for line in parity_differences(expected[section], actual[section], section)
    ]
    diffs, artefacts = sampling_boundary_artefacts(expected, raw)
    record_property(f"{name}.samplingBoundaryArtefacts", artefacts)
    for line in artefacts:
        print(
            f"[baseline advisory] {name}: cross-runner sampling-boundary artefact — {line}; "
            "the Longhole geometry is unchanged, one float last digit moved a ceil()"
        )
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


def test_sampling_boundary_classifier_accepts_only_the_measured_artefact(
    baseline: dict[str, Any],
) -> None:
    """The PR #47 CI case (DRIFT:L01:09, 10.00000000000001 m → 7 vs 6 points)
    is an artefact; a two-point change, a non-boundary length or any other
    field stays BLOCKING."""
    expected = baseline["LEGACY_WELDED"]
    stations = expected["levels"]["stations"]
    i = next(k for k, st in enumerate(stations) if st["id"] == "DRIFT:L01:09")
    assert stations[i]["pointCount"] == 7 and abs(stations[i]["length3d"] - 10.0) < 1e-9
    j = next(
        k
        for k, d in enumerate(expected["timeline"]["developments"])
        if d["edgeId"] == "DRIFT:L01:09"
    )
    ci = [
        f"levels.stations[{i}].pointCount: 7 != 6",
        f"timeline.developments[{j}].fractionCount: 7 != 6",
    ]
    blocking, artefacts = sampling_boundary_artefacts(expected, ci)
    assert blocking == [] and len(artefacts) == 2
    # never more than one point, never the wrong side of the boundary
    blocking, artefacts = sampling_boundary_artefacts(
        expected, [f"levels.stations[{i}].pointCount: 7 != 5"]
    )
    assert artefacts == [] and len(blocking) == 1
    blocking, _ = sampling_boundary_artefacts(
        expected, [f"levels.stations[{i}].pointCount: 7 != 8"]
    )
    assert len(blocking) == 1
    # a piece whose length is not at a sampling boundary is never reclassified
    k = next(
        k
        for k, st in enumerate(stations)
        if abs(st["length3d"] / SAMPLE_SPACING - round(st["length3d"] / SAMPLE_SPACING)) > 1e-3
    )
    c = stations[k]["pointCount"]
    blocking, _ = sampling_boundary_artefacts(
        expected, [f"levels.stations[{k}].pointCount: {c} != {c - 1}"]
    )
    assert len(blocking) == 1
    # any other field is untouched by the classifier
    blocking, _ = sampling_boundary_artefacts(expected, ["levels.stations[0].valid: True != False"])
    assert len(blocking) == 1
