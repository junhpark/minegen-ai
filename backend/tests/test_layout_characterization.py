"""AC-01G — layout-v2 CHARACTERIZATION FREEZE.

The safety net for the AC-01G search/stage-boundary refactor, built BEFORE
the refactor exists: the observable behaviour of ``LayoutV2Search`` on two
cases is pinned, bit for bit, against a baseline committed at the freeze SHA
``3951d98d91235facb6b95e9d646f0dc62b7c9835``.

    TABULAR-REFERENCE   EXACT clearance contract
    WARPED_VEIN-301     CONSERVATIVE clearance contract

Frozen observations (one definition, in ``tests/characterization_support``,
shared by this test and the generator so the baseline and the comparison can
never drift apart):

    C1  enumeration — ordered candidate ids, family, serialized parameters
    C2  post-cheap — status, stage, failure reasons, cheap proxy, the ramp
        level-reference summary and the geometric access screen
    C3  shortlist — the ordered shortlist and every ``shortlisted`` flag
    C4  detailed — per shortlisted candidate: status, failures, clearance,
        validation, scores, exposure, diagnostics, derived, access and the
        per-level access records (anchors included)
    C5  ranking — the ordered ranking, every rank and the winner
    C6  payload — sha256 of the wall-clock-stripped ``to_dict()`` in EMISSION
        key order, plus three views of the UNMASKED payload's key paths, so a
        key added, removed or reordered fails even where its value was
        masked: the exact ``keyPathCount``, the sha256 of the full ORDERED
        list, and the order-preserving distinct ``keyPathShape`` with list
        indices collapsed (``candidates[].scores.total``). The shape is what
        a reviewer reads — 483 entries instead of 39 577 — and it still gains
        an entry when one single row grows a key; the count and the sha keep
        multiplicity and per-row order

INPUT ROUTE (deliberate, so FULL does not pay twice):

  * WARPED_VEIN-301 reuses the session-scoped ``warped_301_search`` fixture.
    Its inputs are constructed identically to
    ``case_by_key("WARPED_VEIN-301").realize()`` (same preset, seed, fault
    count, no overrides) and the test asserts that equality cheaply, so the
    55 s clean WARPED-301 search is shared with every other consumer instead
    of being run a second time here.
  * TABULAR-REFERENCE has no shared fixture; it is built once per module
    from the same golden ``LayoutCase`` (≈ 18 s).

WALL-CLOCK HANDLING: exactly the rule ``test_layout_policy_restore.py``
already established — drop ``sourceRevision`` and every key ending in
``Seconds``, nothing else. ``test_wall_clock_mask_matches_the_established_
rule`` pins that the two definitions stay literally identical. Anything else
that differs between two clean runs is a finding to report, not something to
normalise away.

SCOPE / AUTHORITY: a characterization baseline records what the code DID, not
what it SHOULD do. A difference here is a signal that behaviour changed and
must be explained; it is never on its own proof of a defect, and it is never
resolved by regenerating the baseline (the generator refuses without
``--force``, and the freeze SHA is pinned in source).

PORTABILITY: the comparison is exact float equality on a deterministic pure
NumPy pipeline. It is a same-toolchain freeze; a different BLAS / CPU could
in principle move a last bit, which would show up as a C6 sha difference with
identical C1–C5 — that reading is part of the net, not a reason to loosen it.
"""

from __future__ import annotations

import copy
import math
from pathlib import Path
from typing import Any

import pytest

from minegen.core.models import Scenario
from minegen.layout import access
from minegen.layout.search import LayoutSearchResult, LayoutV2Search
from minegen.regression.layout_v2 import case_by_key
from minegen.world.synthetic_world import SyntheticWorld, generate_world
from tests.characterization_support import (
    BASELINE_GIT_SHA,
    CASE_KEYS,
    PLATFORM_SENSITIVE_LEAVES,
    SECTIONS,
    WALL_CLOCK_KEYS,
    canonicalize_platform_sensitive,
    key_path_shape,
    key_paths,
    load_baseline,
    observations,
)

