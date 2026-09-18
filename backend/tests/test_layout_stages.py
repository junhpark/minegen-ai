"""AC-01G stage-boundary proofs for the ``layout.search`` stage extraction.

Mechanical contracts of the new modules (``layout.provider``,
``layout.stages``) and of what ``layout.search`` keeps:

    I1  a stage never reads the search object's run state — the stage
        functions take a ``StageContext`` and have no ``self`` at all, the two
        new modules never name ``_sections`` / ``_track`` / ``_reference`` /
        ``_ctx``, never import the search, and ``_ctx`` is the ONLY private
        attribute left on ``LayoutV2Search``
    I2  ONE owner per run for the section geometry — ``LevelSections`` is
        constructed only in ``layout.setup``, the ``ServiceReference`` only in
        ``layout.provider``, ``set_resolution`` only in ``layout.setup`` /
        ``layout.levels``; and the context, the provider and the stages all
        hold the very same objects
    R1  the offset-trace cache key did not move: the number of
        ``build_offset_trace`` executions of a WARPED-301 run is what it was
        before the refactor
    R2  the world policy / evaluator a rebuilt certification returns are the
        CONSTRUCTOR objects (identity is what decides the trace token)
    R4  the persisted ``performance`` key INSERTION ORDER is unchanged on the
        normal path and on both early-return paths
    I4  (commit 3) an invalid stage transition is impossible or EXPLICITLY
        refused: the stage functions return frozen outcomes whose fields are
        required, exactly two functions write a ``CandidateResult``
        (``apply_cheap`` / ``apply_detailed``) plus ``run()``'s own run-level
        fields, and every refusal is a ``ValueError`` — the stage modules
        contain no ``assert`` at all, so nothing weakens under ``python -O``
    S1  (commit 3) the stage functions really do live in ``layout.stages``,
        which still imports neither ``layout.search`` nor ``minegen.services``

The AST tests are static and cheap (FAST tier); only the WARPED-301 build
count pays for a clean search.
"""

from __future__ import annotations

import ast
import dataclasses
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest

from minegen.core.models import Scenario
from minegen.design.cost_field import RejectionReason
from minegen.layout import levels as levels_module
from minegen.layout import search as search_module
from minegen.layout import stages as stages_module
from minegen.layout.families import CandidateParams, InfeasibleReason, RampFamily
from minegen.layout.results import CandidateResult, CandidateStatus, Stage
from minegen.layout.search import LayoutSearchResult, LayoutV2Search
from minegen.layout.sections import SectionGeometryError
from minegen.world.synthetic_world import SyntheticWorld, generate_world

from .conftest import small_scenario

LAYOUT_DIR = Path(search_module.__file__).parent

#: the private names the refactor removed from ``LayoutV2Search``
#: the search's COMPLETE data-attribute set — seven constructor-owned
#: immutables plus the one post-run compatibility slot. Public or private, an
#: eighth attribute is run state on the search object and fails this test
#: (AC-01G Stage D, D1).
SEARCH_DATA_ATTRIBUTES: frozenset[str] = frozenset(
    {"scenario", "world", "cfg", "policy", "evaluator", "shape", "station_merge_bound", "_ctx"}
)

