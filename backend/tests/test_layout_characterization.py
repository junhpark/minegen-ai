"""AC-01G — layout-v2 CHARACTERIZATION FREEZE, in two layers.

The safety net for the AC-01G search/stage-boundary refactor: the observable
behaviour of ``LayoutV2Search`` on four golden cases is pinned against the
freeze SHA ``BASELINE_GIT_SHA`` (``tests/characterization_support.py``;
AC-01G froze ``3951d98d``, Phase 20B.x re-froze at ``b13319cf`` after the
rule-188 vertical-profile change — a reviewed move of baseline AND SHA).

    TABULAR-REFERENCE   EXACT clearance contract
    WARPED_VEIN-301     CONSERVATIVE clearance contract
    ACCESS-INFEASIBLE   NO_FEASIBLE_CANDIDATE terminal branch, winnerId None
    GEOMETRY-STRESS     FamilyInfeasible-dominated population; a station-hairpin
                        SWITCHBACK winner at the AC-01G freeze, NO feasible
                        candidate (winnerId None) since Phase 20B.x — proven
                        hard-gate in tests/test_geometry_stress_oracle.py

WHY TWO LAYERS (Park review of PR #35). The first freeze compared every float
of a committed baseline bit for bit. On one commit (tree ``75b67c6``) the
FULL backend job was green and the ordinary CI job was red, differing in
hundreds of last bits of ``footprintDistance`` / ``referencePosition`` /
``referenceChainage`` / ``cheapProxy`` across all four cases: an IEEE bit
pattern is a property of the runner's CPU / BLAS dispatch, not of the source
tree. Rounding those leaves was rejected — ``cheapProxy`` orders the
shortlist and the others are geometry — so the freeze was split by what each
question actually needs:

LAYER A — STATIC COMMITTED, EXACT, DISCRETE. ``discrete_observations``: every
float leaf and numeric list REMOVED (never rounded); ids, order, family,
declared parameters, status, stage, failure reasons, shortlist order and
flags, ranking, rank, winner, screen authority, clearance basis, counts, key
presence / order, plus two declared-literal subtrees kept verbatim. Portable
across runners by construction; compared to the committed baseline exactly.

LAYER B — SAME RUNNER, EXACT, NUMERIC. ``scripts/characterization_observe.py``
is run twice from THIS interpreter on THIS machine — once against
``git archive <freeze-sha> backend/src``, once against HEAD's ``src`` — and
the full float-bearing observation sets must be bit-identical. That is the
question a refactor raises ("same function on this platform?"), and it holds
without any tolerance. Provenance (CPU model, NumPy version and enabled SIMD
dispatch) is recorded on both sides and asserted equal, so "same runner" is
mechanical, not assumed.

Observations (one definition, ``tests/characterization_support``, shared by
the test, the generator and the observe script):

    C1  enumeration — ordered candidate ids, family, serialized parameters
    C2  post-cheap — status, stage, failure reasons, cheap proxy, the ramp
        level-reference summary and the geometric access screen
    C3  shortlist — the ordered shortlist and every ``shortlisted`` flag
    C4  detailed — per shortlisted candidate: status, failures, clearance,
        validation, scores, exposure, diagnostics, derived, access and the
        per-level access records (anchors included)
    C5  ranking — the ordered ranking, every rank and the winner
    C6  payload — (LAYER B) sha256 of the wall-clock-stripped ``to_dict()``;
        (both layers) three views of the UNMASKED payload's key paths, so a
        key added, removed or reordered fails even where its value is not
        compared: ``keyPathCount``, ``keyPathsSha256`` of the ORDERED list,
        and the distinct ``keyPathShape`` with list indices collapsed

INPUT ROUTE (deliberate, so FULL does not pay twice): WARPED_VEIN-301's
in-process result reuses the session ``warped_301_search`` fixture (its
inputs are asserted equal to ``case_by_key("WARPED_VEIN-301").realize()``);
the other three are built once per module. LAYER B builds all four twice in
two fresh subprocesses — symmetric by design: both sides run the same script
with only the source root differing.

WALL-CLOCK HANDLING: exactly the rule ``test_layout_policy_restore.py``
established — drop ``sourceRevision`` and every key ending in ``Seconds``,
nothing else — and a test pins that the two definitions stay identical.

SCOPE / AUTHORITY: a characterization baseline records what the code DID,
not what it SHOULD do. A difference is a signal that behaviour changed and
must be explained; it is never on its own proof of a defect, and it is never
resolved by regenerating the baseline (the generator refuses without
``--force``, and the freeze SHA is pinned in source). The LAYER B base side
is never skipped: a runner that cannot see the base commit FAILS this module
(the CI checkouts use ``fetch-depth: 0`` for exactly that reason).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from minegen.core.models import Scenario
from minegen.layout.search import LayoutSearchResult, LayoutV2Search
from minegen.regression.layout_v2 import case_by_key
from minegen.world.synthetic_world import SyntheticWorld, generate_world
from tests.characterization_support import (
    BASELINE_GIT_SHA,
    CASE_KEYS,
    DECLARED_LITERAL_PATHS,
    SECTIONS,
    WALL_CLOCK_KEYS,
    discrete_from_observations,
    discrete_observations,
    discrete_projection,
    float_leaf_paths,
    key_path_shape,
    key_paths,
    load_baseline,
    observations,
)

TABULAR_KEY = "TABULAR-REFERENCE"
WARPED_KEY = "WARPED_VEIN-301"
ACCESS_INFEASIBLE_KEY = "ACCESS-INFEASIBLE"
GEOMETRY_STRESS_KEY = "GEOMETRY-STRESS"

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
OBSERVE_SCRIPT = ROOT / "scripts" / "characterization_observe.py"
SUPPORT_MODULE = BACKEND / "tests" / "characterization_support.py"


# --------------------------------------------------------------------------- #
# inputs — in-process HEAD results (LAYER A and the structural tests)
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
    """AC-01G Stage D (D4): a FamilyInfeasible-dominated population (60
    CONSTRUCT / 20 CHEAP / 12 DETAILED, against 18 / 62 / 12 in both original
    cases). At the AC-01G freeze it had a SWITCHBACK winner WITH a hairpin
    station; since Phase 20B.x (rule 188) every shortlisted candidate fails
    LEVEL_ACCESS_INFEASIBLE and ``winnerId`` is None — the frozen record now
    holds that outcome and ``test_geometry_stress_oracle.py`` proves why."""
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
# inputs — LAYER B: base and HEAD observed by one script on this machine
# --------------------------------------------------------------------------- #


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def _observe(label: str, source_root: Path, source_sha: str | None, work: Path) -> dict[str, Any]:
    """Run ``characterization_observe.py`` from THIS interpreter with ``minegen``
    resolved from ``source_root`` (the script refuses if it is not)."""
    out = work / f"{label}.json"
    env = {**os.environ, "PYTHONPATH": f"{source_root}{os.pathsep}{BACKEND}"}
    cmd = [
        sys.executable,
        str(OBSERVE_SCRIPT),
        "--expect-source-root",
        str(source_root),
        "--out",
        str(out),
    ]
    for key in CASE_KEYS:
        cmd += ["--case", key]
    if source_sha:
        cmd += ["--source-sha", source_sha]
    proc = subprocess.run(cmd, cwd=BACKEND, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.fail(
            f"LAYER B observation of {label} ({source_root}) failed with exit "
            f"{proc.returncode}:\n{proc.stderr[-4000:]}"
        )
    data: dict[str, Any] = json.loads(out.read_text(encoding="utf-8"))
    return data


@pytest.fixture(scope="session")
def same_runner(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """The freeze-SHA production source and HEAD's, observed by one script,
    one interpreter, one machine. Never skipped: a checkout that cannot see
    the base commit fails here, loudly."""
    work = tmp_path_factory.mktemp("characterization")
    if _git("cat-file", "-e", f"{BASELINE_GIT_SHA}^{{commit}}").returncode != 0:
        pytest.fail(
            f"BASE COMMIT UNAVAILABLE: {BASELINE_GIT_SHA} is not in this clone, so the "
            "same-runner base-vs-HEAD comparison cannot run. A shallow checkout hides it — "
            "the CI workflows check out with fetch-depth: 0 for this reason. This is a FAILURE, "
            "not a skip (rule 181: FULL is never weakened by a missing input)."
        )
    base_root = work / "base"
    base_root.mkdir()
    archive = subprocess.run(
        ["git", "archive", BASELINE_GIT_SHA, "backend/src"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    subprocess.run(["tar", "-x", "-C", str(base_root)], input=archive.stdout, check=True)
    head_sha = _git("rev-parse", "HEAD").stdout.strip() or None
    return {
        "base": _observe("base", base_root / "backend" / "src", BASELINE_GIT_SHA, work),
        "head": _observe("head", BACKEND / "src", head_sha, work),
    }


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
# difference reporting (shared by both layers)
# --------------------------------------------------------------------------- #


def _differing_leaves(expected: Any, actual: Any, path: str = "") -> list[str]:
    """Every differing LEAF path, not just the first.

    Diagnostic only — the comparison itself is unchanged. One difference names
    a candidate; a hundred differences under ONE leaf name is the signature of
    a platform-sensitive scalar, and differences under MANY names are the
    signature of a real behaviour change. Knowing which, from one failing run,
    is what this buys (it is how the PR #35 CI failure was read).
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


def _clip(value: Any, limit: int = 600) -> str:
    text = repr(value)
    return text if len(text) <= limit else f"{text[:limit]}… ({len(text)} chars)"


def _report(
    title: str, section: str, expected: Any, actual: Any, expected_label: str, actual_label: str
) -> str:
    diffs = _differing_leaves(expected, actual)
    first = _first_difference(expected, actual)
    return (
        f"{title} — {section}\n"
        f"  differing leaves in this section: {len(diffs)} — {_leaf_name_census(diffs)}\n"
        f"  {expected_label}: {first[0]}\n"
        f"  {actual_label}: {first[1]}\n"
    )


def _fail_first_differing_section(
    title: str, expected: dict[str, Any], actual: dict[str, Any], labels: tuple[str, str], tail: str
) -> None:
    for section in SECTIONS:
        exp, got = expected[section], actual[section]
        if exp == got:
            continue
        pytest.fail(_report(title, section, exp, got, *labels) + tail)


_BASELINE_TAIL = (
    f"  the committed characterization baseline was generated at git SHA {BASELINE_GIT_SHA} "
    "and records what the search DID there.\n"
    "  Do NOT regenerate the baseline to make this pass. Either the change is unintended "
    "(fix it) or it is intended (explain it in the change, then update the baseline "
    "deliberately with scripts/generate_characterization_baseline.py --force and move "
    "BASELINE_GIT_SHA in tests/characterization_support.py)."
)


# --------------------------------------------------------------------------- #
# LAYER A — the committed discrete record
# --------------------------------------------------------------------------- #


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
    assert "sha256" not in c6, "a float-hashing sha has no place in the LAYER A record"
    assert c6["keyPathCount"] >= len(c6["keyPathShape"]) > 0, (
        "the collapsed key-path shape must be non-empty and no longer than the full list"
    )
    assert len(c6["keyPathsSha256"]) == 64


@pytest.mark.parametrize("case_key", CASE_KEYS)
def test_committed_baseline_is_discrete(case_key: str) -> None:
    """LAYER A portability, mechanically: the committed record holds no float
    and no numeric list outside the two declared-literal subtrees."""
    obs = load_baseline(case_key)["observations"]
    allowed = tuple(f"{section}" for section, _ in DECLARED_LITERAL_PATHS)
    leaks = [
        p
        for p in float_leaf_paths(obs)
        if not any(
            p.startswith(f"{section}") and f".{key}" in p for section, key in DECLARED_LITERAL_PATHS
        )
    ]
    assert leaks == [], (
        f"{case_key}: floats survived the discrete projection outside "
        f"{DECLARED_LITERAL_PATHS} (allowed sections {allowed}): {leaks[:10]}"
    )


@pytest.mark.parametrize("case_key", CASE_KEYS)
def test_search_matches_the_frozen_characterization(
    case_key: str, request: pytest.FixtureRequest
) -> None:
    """LAYER A: every frozen DISCRETE observation of the case, section by
    section, compared exactly."""
    baseline = load_baseline(case_key)["observations"]
    actual = discrete_observations(_result(request, case_key).to_dict())
    _fail_first_differing_section(
        f"LAYOUT-V2 BEHAVIOUR CHANGED — {case_key}",
        baseline,
        actual,
        ("expected (baseline)", "actual   (this run)"),
        _BASELINE_TAIL,
    )


@pytest.mark.parametrize("case_key", CASE_KEYS)
def test_key_paths_are_recomputed_from_the_unmasked_payload(
    case_key: str, request: pytest.FixtureRequest
) -> None:
    """C6 structure: the committed key-path list is the payload's own, in
    emission order, and it still contains the masked keys (a masked VALUE is
    not an unfrozen KEY) and the float keys (a REMOVED value is not a removed
    key)."""
    baseline = load_baseline(case_key)["observations"]["c6Payload"]
    paths = key_paths(_result(request, case_key).to_dict())
    shape = key_path_shape(paths)
    assert shape == baseline["keyPathShape"], _report(
        f"LAYOUT-V2 BEHAVIOUR CHANGED — {case_key}",
        "c6Payload.keyPathShape",
        baseline["keyPathShape"],
        shape,
        "expected (baseline)",
        "actual   (this run)",
    )
    masked = [p for p in paths if p.rsplit(".", 1)[-1].endswith("Seconds")]
    assert masked, "no *Seconds key in the payload — the mask/key-path split is untested here"
    assert any(p.endswith(".cheapProxy") for p in paths), (
        "the float key cheapProxy is absent from the key paths — the key net lost a float key"
    )


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
# the discrete projection itself
# --------------------------------------------------------------------------- #


def test_discrete_projection_removes_floats_and_keeps_decisions() -> None:
    """Removal, never rounding: floats and numeric lists vanish; ints, bools,
    strings, None, empty lists and discrete lists survive with their order."""
    probe: dict[str, Any] = {
        "status": "FEASIBLE",
        "rank": 3,
        "flag": True,
        "nothing": None,
        "empty": [],
        "score": 0.123456789012345,
        "point": [1.0, 2.0, 3.0],
        "points": [[1.0, 2.0], [3.0, 4.0]],
        "ids": ["L01", "L02"],
        "pairs": [["SPIRAL", 1], ["SWITCHBACK", 2]],
        "nested": [{"levelId": "L01", "distance": 38.36011657414005, "withinReach": True}],
        "mixed": [1, 2.5, "x"],
    }
    out = discrete_projection(probe)
    assert out == {
        "status": "FEASIBLE",
        "rank": 3,
        "flag": True,
        "nothing": None,
        "empty": [],
        "ids": ["L01", "L02"],
        "pairs": [["SPIRAL", 1], ["SWITCHBACK", 2]],
        "nested": [{"levelId": "L01", "withinReach": True}],
        # a MIXED list is not a numeric list: it is kept, its float element is
        # dropped from it (a list position is not a key, so nothing to name)
        "mixed": [1, "x"],
    }
    assert float_leaf_paths(out) == []


def test_declared_literals_are_kept_verbatim_and_are_literals(
    tabular_reference: LayoutSearchResult,
) -> None:
    """The two exempt subtrees are exactly the unprojected ones, and they ARE
    declared literals: ``searchConfig`` is byte-equal to the scenario's own
    ``layout`` echo, and ``parameters`` are the enumeration-grid values."""
    payload = tabular_reference.to_dict()
    full = observations(payload)
    disc = discrete_observations(payload)
    assert disc["header"]["searchConfig"] == full["header"]["searchConfig"]
    assert [c["parameters"] for c in disc["c1Enumeration"]] == [
        c["parameters"] for c in full["c1Enumeration"]
    ]
    echo = case_by_key(TABULAR_KEY).realize().layout.model_dump(mode="json", by_alias=True)
    assert disc["header"]["searchConfig"] == echo, (
        "searchConfig is not a pure config echo — it may no longer be treated as a declared "
        "literal in the discrete record"
    )
    # nothing else carries a float
    leaks = [
        p
        for p in float_leaf_paths(disc)
        if not any(
            p.startswith(section) and f".{key}" in p for section, key in DECLARED_LITERAL_PATHS
        )
    ]
    assert leaks == []
    assert "sha256" not in disc["c6Payload"]


def test_the_freeze_has_no_rounding_and_no_tolerance() -> None:
    """Both layers compare EXACTLY. There is no ``round``, no ``isclose``, no
    ``allclose`` and no per-leaf precision table anywhere in the support module
    or the observe script — pinned statically so a tolerance cannot creep in
    under a different name."""
    forbidden = ("round(", "isclose", "allclose", "rel_tol", "abs_tol", "PLATFORM_SENSITIVE")
    for path in (SUPPORT_MODULE, OBSERVE_SCRIPT):
        src = path.read_text(encoding="utf-8")
        hits = [token for token in forbidden if token in src]
        assert hits == [], f"{path.name} contains {hits}"


# --------------------------------------------------------------------------- #
# LAYER B — same runner, base vs HEAD, exact
# --------------------------------------------------------------------------- #


def test_same_runner_sides_share_one_platform(same_runner: dict[str, Any]) -> None:
    """ "Same runner" is asserted, not assumed: same interpreter, same NumPy
    build and enabled SIMD dispatch, same CPU model — and two DIFFERENT
    ``minegen`` roots, the base archive and HEAD."""
    base, head = same_runner["base"]["provenance"], same_runner["head"]["provenance"]
    for key in ("python", "executable", "platform", "machine", "cpuModel", "numericEnv"):
        assert base[key] == head[key], f"provenance.{key} differs: {base[key]!r} vs {head[key]!r}"
    assert base["numpy"] == head["numpy"], f"NumPy differs: {base['numpy']} vs {head['numpy']}"
    assert base["sourceSha"] == BASELINE_GIT_SHA
    assert Path(base["minegenFile"]).is_relative_to(Path(base["sourceRoot"]))
    assert Path(head["minegenFile"]).is_relative_to(BACKEND / "src")
    assert base["sourceRoot"] != head["sourceRoot"]


@pytest.mark.parametrize("case_key", CASE_KEYS)
def test_same_runner_base_and_head_are_bit_identical(
    case_key: str, same_runner: dict[str, Any]
) -> None:
    """LAYER B: the full float-bearing observation set — geometry, scores,
    clearances, the C6 payload sha, everything but the wall clock — of the
    freeze-SHA source and of HEAD, generated on this machine by one script,
    compared exactly. No tolerance."""
    base, head = same_runner["base"], same_runner["head"]
    prov = head["provenance"]
    tail = (
        f"  both sides ran here: {prov['cpuModel']}, numpy {prov['numpy']['version']} "
        f"(dispatch {prov['numpy'].get('dispatchEnabled')}), {prov['python'].split()[0]}\n"
        f"  base = git archive {BASELINE_GIT_SHA[:12]} backend/src; head = {prov['sourceSha']}\n"
        "  A difference here is a behaviour change of the production source on THIS platform — "
        "not a platform artefact, which this layer is built to exclude. Explain it or fix it."
    )
    _fail_first_differing_section(
        f"LAYOUT-V2 BEHAVIOUR CHANGED ON THIS RUNNER — {case_key}",
        base["cases"][case_key],
        head["cases"][case_key],
        ("base (freeze SHA)", "head (this tree)"),
        tail,
    )


@pytest.mark.parametrize("case_key", CASE_KEYS)
def test_same_runner_base_reproduces_the_committed_baseline(
    case_key: str, same_runner: dict[str, Any]
) -> None:
    """The loop closes: the committed LAYER A record is exactly what the
    freeze-SHA source does on THIS runner too, so a LAYER A failure can be
    read as a change and never as a stale or foreign baseline."""
    baseline = load_baseline(case_key)["observations"]
    actual = discrete_from_observations(same_runner["base"]["cases"][case_key])
    _fail_first_differing_section(
        f"COMMITTED BASELINE DISAGREES WITH THE FREEZE SOURCE ON THIS RUNNER — {case_key}",
        baseline,
        actual,
        ("committed baseline", "freeze source, here"),
        "  the baseline was not generated from the pinned freeze source, or the discrete "
        "projection changed without a regeneration. Investigate; never auto-rewrite.",
    )


@pytest.mark.parametrize("case_key", CASE_KEYS)
def test_in_process_and_fresh_process_head_agree_on_the_discrete_record(
    case_key: str, request: pytest.FixtureRequest, same_runner: dict[str, Any]
) -> None:
    """The in-process HEAD result the LAYER A tests use (module fixtures, the
    shared session WARPED search) and the fresh-subprocess HEAD result LAYER
    B uses carry the same discrete record — the two routes into HEAD cannot
    disagree about a decision."""
    in_process = discrete_observations(_result(request, case_key).to_dict())
    fresh = discrete_from_observations(same_runner["head"]["cases"][case_key])
    _fail_first_differing_section(
        f"IN-PROCESS AND FRESH-PROCESS HEAD DISAGREE — {case_key}",
        in_process,
        fresh,
        ("in-process fixture", "fresh subprocess"),
        "  process-global state (a cache, a resolution setting) is leaking into a decision.",
    )