TABULAR_KEY = "TABULAR-REFERENCE"
WARPED_KEY = "WARPED_VEIN-301"
ACCESS_INFEASIBLE_KEY = "ACCESS-INFEASIBLE"
GEOMETRY_STRESS_KEY = "GEOMETRY-STRESS"


# --------------------------------------------------------------------------- #
# inputs
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def tabular_reference() -> LayoutSearchResult:
    case = case_by_key(TABULAR_KEY)
    sc = case.realize()
    return LayoutV2Search(sc, generate_world(sc)).run()


@pytest.fixture(scope="module")
def warped_reference(
    warped_301: tuple[Scenario, SyntheticWorld],
    warped_301_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> LayoutSearchResult:
    """The shared session WARPED-301 search, with the proof that it really is
    the golden ``WARPED_VEIN-301`` case (cheap: a realize, no second search)."""
    sc, _ = warped_301
    fixture_scenario = sc.model_dump(mode="json", by_alias=True)
    case_scenario = case_by_key(WARPED_KEY).realize().model_dump(mode="json", by_alias=True)
    # the scenario id is minted per instantiation and carries no geometry
    fixture_scenario.pop("id", None)
    case_scenario.pop("id", None)
    assert fixture_scenario == case_scenario, (
        "the session warped_301 fixture no longer matches the golden WARPED_VEIN-301 case — "
        "the characterization freeze must not silently switch scenarios"
    )
    return warped_301_search[1]


@pytest.fixture(scope="module")
def access_infeasible_reference() -> LayoutSearchResult:
    """AC-01G Stage D (D4): the NO_FEASIBLE_CANDIDATE terminal branch —
    ``winnerId`` None, zero feasible candidates, and the
    ``LEVEL_ACCESS_INFEASIBLE`` problem assembly, none of which the first two
    frozen cases reach."""
    case = case_by_key(ACCESS_INFEASIBLE_KEY)
    sc = case.realize()
    return LayoutV2Search(sc, generate_world(sc)).run()


@pytest.fixture(scope="module")
def geometry_stress_reference() -> LayoutSearchResult:
    """AC-01G Stage D (D4): a SWITCHBACK winner WITH a hairpin station over a
    FamilyInfeasible-dominated population (60 CONSTRUCT / 20 CHEAP / 12
    DETAILED), against 18 / 62 / 12 in both original cases."""
    case = case_by_key(GEOMETRY_STRESS_KEY)
    sc = case.realize()
    return LayoutV2Search(sc, generate_world(sc)).run()


#: case → the fixture that produces its search result. Resolved lazily, so
#: running one case does not build the others' worlds and searches.
RESULT_FIXTURES = {
    TABULAR_KEY: "tabular_reference",
    WARPED_KEY: "warped_reference",
    ACCESS_INFEASIBLE_KEY: "access_infeasible_reference",
    GEOMETRY_STRESS_KEY: "geometry_stress_reference",
}


def _result(request: pytest.FixtureRequest, case_key: str) -> LayoutSearchResult:
    result: LayoutSearchResult = request.getfixturevalue(RESULT_FIXTURES[case_key])
    return result


# --------------------------------------------------------------------------- #
# the mask is the established one, not a new one
# --------------------------------------------------------------------------- #


def test_wall_clock_mask_matches_the_established_rule() -> None:
    from tests.test_layout_policy_restore import WALL_CLOCK_KEYS as ESTABLISHED
    from tests.test_layout_policy_restore import _strip as established_strip

    assert WALL_CLOCK_KEYS == ESTABLISHED
    probe = {
        "totalSeconds": 1.0,
        "sourceRevision": "x",
        "keep": {"detailedSeconds": 2.0, "value": 3.0, "sourceRevision": "y"},
        "list": [{"setupSeconds": 4.0, "n": 5}],
        "Seconds": 6.0,
    }
    from tests.characterization_support import strip_wall_clock

    assert strip_wall_clock(probe) == established_strip(probe)


# --------------------------------------------------------------------------- #
# C1 – C6
# --------------------------------------------------------------------------- #


def _differing_leaves(expected: Any, actual: Any, path: str = "") -> list[str]:
    """Every differing LEAF path, not just the first.

    Diagnostic only — the comparison itself is unchanged. One difference names
    a candidate; a hundred differences under ONE leaf name is the signature of
    a platform-sensitive scalar (see ``PLATFORM_SENSITIVE_LEAVES``), and
    differences under MANY names are the signature of a real behaviour change.
    Knowing which, from one failing run, is what this buys.
    """
    if isinstance(expected, dict) and isinstance(actual, dict):
        out: list[str] = []
        for k in expected:
            if k not in actual:
                out.append(f"{path}.{k} (MISSING)")
            elif expected[k] != actual[k]:
                out.extend(_differing_leaves(expected[k], actual[k], f"{path}.{k}"))
        out.extend(f"{path}.{k} (ADDED)" for k in actual if k not in expected)
        return out
    if isinstance(expected, list) and isinstance(actual, list) and len(expected) == len(actual):
        out = []
        for i, (e, a) in enumerate(zip(expected, actual, strict=True)):
            if e != a:
                out.extend(_differing_leaves(e, a, f"{path}[{i}]"))
        return out
    return [path or "<root>"]


def _leaf_name_census(paths: list[str]) -> str:
    """``count x leafName`` per distinct final path segment, largest first."""
    counts: dict[str, int] = {}
    for p in paths:
        counts[p.rsplit(".", 1)[-1]] = counts.get(p.rsplit(".", 1)[-1], 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return ", ".join(f"{n}x {name}" for name, n in ordered[:8]) + (
        f" (+{len(ordered) - 8} more names)" if len(ordered) > 8 else ""
    )


def _explain(
    case_key: str,
    section: str,
    expected: Any,
    actual: Any,
    all_differences: list[str] | None = None,
) -> str:
    census = ""
    if all_differences:
        census = (
            f"  differing leaves in this section: {len(all_differences)} — "
            f"{_leaf_name_census(all_differences)}\n"
        )
    return (
        f"LAYOUT-V2 BEHAVIOUR CHANGED — {case_key} / {section}\n"
        f"{census}"
        f"  the committed characterization baseline was generated at git SHA "
        f"{BASELINE_GIT_SHA} and records what the search DID there.\n"
        f"  expected (baseline): {_clip(expected)}\n"
        f"  actual   (this run): {_clip(actual)}\n"
        "  Do NOT regenerate the baseline to make this pass. Either the change is "
        "unintended (fix it) or it is intended (explain it in the change, then update the "
        "baseline deliberately with scripts/generate_characterization_baseline.py --force and "
        "move BASELINE_GIT_SHA in tests/characterization_support.py)."
    )


def _clip(value: Any, limit: int = 600) -> str:
    text = repr(value)
    return text if len(text) <= limit else f"{text[:limit]}… ({len(text)} chars)"


@pytest.mark.parametrize("case_key", CASE_KEYS)
def test_baseline_is_committed_and_self_consistent(case_key: str) -> None:
    """The baseline exists, is schema-valid, and its recorded content
    fingerprint matches its own body under its recorded git SHA."""
    data = load_baseline(case_key)
    meta = data["metadata"]
    assert meta["generatedFromGitSha"] == BASELINE_GIT_SHA, (
        f"CHARACTERIZATION BASELINE {case_key} was generated at "
        f"{meta['generatedFromGitSha']} but the pinned freeze SHA is {BASELINE_GIT_SHA} — a "
        "freeze baseline is regenerated only in a reviewed change that moves both."
    )
    assert data["case"]["key"] == case_key
    assert set(data["observations"]) == set(SECTIONS)
    obs = data["observations"]
    assert obs["c1Enumeration"], "C1 enumeration is empty"
    c6 = obs["c6Payload"]
    assert c6["keyPathCount"] >= len(c6["keyPathShape"]) > 0, (
        "the collapsed key-path shape must be non-empty and no longer than the full list"
    )
    assert len(c6["keyPathsSha256"]) == 64 and len(c6["sha256"]) == 64


@pytest.mark.parametrize("case_key", CASE_KEYS)
def test_search_matches_the_frozen_characterization(
    case_key: str, request: pytest.FixtureRequest
) -> None:
    """C1–C6: every frozen observation of the case, section by section."""
    baseline = load_baseline(case_key)["observations"]
    payload = _result(request, case_key).to_dict()
    actual = observations(payload)

    for section in SECTIONS:
        exp, got = baseline[section], actual[section]
        if exp == got:
            continue
        # narrow the report to the first difference so the failure names the
        # candidate / key that moved instead of dumping the whole section, and
        # add the leaf-name census so ONE failing run distinguishes a
        # platform-sensitive scalar from a real behaviour change
        pytest.fail(
            _explain(
                case_key,
                section,
                *_first_difference(exp, got),
                all_differences=_differing_leaves(exp, got),
            )
        )


def _first_difference(expected: Any, actual: Any, path: str = "") -> tuple[Any, Any]:
    """Deepest path at which two observation trees first differ, as
    ``(expected_at_path, actual_at_path)`` wrapped with that path."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        for k in expected:
            if k not in actual:
                return (f"{path}.{k} present", f"{path}.{k} MISSING")
            if expected[k] != actual[k]:
                return _first_difference(expected[k], actual[k], f"{path}.{k}")
        for k in actual:
            if k not in expected:
                return (f"{path}.{k} absent", f"{path}.{k} ADDED")
    elif isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return (f"{path}: {len(expected)} entries", f"{path}: {len(actual)} entries")
        for i, (e, a) in enumerate(zip(expected, actual, strict=True)):
            if e != a:
                return _first_difference(e, a, f"{path}[{i}]")
    return (f"{path or '<root>'} = {_clip(expected)}", f"{path or '<root>'} = {_clip(actual)}")


@pytest.mark.parametrize("case_key", CASE_KEYS)
def test_key_paths_are_recomputed_from_the_unmasked_payload(
    case_key: str, request: pytest.FixtureRequest
) -> None:
    """C6 structure: the committed key-path list is the payload's own, in
    emission order, and it still contains the masked keys (a masked VALUE is
    not an unfrozen KEY)."""
    baseline = load_baseline(case_key)["observations"]["c6Payload"]
    paths = key_paths(_result(request, case_key).to_dict())
    shape = key_path_shape(paths)
    assert shape == baseline["keyPathShape"], _explain(
        case_key,
        "c6Payload.keyPathShape",
        *_first_difference(baseline["keyPathShape"], shape),
    )
    masked = [p for p in paths if p.rsplit(".", 1)[-1].endswith("Seconds")]
    assert masked, "no *Seconds key in the payload — the mask/key-path split is untested here"


@pytest.mark.parametrize("case_key", CASE_KEYS)
def test_shortlisted_candidates_passed_the_cheap_stage_clean(
    case_key: str, request: pytest.FixtureRequest
) -> None:
    """C2, the half the published result cannot show directly.

    ``status`` / ``stageReached`` of a SHORTLISTED candidate are overwritten by
    stage 4, so the frozen C2 record holds their post-detailed values. Their
    POST-CHEAP values are nevertheless determined: the shortlist is drawn only
    from ``status == NOT_VALIDATED`` (``layout/search.py``'s stage-3 filter), which the cheap
    stage sets only on the branch where ``problems`` is empty
    (``layout/stages.py``'s clean cheap branch), and that branch is also the only one that
    runs the geometric access screen. So every shortlisted candidate WAS
    ``(CHEAP, NOT_VALIDATED, no failure reasons, screened)`` when stage 3 chose
    it. This is a derived invariant, not an observation — it is asserted here
    because a refactor that let another cheap status reach the shortlist would
    leave every frozen value unchanged."""
    payload = _result(request, case_key).to_dict()
    shortlisted = [c for c in payload["candidates"] if c["shortlisted"]]
    assert shortlisted, f"{case_key}: no shortlisted candidate to check"
    for c in shortlisted:
        assert c["stageReached"] == "DETAILED", (
            f"{case_key}/{c['candidateId']}: shortlisted but never detailed — "
            "the post-cheap derivation below no longer holds"
        )
        assert c["accessScreen"] is not None, (
            f"{case_key}/{c['candidateId']}: shortlisted without an access screen; "
            "the screen runs only on the clean cheap branch, so this candidate "
            "cannot have been NOT_VALIDATED after the cheap stage"
        )
        assert c["cheapProxy"] is not None, (
            f"{case_key}/{c['candidateId']}: shortlisted with no cheap proxy — "
            "the stage-3 ordering key would have sorted it last"
        )


# --------------------------------------------------------------------------- #
# platform sensitivity: ONE enumerated leaf, and proof the net is unchanged
# elsewhere (AC-01G correction, Park review blocker 1)
# --------------------------------------------------------------------------- #


def test_the_platform_sensitivity_registry_is_one_enumerated_measured_leaf() -> None:
    """The registry is a closed, declared list — not a policy that can grow.

    Adding an entry means editing this literal in a reviewed change, exactly
    like moving ``BASELINE_GIT_SHA``.
    """
    assert PLATFORM_SENSITIVE_LEAVES == {"localTangentVsGlobalPcaDeg": 9}

    # the two REAL values measured for this leaf on the SAME source: this
    # container (numpy 2.5.2 / CPython 3.12.3) and the GitHub runner
    # (numpy 2.5.3 / CPython 3.12.14, run 35303979826 on probe branch
    # ac-01g-probe-base-platform, which carries ZERO backend/src changes
    # against the freeze SHA — so the difference is the platform, not a
    # refactor).
    container, runner = 1.4886559404747177, 1.488655940474473
    assert container != runner, "the measured platform pair must really differ"
    assert abs(container - runner) < 1e-12, "the measured drift is 2.4e-13 deg"
    assert round(container, 9) == round(runner, 9), (
        "the declared precision must actually absorb the MEASURED drift"
    )
    # and it is still 10 orders of magnitude tighter than the only engineering
    # use of the number (tests/test_footwall_trace.py's > 25.0 threshold)
    assert 10.0 ** -PLATFORM_SENSITIVE_LEAVES["localTangentVsGlobalPcaDeg"] < 25.0 * 1e-9


def test_canonicalization_touches_only_the_enumerated_leaf() -> None:
    """Narrowness, directly: by NAME, only floats, nothing else in the tree."""
    full = 1.4886559404747177
    probe: dict[str, Any] = {
        "localTangentVsGlobalPcaDeg": full,
        "notEnumerated": full,
        "localTangentVsGlobalPcaDegSuffixed": full,
        "nested": [{"localTangentVsGlobalPcaDeg": full, "alsoNotEnumerated": full}],
        "stringValued": {"localTangentVsGlobalPcaDeg": repr(full)},
        "nullValued": {"localTangentVsGlobalPcaDeg": None},
        "intValued": {"localTangentVsGlobalPcaDeg": 3},
    }
    out = canonicalize_platform_sensitive(probe)

    assert out["localTangentVsGlobalPcaDeg"] == round(full, 9)
    assert out["nested"][0]["localTangentVsGlobalPcaDeg"] == round(full, 9)
    # every non-enumerated float survives BIT-identically — this is not a
    # blanket float rounding
    assert out["notEnumerated"] == full
    assert out["localTangentVsGlobalPcaDegSuffixed"] == full
    assert out["nested"][0]["alsoNotEnumerated"] == full
    # a non-float under the enumerated name is passed through untouched
    assert out["stringValued"]["localTangentVsGlobalPcaDeg"] == repr(full)
    assert out["nullValued"]["localTangentVsGlobalPcaDeg"] is None
    assert out["intValued"]["localTangentVsGlobalPcaDeg"] == 3
    assert isinstance(out["intValued"]["localTangentVsGlobalPcaDeg"], int)
    # a payload with NO enumerated leaf is returned unchanged
    plain = {"a": [full, {"b": full}], "c": "x"}
    assert canonicalize_platform_sensitive(plain) == plain


#: engineering leaves that must stay BIT-exact. Deliberately one per family
#: Park named: clearance, cost/validation, access geometry, score component.
_PROTECTED_LEAVES = (
    "conservativeMinimumClearance",
    "requiredClearance",
    "fieldCost",
    "length3d",
    "equivalentHalfTurns",
)


def _perturb_first_float(obj: Any, key: str) -> bool:
    """Move the FIRST float stored under ``key`` by one ulp. True if found."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key and isinstance(v, float) and not isinstance(v, bool):
                obj[k] = math.nextafter(v, math.inf)
                return True
        for v in obj.values():
            if _perturb_first_float(v, key):
                return True
    elif isinstance(obj, list):
        for v in obj:
            if _perturb_first_float(v, key):
                return True
    return False


@pytest.mark.parametrize("leaf", _PROTECTED_LEAVES)
def test_one_ulp_change_to_a_protected_leaf_still_fails(
    leaf: str, tabular_reference: LayoutSearchResult
) -> None:
    """The canonicalization did not become a tolerance: a single ulp of a
    clearance, cost or access length is still a FAILING difference."""
    payload = tabular_reference.to_dict()
    clean = observations(payload)
    mutated = copy.deepcopy(payload)
    assert _perturb_first_float(mutated, leaf), f"no float named {leaf!r} in the payload"
    assert observations(mutated) != clean, (
        f"a one-ulp change to {leaf!r} did NOT fail the characterization — the "
        "comparison has become a tolerance"
    )


def test_one_ulp_change_to_a_geometry_coordinate_still_fails(
    tabular_reference: LayoutSearchResult,
) -> None:
    """Centerline coordinates are dropped from the READABLE C4 projection and
    covered only by the C6 payload sha — prove that net is real."""
    payload = tabular_reference.to_dict()
    clean = observations(payload)["c6Payload"]["sha256"]
    mutated = copy.deepcopy(payload)
    # geometry is emitted for SHORTLISTED candidates only (rule 149)
    flat = next(
        c["centerline"]["points"]
        for c in mutated["candidates"]
        if c.get("centerline") and c["centerline"].get("points")
    )
    while isinstance(flat, list) and flat and isinstance(flat[0], list):
        flat = flat[0]
    assert isinstance(flat, list) and isinstance(flat[0], float)
    flat[0] = math.nextafter(flat[0], math.inf)
    assert observations(mutated)["c6Payload"]["sha256"] != clean, (
        "a one-ulp change to a centerline coordinate did NOT change the C6 sha"
    )


def test_the_canonicalized_leaf_is_a_terminal_diagnostic() -> None:
    """WHY the enumerated leaf may be canonicalized at all: nothing else can
    inherit its last bit.

    ``_principal_axis`` (``numpy.linalg.eigh``, the platform-sensitive step)
    has exactly ONE production call site, its axis reaches exactly one dot
    product, and that dot product reaches exactly one diagnostic string. This
    is a SOURCE-level guard: wiring the PCA axis into geometry, a score, a
    clearance or a decision breaks it, and the canonicalization must then be
    re-justified instead of silently covering an engineering value.
    """
    src = Path(access.__file__).read_text(encoding="utf-8")
    assert src.count("_principal_axis(") == 2, "one definition + one production call site"
    assert src.count("pca_axis") == 2, "the axis is assigned once and read once"
    assert src.count("cosang") == 2, "the dot product is assigned once and read once"
    assert "math.degrees(math.acos(cosang))" in src
    assert src.count("localTangentVsGlobalPcaDeg") == 1