REMOVED_RUN_STATE = ("_sections", "_track", "_reference")
#: the stage functions that were methods before AC-01G and module functions of
#: ``layout.search`` in commit 2; commit 3 moved them into ``layout.stages``
STAGE_FUNCTIONS = ("cheap_stage", "detailed_stage", "certify")
#: the stage helpers commit 3 moved with them (``layout.search`` re-exports
#: every one of them — proved in ``test_layout_boundaries.py``)
MOVED_HELPERS = (
    "level_service",
    "cheap_checks",
    "level_screen_problems",
    "cheap_proxy",
    "score_candidate",
    "screen_authority",
    "_map_reason",
)
#: the ONLY functions in ``layout/`` allowed to assign a ``CandidateResult``
#: attribute, and the exact field set each of them may write (I4 (iii))
CANDIDATE_WRITERS: dict[tuple[str, str], frozenset[str]] = {
    ("stages.py", "apply_cheap"): frozenset(
        {
            "stage_reached",
            "points",
            "pieces",
            "derived",
            "diagnostics",
            "level_service",
            "cheap_proxy",
            "status",
            "failure_reasons",
            "failure_detail",
            "access_screen",
        }
    ),
    ("stages.py", "apply_detailed"): frozenset(
        {
            "stage_reached",
            "validation",
            "clearance",
            "anchors",
            "access_plan",
            "exposure",
            "scores",
            "status",
            "failure_reasons",
            "failure_detail",
        }
    ),
    ("search.py", "run"): frozenset({"failure_reasons", "failure_detail", "shortlisted", "rank"}),
}
#: writes of a ``CandidateResult`` FIELD NAME by a receiver that is provably
#: NOT a ``CandidateResult``. Park's review of PR #35 found the earlier proof
#: matched only the receiver names ``{cand, c, candidate}``, so a writer bound
#: to any other local name bypassed it entirely. The sweep below is now
#: receiver-AGNOSTIC — it is keyed on the dataclass's OWN field names, read from
#: ``dataclasses.fields`` so it cannot rot — and every non-candidate receiver
#: that happens to share a field name must be declared here. The direction of
#: the over-approximation is deliberate: an undeclared receiver becomes a test
#: FAILURE, never a silent pass.
NON_CANDIDATE_FIELD_WRITES: dict[tuple[str, str, str], frozenset[str]] = {
    # LevelAccess (access.py:1507) — the access planner's own result DTO
    ("access.py", "plan_level_accesses", "access"): frozenset({"failure_detail"}),
    # layout.families.Path — the geometry object a candidate REFERENCES
    ("families.py", "__init__", "self"): frozenset({"pieces", "points"}),
    # layout.sections.SectionGeometryError — the shared section diagnostics
    ("sections.py", "__init__", "self"): frozenset({"diagnostics"}),
}
#: call → the modules under ``layout/`` allowed to make it (I2)
OWNERSHIP_ALLOWLIST: dict[str, frozenset[str]] = {
    "LevelSections": frozenset({"setup.py"}),
    "build_service_reference": frozenset({"provider.py"}),
    "build_footwall_track": frozenset({"setup.py"}),
    "set_resolution": frozenset({"setup.py", "levels.py"}),
    # AC-01G Stage D (D3): the provider itself is built in exactly one place.
    # Without these two rows a SECOND ``build_section_provider(...)`` inside
    # ``layout/`` passed the guard, leaving the WARPED-only, FULL-tier
    # 154-build witness as the only net — and TABULAR builds 0 offset traces,
    # so a TABULAR duplication would have been invisible to it.
    "build_section_provider": frozenset({"search.py"}),
    "SectionProvider": frozenset({"provider.py"}),
    # AC-01G Stage D (D5): the two value types that CARRY the clearance-policy
    # identity. ``StageContext(provider=P, world_policy=<refined>)`` and
    # ``AnchorLens(<refined clearance>, "WORLD")`` are legal values that would
    # key a refined level set under the world cache token; what makes that
    # impossible today is a single construction site, not the type, so the
    # site is pinned here.
    "StageContext": frozenset({"search.py"}),
    "AnchorLens": frozenset({"stages.py"}),
}


def _layout_modules() -> list[Path]:
    return sorted(p for p in LAYOUT_DIR.glob("*.py") if p.name != "__init__.py")


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found")


# --------------------------------------------------------------------------- #
# I1 — stages never read the search object's run state
# --------------------------------------------------------------------------- #


def test_stages_never_read_search_private_state() -> None:
    """The removed run state is named nowhere: not in the new modules, not in
    the stage functions, not anywhere in ``layout/``. ``_ctx`` survives only
    on the search object itself."""
    offenders: list[str] = []
    for path in _layout_modules():
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Attribute) and node.attr in REMOVED_RUN_STATE:
                offenders.append(f"{path.name}:{node.lineno} .{node.attr}")
            if isinstance(node, ast.Attribute) and node.attr == "_ctx" and path.name != "search.py":
                offenders.append(f"{path.name}:{node.lineno} ._ctx")
    assert offenders == [], offenders

    # The search's ENTIRE data-attribute set is pinned, not just the private
    # half. AC-01G Stage D (D1) showed the private-only filter this test used
    # to apply passed unchanged when ``self.sections`` / ``self.track`` /
    # ``self.reference`` were re-introduced as PUBLIC attributes — i.e. the
    # invariant the whole step exists to establish had no guard against its
    # most natural re-introduction. Private METHODS (``_result``,
    # ``_stage_context``) are behaviour, not run state, so they are excluded
    # by name.
    tree = _tree(LAYOUT_DIR / "search.py")
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
    methods = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
    attrs = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        and node.attr not in methods
    }
    assert attrs == SEARCH_DATA_ATTRIBUTES, attrs


