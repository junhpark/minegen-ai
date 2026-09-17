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

The AST tests are static and cheap (FAST tier); only the WARPED-301 build
count pays for a clean search.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from minegen.core.models import Scenario
from minegen.layout import levels as levels_module
from minegen.layout import search as search_module
from minegen.layout.results import CandidateStatus
from minegen.layout.search import LayoutSearchResult, LayoutV2Search
from minegen.layout.sections import SectionGeometryError
from minegen.world.synthetic_world import SyntheticWorld, generate_world

from .conftest import small_scenario

LAYOUT_DIR = Path(search_module.__file__).parent

#: the private names the refactor removed from ``LayoutV2Search``
REMOVED_RUN_STATE = ("_sections", "_track", "_reference")
#: the stage functions that were methods before AC-01G
STAGE_FUNCTIONS = ("cheap_stage", "detailed_stage", "_certify")
#: call → the modules under ``layout/`` allowed to make it (I2)
OWNERSHIP_ALLOWLIST: dict[str, frozenset[str]] = {
    "LevelSections": frozenset({"setup.py"}),
    "build_service_reference": frozenset({"provider.py"}),
    "build_footwall_track": frozenset({"setup.py"}),
    "set_resolution": frozenset({"setup.py", "levels.py"}),
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

    # ``_ctx`` is the ONLY private ``self._x`` DATA attribute left on the
    # search class (private METHODS — ``_result``, ``_stage_context`` — are
    # behaviour, not run state, so they are excluded by name)
    tree = _tree(LAYOUT_DIR / "search.py")
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
    methods = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
    private = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        and node.attr.startswith("_")
        and node.attr not in methods
    }
    assert private == {"_ctx"}, private


def test_stage_functions_are_module_functions_without_self() -> None:
    """The stage bodies moved OUT of the class: they are module functions
    whose only context argument is a ``StageContext``, so there is no ``self``
    to reach through (I1 carried by the type, not by discipline).

    They live in ``layout/search.py`` rather than ``layout/stages.py`` because
    they call the stage helpers (``cheap_checks`` / ``level_service`` /
    ``cheap_proxy`` / ``score_candidate`` / ``screen_authority``) that this
    commit deliberately does NOT move; importing them into ``layout.stages``
    would make ``stages`` ↔ ``search`` a cycle. ``StageContext`` /
    ``AnchorLens`` / ``build_anchors`` — everything that needs no helper —
    live in ``layout.stages``, which stays a leaf.
    """
    tree = _tree(LAYOUT_DIR / "search.py")
    class_defs = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    assert class_defs == {"LayoutV2Search"}
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
    methods = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
    for name in STAGE_FUNCTIONS:
        assert name not in methods, f"{name} is still a method"
        fn = _function(tree, name)
        assert fn.args.args[0].arg == "sc"
        names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
        assert "self" not in names, f"{name} still references self"
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
    forbidden = ("minegen.layout.search", "minegen.layout.results", "minegen.services")
    for name in ("provider.py", "stages.py"):
        for node in ast.walk(_tree(LAYOUT_DIR / name)):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(forbidden), f"{name}: {node.module}"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith(forbidden), f"{name}: {alias.name}"


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
    against and the context a stage received all hold the SAME objects."""
    sc, world = tabular
    seen: dict[str, Any] = {}
    real_provider = search_module.build_section_provider
    real_cheap = search_module.cheap_stage

    def spy_provider(*a: Any, **k: Any) -> Any:
        out = real_provider(*a, **k)
        seen.setdefault("provider", out[1])
        return out

    def spy_cheap(stage_ctx: Any, cand: Any, built: Any) -> None:
        seen.setdefault("stage_ctx", stage_ctx)
        real_cheap(stage_ctx, cand, built)

    monkeypatch.setattr(search_module, "build_section_provider", spy_provider)
    monkeypatch.setattr(search_module, "cheap_stage", spy_cheap)
    s = LayoutV2Search(sc, world)
    s.run()
    provider = seen["provider"]
    stage_ctx = seen["stage_ctx"]
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