def test_stage_functions_are_module_functions_of_layout_stages() -> None:
    """The stage bodies moved OUT of the class and, in commit 3, out of
    ``layout/search.py`` entirely: they are module functions of
    ``layout/stages.py`` whose only context argument is a ``StageContext``, so
    there is no ``self`` to reach through (I1 carried by the type, not by
    discipline). ``layout/search.py`` keeps orchestration and the
    deterministic ordering authority only.
    """
    search_tree = _tree(LAYOUT_DIR / "search.py")
    stages_tree = _tree(LAYOUT_DIR / "stages.py")
    class_defs = {n.name for n in ast.walk(search_tree) if isinstance(n, ast.ClassDef)}
    assert class_defs == {"LayoutV2Search"}
    cls = next(n for n in ast.walk(search_tree) if isinstance(n, ast.ClassDef))
    methods = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
    search_defs = {n.name for n in search_tree.body if isinstance(n, ast.FunctionDef)}
    stage_defs = {n.name for n in stages_tree.body if isinstance(n, ast.FunctionDef)}
    for name in STAGE_FUNCTIONS:
        assert name not in methods, f"{name} is still a method"
        assert name not in search_defs, f"{name} is still defined in search.py"
        assert name in stage_defs, f"{name} is not defined in stages.py"
        fn = _function(stages_tree, name)
        assert fn.args.args[0].arg == "sc"
        names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
        assert "self" not in names, f"{name} still references self"
    for name in MOVED_HELPERS:
        assert name not in search_defs, f"{name} is still defined in search.py"
        assert name in stage_defs, f"{name} is not defined in stages.py"
    # what ``search.py`` keeps: orchestration + the deterministic ordering
    assert search_defs == {"_family_rank", "_shortlist_key", "_rank_key", "_event"}, search_defs
    # and the removed methods are gone
    for gone in ("_cheap_stage", "_detailed_stage", "_candidate_policy"):
        assert gone not in methods, gone


def test_stage_modules_are_leaves() -> None:
    """Importing ``layout.provider`` / ``layout.stages`` must not drag in the
    search or the service layer."""
    code = (
        "import sys, minegen.layout.provider, minegen.layout.stages; "
        "assert 'minegen.layout.search' not in sys.modules, 'search'; "
        "assert not [m for m in sys.modules if m.startswith('minegen.services')], 'services'"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
    # S1 (commit 3): ``layout.stages`` now owns the stage bodies, so it writes
    # the persisted ``CandidateResult`` and must import ``layout.results``;
    # ``layout.search`` and the service layer stay forbidden to both modules,
    # and ``layout.provider`` stays below ``layout.results`` as well.
    forbidden = {
        "provider.py": ("minegen.layout.search", "minegen.layout.results", "minegen.services"),
        "stages.py": ("minegen.layout.search", "minegen.services"),
    }
    for name, banned in forbidden.items():
        for node in ast.walk(_tree(LAYOUT_DIR / name)):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(banned), f"{name}: {node.module}"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith(banned), f"{name}: {alias.name}"


# --------------------------------------------------------------------------- #
# I2 — one owner per run
# --------------------------------------------------------------------------- #


def test_one_owner_per_run_construction_allowlist() -> None:
    offenders: list[str] = []
    for path in _layout_modules():
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.Call):
                continue
            allowed = OWNERSHIP_ALLOWLIST.get(_call_name(node))
            if allowed is not None and path.name not in allowed:
                offenders.append(f"{path.name}:{node.lineno} calls {_call_name(node)}()")
    assert offenders == [], offenders


def test_context_provider_and_stages_share_one_set_of_objects(
    tabular: tuple[Scenario, SyntheticWorld], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The provider the run built, the context the families were built
    against and the context a stage received all hold the SAME objects.

    The reference is attached in a SECOND step (``attach_service_reference``,
    after the early-return guards, so ``performance.setupSeconds`` keeps its
    meaning), which returns a new frozen provider — so this pins both halves:
    the attached provider must carry the pre-attach ``sections`` / ``track`` /
    ``serviceable`` BY IDENTITY (nothing is rebuilt) and the reference the
    stage sees must be the one ``build_service_reference`` returned."""
    sc, world = tabular
    seen: dict[str, Any] = {}
    real_provider = search_module.build_section_provider
    real_attach = search_module.attach_service_reference
    real_cheap = search_module.cheap_stage

    def spy_provider(*a: Any, **k: Any) -> Any:
        out = real_provider(*a, **k)
        seen.setdefault("setup_provider", out[1])
        return out

    def spy_attach(*a: Any, **k: Any) -> Any:
        out = real_attach(*a, **k)
        seen.setdefault("provider", out)
        return out

    def spy_cheap(stage_ctx: Any, candidate_id: str, built: Any) -> Any:
        seen.setdefault("stage_ctx", stage_ctx)
        return real_cheap(stage_ctx, candidate_id, built)

    monkeypatch.setattr(search_module, "build_section_provider", spy_provider)
    monkeypatch.setattr(search_module, "attach_service_reference", spy_attach)
    monkeypatch.setattr(search_module, "cheap_stage", spy_cheap)
    s = LayoutV2Search(sc, world)
    s.run()
    provider = seen["provider"]
    setup_provider = seen["setup_provider"]
    stage_ctx = seen["stage_ctx"]
    # attaching the reference rebuilds NOTHING: the three section-geometry
    # references survive the frozen `replace` by identity
    assert provider.sections is setup_provider.sections
    assert provider.track is setup_provider.track
    assert provider.serviceable is setup_provider.serviceable
    assert setup_provider.reference is None and provider.reference is not None
    assert s.context.sections is provider.sections
    assert s.context.track is provider.track
    assert s.context.reference is provider.reference
    assert s.context.levels is provider.serviceable
    assert stage_ctx.provider is provider
    assert stage_ctx.sections is provider.sections
    assert stage_ctx.track is provider.track
    assert stage_ctx.ctx is s.context


# --------------------------------------------------------------------------- #
# R1 — the offset-trace cache key did not move
# --------------------------------------------------------------------------- #

#: ``layout.levels.build_offset_trace`` executions of ONE clean WARPED-301
#: search. MEASURED AT THE FREEZE HEAD 45e9aea (AC-01G commit 1) with a spy
#: identical to the one below, BEFORE any of the AC-01G commit-2 code existed:
#: 154 = the WORLD-token reference/screen traces plus the per-candidate
#: REFINED_CONSERVATIVE traces of the shortlist (A5: S + K_refined × S).
#: A change here means the cache KEY moved — a different stand-off, a
#: different token, or a second clearance field — which also moves the
#: delivered trace geometry (rule 178). It is a build-cost witness, not a
#: budget to be tuned.
WARPED_301_OFFSET_TRACE_BUILDS = 154


def test_offset_trace_build_count_matches_head(
    warped_301: tuple[Scenario, SyntheticWorld],
) -> None:
    sc, world = warped_301
    calls: list[int] = [0]
    real = levels_module.build_offset_trace

    def spy(*a: Any, **k: Any) -> Any:
        calls[0] += 1
        return real(*a, **k)

    original = levels_module.build_offset_trace
    levels_module.build_offset_trace = spy  # type: ignore[assignment]
    try:
        LayoutV2Search(sc, world).run()
    finally:
        levels_module.build_offset_trace = original  # type: ignore[assignment]
    assert calls[0] == WARPED_301_OFFSET_TRACE_BUILDS


# --------------------------------------------------------------------------- #
# R2 — the world policy / evaluator identity
# --------------------------------------------------------------------------- #


def test_world_policy_identity_is_the_constructor_object(
    tabular_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    """On an EXACT (non-refined) candidate ``build_candidate_policy`` returns
    the world objects themselves — which is exactly what makes the
    offset-trace token ``"WORLD"``. A ``StageContext`` that fetched a FRESH
    ``world_search_policy`` would keep the token but break this identity."""
    s, res = tabular_search
    assert res.winner_id is not None
    evaluator, policy, refinement = s.candidate_policy(res, res.winner_id)
    assert policy is s.policy
    assert evaluator is s.evaluator
    assert refinement["applied"] is False


# --------------------------------------------------------------------------- #
# R4 — the persisted `performance` key insertion order
# --------------------------------------------------------------------------- #

NORMAL_PERF_KEYS = (
    "candidateCount",
    "setupSeconds",
    "serviceReference",
    "constructAndCheapSeconds",
    "shortlistSize",
    "cheapFeasibleCount",
    "exhaustiveDiagnostic",
    "detailedSeconds",
    "totalSeconds",
)
EARLY_RETURN_PERF_KEYS = ("candidateCount", "setupSeconds", "totalSeconds")


def test_performance_key_order_on_the_normal_path(
    tabular_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    """``performance`` is persisted in INSERTION order (``results.py``), so
    moving the ServiceReference build into the provider must not move its
    key. TABULAR attaches no ``sectionGeometry`` (no section resolution)."""
    _, res = tabular_search
    assert tuple(res.performance) == NORMAL_PERF_KEYS


def test_performance_key_order_with_section_geometry(
    warped_301_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    """A non-TABULAR body adds ``sectionGeometry`` between ``setupSeconds``
    and ``serviceReference`` — and nowhere else."""
    _, res = warped_301_search
    keys = tuple(res.performance)
    i = keys.index("setupSeconds")
    assert keys[i + 1] == "sectionGeometry"
    assert tuple(k for k in keys if k != "sectionGeometry") == NORMAL_PERF_KEYS


def test_performance_key_order_on_the_section_error_early_return(
    tabular: tuple[Scenario, SyntheticWorld], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The section-geometry failure path: ``sectionGeometry`` is inserted
    between ``setupSeconds`` and ``totalSeconds`` and nothing else is."""
    sc, world = tabular
    real = search_module.build_section_provider
    err = SectionGeometryError("SECTION_STANDOFF_NONPOSITIVE", "forced", {"probe": 1})

    def broken(*a: Any, **k: Any) -> Any:
        setup, provider = real(*a, **k)
        return replace(setup, section_error=err), replace(provider, reference=None)

    monkeypatch.setattr(search_module, "build_section_provider", broken)
    res = LayoutV2Search(sc, world).run()
    assert tuple(res.performance) == (
        "candidateCount",
        "setupSeconds",
        "sectionGeometry",
        "totalSeconds",
    )
    assert res.performance["sectionGeometry"] == {"probe": 1}
    assert all(c.failure_reasons == ["SECTION_STANDOFF_NONPOSITIVE"] for c in res.candidates)
    assert all(c.status == CandidateStatus.INFEASIBLE for c in res.candidates)


def test_performance_key_order_on_the_no_serviceable_level_early_return(
    tabular: tuple[Scenario, SyntheticWorld], monkeypatch: pytest.MonkeyPatch
) -> None:
    sc, world = tabular
    real = search_module.build_section_provider

    def empty(*a: Any, **k: Any) -> Any:
        setup, provider = real(*a, **k)
        return setup, replace(provider, serviceable=[], reference=None)

    monkeypatch.setattr(search_module, "build_section_provider", empty)
    res = LayoutV2Search(sc, world).run()
    assert tuple(res.performance) == EARLY_RETURN_PERF_KEYS
    assert all(c.failure_reasons == ["NO_REQUIRED_LEVELS"] for c in res.candidates)


def test_a_repeated_early_returning_run_leaves_no_stale_context(
    tabular: tuple[Scenario, SyntheticWorld], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``run()`` clears ``_ctx`` first (census O11): a search that ran, then
    returned early, exposes no previous context."""
    sc, world = tabular
    s = LayoutV2Search(sc, world)
    s.run()
    assert s.context is not None
    real = search_module.build_section_provider

    def empty(*a: Any, **k: Any) -> Any:
        setup, provider = real(*a, **k)
        return setup, replace(provider, serviceable=[], reference=None)

    monkeypatch.setattr(search_module, "build_section_provider", empty)
    s.run()
    with pytest.raises(RuntimeError, match="has not built a stage context"):
        _ = s.context


# --------------------------------------------------------------------------- #
# I4 — invalid stage transitions are impossible or EXPLICITLY refused
# --------------------------------------------------------------------------- #


def _params() -> CandidateParams:
    return CandidateParams(
        RampFamily.SPIRAL, 0.1, turns_per_level=1, turn_sense="CW", entry_orientation_deg=0.0
    )


def _other_params() -> CandidateParams:
    """A DIFFERENT candidate — same family, another gradient, so its
    ``candidate_id`` differs while every other precondition of the transition
    paths still passes."""
    return CandidateParams(
        RampFamily.SPIRAL, 0.12, turns_per_level=1, turn_sense="CW", entry_orientation_deg=0.0
    )


def _cheap_outcome(
    problems: list[Any], candidate_id: str | None = None
) -> stages_module.CheapEvaluation:
    """A hand-built stage-2 outcome carrying only what the transition paths
    read. Every field is REQUIRED by the frozen DTO — which is the point: a
    half-built stage result cannot be constructed at all."""
    return stages_module.CheapEvaluation(
        candidate_id=candidate_id or _params().candidate_id,
        points=np.zeros((2, 3)),
        diagnostics=cast(Any, "DIAGNOSTICS"),
        level_service=[],
        cheap_proxy=12.5,
        problems=problems,
        status=(CandidateStatus.INFEASIBLE if problems else CandidateStatus.NOT_VALIDATED),
        failure_reasons=["PROBE"] if problems else [],
        failure_detail="probe" if problems else None,
        access_screen=None if problems else {"blockedCount": 0, "authority": "HEURISTIC"},
        derived={"probe": 1},
        pieces=[{"kind": "PROBE"}],
    )


def _detailed_outcome(candidate_id: str | None = None) -> stages_module.DetailedEvaluation:
    return stages_module.DetailedEvaluation(
        candidate_id=candidate_id or _params().candidate_id,
        clearance=cast(Any, "CLEARANCE"),
        validation={"probe": 2},
        scores=cast(Any, "SCORES"),
        exposure={"probe": 3},
        anchors=[],
        access_plan=None,
        status=CandidateStatus.FEASIBLE,
        failure_reasons=[],
        failure_detail=None,
    )


def test_detailed_stage_refuses_a_failed_cheap_outcome() -> None:
    """The shortlist is drawn from ``NOT_VALIDATED`` candidates only, so a
    failed cheap outcome can never reach stage 4 — which is exactly why the
    guard must be a ``ValueError`` and not an ``assert`` (it would vanish
    under ``python -O``, leaving the unreachable case unguarded)."""
    cand = CandidateResult(_params())
    failed = _cheap_outcome([(cast(Any, "GRADE_LIMIT"), "probe")])
    with pytest.raises(ValueError, match="failed the cheap stage"):
        stages_module.detailed_stage(cast(Any, None), cand, failed)


def test_apply_cheap_refuses_a_record_that_is_past_construct() -> None:
    cand = CandidateResult(_params())
    ev = _cheap_outcome([])
    stages_module.apply_cheap(cand, ev)
    # the outcome's values land on the record, unchanged and by identity
    assert cand.stage_reached == Stage.CHEAP
    assert cand.status == CandidateStatus.NOT_VALIDATED
    assert cand.points is ev.points
    assert cand.diagnostics is ev.diagnostics
    assert cand.level_service is ev.level_service
    assert cand.cheap_proxy == 12.5
    assert cand.derived is ev.derived and cand.pieces is ev.pieces
    assert cand.access_screen is ev.access_screen
    with pytest.raises(ValueError, match="cleanly constructed record"):
        stages_module.apply_cheap(cand, ev)


def test_apply_cheap_writes_the_proxy_of_a_cheap_infeasible_row() -> None:
    """R3: ``cheap_proxy`` is computed for EVERY constructed candidate, before
    the feasibility branch, so a cheap-INFEASIBLE row's persisted
    ``cheapProxy`` is a number — not ``null``. The DTO makes it non-optional
    and ``apply_cheap`` writes it unconditionally."""
    cand = CandidateResult(_params())
    ev = _cheap_outcome([(cast(Any, "GRADE_LIMIT"), "probe")])
    stages_module.apply_cheap(cand, ev)
    assert cand.status == CandidateStatus.INFEASIBLE
    assert cand.cheap_proxy == 12.5
    assert cand.failure_reasons == ["PROBE"] and cand.failure_detail == "probe"
    assert cand.access_screen is None


def test_apply_detailed_refuses_anything_but_a_cheap_feasible_record() -> None:
    det = _detailed_outcome()
    fresh = CandidateResult(_params())
    with pytest.raises(ValueError, match=r"not \(CHEAP, NOT_VALIDATED\)"):
        stages_module.apply_detailed(fresh, det)

    infeasible = CandidateResult(_params())
    stages_module.apply_cheap(infeasible, _cheap_outcome([(cast(Any, "GRADE_LIMIT"), "probe")]))
    with pytest.raises(ValueError, match=r"not \(CHEAP, NOT_VALIDATED\)"):
        stages_module.apply_detailed(infeasible, det)

    ok = CandidateResult(_params())
    stages_module.apply_cheap(ok, _cheap_outcome([]))
    stages_module.apply_detailed(ok, det)
    assert ok.stage_reached == Stage.DETAILED
    assert ok.status == CandidateStatus.FEASIBLE
    assert ok.clearance is det.clearance and ok.scores is det.scores
    assert ok.validation is det.validation and ok.exposure is det.exposure
    assert ok.anchors is det.anchors and ok.access_plan is None
    # a second application (now DETAILED / FEASIBLE) is refused too
    with pytest.raises(ValueError, match=r"not \(CHEAP, NOT_VALIDATED\)"):
        stages_module.apply_detailed(ok, det)


def test_candidate_result_writers_are_the_apply_functions() -> None:
    """Exactly three functions in ``layout/`` assign a ``CandidateResult``
    attribute, and each writes exactly the field set it is allowed to.

    Receiver-AGNOSTIC: every assignment to ANY attribute whose name is a
    ``CandidateResult`` field is examined, whatever the receiver is called, so
    ``result.status = ...`` or ``x.scores = ...`` cannot slip past the proof.
    The three receivers in ``layout/`` that are NOT candidates are declared in
    ``NON_CANDIDATE_FIELD_WRITES``.
    """
    fields = {f.name for f in dataclasses.fields(CandidateResult)}
    # the allowlist may not name a field the dataclass does not have
    declared = {a for allowed in CANDIDATE_WRITERS.values() for a in allowed}
    assert declared <= fields, f"CANDIDATE_WRITERS names non-fields: {sorted(declared - fields)}"

    written: dict[tuple[str, str], set[str]] = {}
    exempt_seen: dict[tuple[str, str, str], set[str]] = {}
    offenders: list[str] = []
    for path in _layout_modules():
        for fn in ast.walk(_tree(path)):
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Assign):
                    targets: list[ast.expr] = list(node.targets)
                elif isinstance(node, ast.AugAssign | ast.AnnAssign):
                    targets = [node.target]
                else:
                    continue
                for tgt in targets:
                    if not (isinstance(tgt, ast.Attribute) and tgt.attr in fields):
                        continue
                    receiver = tgt.value.id if isinstance(tgt.value, ast.Name) else "<expr>"
                    exempt_key = (path.name, fn.name, receiver)
                    if tgt.attr in NON_CANDIDATE_FIELD_WRITES.get(exempt_key, frozenset()):
                        exempt_seen.setdefault(exempt_key, set()).add(tgt.attr)
                        continue
                    key = (path.name, fn.name)
                    allowed = CANDIDATE_WRITERS.get(key)
                    if allowed is None or tgt.attr not in allowed:
                        offenders.append(
                            f"{path.name}:{node.lineno} {fn.name}() writes {receiver}.{tgt.attr}"
                        )
                    else:
                        written.setdefault(key, set()).add(tgt.attr)
    assert offenders == [], offenders
    # and neither table has rotted: every declared writer writes every field it
    # declares, nothing declares a field it never writes, and every declared
    # exemption is still a real write that still needs exempting
    assert written == {k: set(v) for k, v in CANDIDATE_WRITERS.items()}
    assert exempt_seen == {k: set(v) for k, v in NON_CANDIDATE_FIELD_WRITES.items()}


def test_the_stage_modules_contain_no_assert_statement() -> None:
    """A refusal that ``python -O`` removes is not a refusal (Stage B §6.8)."""
    for name in ("stages.py", "provider.py"):
        found = [n.lineno for n in ast.walk(_tree(LAYOUT_DIR / name)) if isinstance(n, ast.Assert)]
        assert found == [], f"{name}: assert at {found}"


def test_the_dead_crossings_field_is_gone() -> None:
    """``CandidateResult.crossings`` had one writer and no reader at all
    (census O1); ``level_service`` still returns the crossings and the cheap
    stage discards them."""
    assert not hasattr(CandidateResult(_params()), "crossings")
    assert "crossings" not in {f.name for f in dataclasses.fields(CandidateResult)}


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def tabular() -> tuple[Scenario, SyntheticWorld]:
    sc = small_scenario()
    return sc, generate_world(sc)


@pytest.fixture(scope="module")
def tabular_search(
    tabular: tuple[Scenario, SyntheticWorld],
) -> tuple[LayoutV2Search, LayoutSearchResult]:
    sc, world = tabular
    s = LayoutV2Search(sc, world)
    return s, s.run()


def test_detailed_failure_reasons_are_sorted_and_de_duplicated() -> None:
    """The two stages assemble ``failure_reasons`` DIFFERENTLY on purpose and
    both forms are HARD-CONTRACT golden content: the cheap stage keeps problem
    ORDER with duplicates (``[p[0].value for p in problems]``), the detailed
    stage sorts and de-duplicates (``sorted({...})``).

    AC-01G Stage D (D4) measured that the detailed half was differentiated by
    NOTHING in the repository — across all 7 golden cases the 84 DETAILED
    candidates have a failure-reason multiplicity histogram of {0: 56, 1: 28},
    so not one of them carries two reasons, and a mutant swapping the detailed
    semantics for the cheap ones left every payload sha unchanged. The de-dup
    IS load-bearing: ``_map_reason`` sends BOTH ``INSIDE_OREBODY`` and
    ``OREBODY_BUFFER`` to ``OREBODY_CLEARANCE``, and an explicit clearance
    failure appends a third. This pins the semantics directly on the
    assembly rather than waiting for a scenario that happens to produce it."""
    rejections = {
        RejectionReason.INSIDE_OREBODY.value: 3,
        RejectionReason.OUTSIDE_WORLD.value: 1,
        RejectionReason.OREBODY_BUFFER.value: 12,
    }
    problems = [(stages_module._map_reason(r), f"{c} samples {r}") for r, c in rejections.items()]
    problems.append((InfeasibleReason.OREBODY_CLEARANCE, "conservative minimum clearance"))

    cheap_form = [p[0].value for p in problems]
    detailed_form = sorted({p[0].value for p in problems})

    # the cheap form keeps every occurrence, in problem order
    assert cheap_form == [
        "OREBODY_CLEARANCE",
        "WORLD_BOUNDS",
        "OREBODY_CLEARANCE",
        "OREBODY_CLEARANCE",
    ]
    # the detailed form collapses the three OREBODY_CLEARANCE entries and sorts
    assert detailed_form == ["OREBODY_CLEARANCE", "WORLD_BOUNDS"]
    assert detailed_form != cheap_form, "the two semantics must not coincide on this input"


# --------------------------------------------------------------------------- #
# AC-01G (Park review): a stage outcome BELONGS to one candidate
# --------------------------------------------------------------------------- #


def test_apply_cheap_refuses_an_outcome_from_another_candidate() -> None:
    """The frozen outcomes made a half-built stage result unconstructible,
    but not a MISAPPLIED one: without an identity on the DTO, candidate B's
    record accepts candidate A's cheap outcome and ends up with B's
    ``candidateId`` and ``parameters`` beside A's ``points``, ``diagnostics``,
    ``derived`` and ``pieces``. Production keys the outcomes by id, which is
    exactly the statement-order coupling this step exists to replace."""
    other = CandidateResult(_other_params())
    ev_a = _cheap_outcome([])
    assert ev_a.candidate_id != other.candidate_id
    with pytest.raises(ValueError, match="never applied across candidates"):
        stages_module.apply_cheap(other, ev_a)
    # and the record is untouched by the refusal
    assert other.stage_reached == Stage.CONSTRUCT
    assert other.points is None


def test_detailed_stage_refuses_a_cheap_outcome_from_another_candidate() -> None:
    """Stage 4 reads the delivered centerline from the cheap outcome and the
    candidate id from the record. A mismatched pair would certify one ramp
    under another candidate's id — the identity check comes BEFORE the
    cheap-problems check so the refusal does not depend on the outcome's
    feasibility."""
    other = CandidateResult(_other_params())
    ev_a = _cheap_outcome([])
    with pytest.raises(ValueError, match="never reusable across candidates"):
        stages_module.detailed_stage(cast(Any, None), other, ev_a)


def test_apply_detailed_refuses_an_outcome_from_another_candidate() -> None:
    """The same binding on the stage-4 half: a detailed outcome carries the
    id of the candidate it was computed for, and the identity check precedes
    the (stage, status) check."""
    other = CandidateResult(_other_params())
    stages_module.apply_cheap(other, _cheap_outcome([], other.candidate_id))
    assert (other.stage_reached, other.status) == (Stage.CHEAP, CandidateStatus.NOT_VALIDATED)
    with pytest.raises(ValueError, match="never applied across candidates"):
        stages_module.apply_detailed(other, _detailed_outcome())
    # the refusal leaves the cheap-stage record exactly as it was
    assert other.stage_reached == Stage.CHEAP
    assert other.clearance is None


def test_stage_outcomes_carry_candidate_identity() -> None:
    """The binding is a FIELD of each outcome, not a convention: both DTOs
    declare ``candidate_id`` and both are frozen, so an outcome cannot be
    re-labelled after the stage produced it."""
    for dto in (stages_module.CheapEvaluation, stages_module.DetailedEvaluation):
        names = [f.name for f in dataclasses.fields(dto)]
        assert names[0] == "candidate_id", f"{dto.__name__}: {names}"
        assert dto.__dataclass_params__.frozen, dto.__name__
    ev = _cheap_outcome([])
    with pytest.raises(dataclasses.FrozenInstanceError):
        ev.candidate_id = "SOMETHING-ELSE"  # type: ignore[misc]
