"""AC-01F T10 — ONE reader of the persisted derived artifacts.

The mechanical half of "READ ≠ TRUST": after commit 2 no module outside
``services/artifact_reader.py`` may open, read or parse a file under
``derived/``. The duplicate raw readers this replaces were not a style
problem — they were the reason ``GET …/design/shafts`` served 200 what every
builder refused with 409 (Stage A I-1), and the reason one corrupt file made
the whole scene a bare 500 (I-5).

Pattern: ``tests/test_no_block_semantics.py`` (rule 127) — a static AST proof
over the source tree with a LITERAL allowlist, so a new raw reader fails the
suite the moment it is written, not two phases later.

Stage D S15 widened the proof to match the claim. It scanned
``services`` + ``api`` only, NON-recursively — 21 of the package's 108 modules,
leaving 15 sub-packages (``layout``, ``design``, ``world``, ``network``,
``levels``, ``regression``, …) outside a claim commit 2 stated tree-wide — and
its presence detector modelled only the RECEIVER of ``is_file`` / ``exists``,
so ``os.path.exists(p)``, ``os.path.isfile(p)``, ``os.path.getsize(p)``,
``p.stat()`` and ``p.glob(…)`` were invisible. The scan is
``SRC.rglob("*.py")`` now, the vocabulary covers those five spellings, and
both detectors inspect call ARGUMENTS as well as receivers. One boundary
stays: a derived path built INLINE and bound to a local first (never through a
named path helper) is invisible to ``_derived_path_locals``, so an inline
derived path must be probed directly or through a named helper to be seen. The four
``regression/`` REPORT readers are the explicit allowlist: they read and write
the regression REPORT files under ``backend/golden/`` (rule 132), which are
not derived artifacts of a scenario at all.
"""

from __future__ import annotations

import ast
from pathlib import Path

from minegen.core import artifacts as artifact_names
from minegen.core.artifact_registry import derived_artifacts
from minegen.core.artifacts import RAMP_SOURCE_FILE
from minegen.services.artifact_reader import READ_SPECS
from minegen.services.world_service import SCENE_SLOTS

#: anchored on THIS file, never on the process working directory: a relative
#: ``Path("src/minegen")`` silently globs NOTHING when pytest is invoked from
#: the repository root, and an empty scan asserts ``[] == []`` — a green test
#: that proves nothing (§29). ``test_the_scan_is_not_empty`` pins the count.
SRC = Path(__file__).resolve().parents[1] / "src" / "minegen"
#: the WHOLE package (S15). Commit 2's claim — "no json.loads / read_text /
#: is_file of a derived artifact exists outside ``services/artifact_reader.py``"
#: — is tree-wide, so the proof is tree-wide.
SCANNED = (SRC,)
#: measured at Stage D: 108 modules under ``src/minegen`` (21 of which are the
#: ``services`` + ``api`` packages the pre-S15 scan covered)
MINIMUM_SCANNED_MODULES = 100

#: the ONE module allowed to read a derived artifact file
READ_AUTHORITY = "artifact_reader.py"

#: the ONE remaining file read in the scanned packages that is NOT a derived
#: artifact: ``ScenarioStore.get`` reads ``scenario.json`` (the scenario
#: document, a scenario-directory root — and the Phase 18 migration-on-read,
#: kept as the documented exception to "a read must not write", AC-01F A10).
#: ``WorldService.load`` reads ``arrays.npz`` through ``np.load``, which is
#: not a ``read_text`` / ``read_bytes`` / ``open`` call at all.
#:
#: S15: the four ``regression/`` REPORT readers. ``python -m minegen.regression``
#: writes and re-reads its own report files under ``backend/golden/``
#: (rule 132) — a regression baseline, never a derived artifact of a scenario,
#: and never on any API read path. Named one function at a time, so a new
#: reader anywhere in those modules still fails the proof.
#: keyed by the module's path RELATIVE to ``src/minegen`` — a bare basename
#: would grant ``regression/warped_vein.py``'s exemption to
#: ``world/warped_vein.py`` as well once the scan covers the whole package
ALLOWED_FILE_READS: dict[str, tuple[str, ...]] = {
    "services/scenario_service.py": ("get",),
    "regression/golden.py": ("write_report", "load_report"),
    "regression/layout_v2.py": ("write_report", "load_report"),
    "regression/warped_vein.py": ("write_report", "load_report"),
    "regression/repool.py": ("main",),
}


def _allowed_reads(module: Path) -> tuple[str, ...]:
    return ALLOWED_FILE_READS.get(module.relative_to(SRC).as_posix(), ())


def test_every_allowlist_key_names_exactly_one_scanned_module() -> None:
    scanned = {m.relative_to(SRC).as_posix() for m in _modules()}
    missing = sorted(k for k in ALLOWED_FILE_READS if k not in scanned)
    assert missing == [], missing


READ_CALLS = frozenset({"read_text", "read_bytes", "open"})

#: a presence probe is a read too — the weakest one. ``_layout_object``'s
#: ``self.layout_path(sid).is_file()`` let a MALFORMED catalogue be selected
#: and the search re-run against a document nobody could parse (C3), and the
#: ramp resolution's three ``is_file`` probes were the R4 interleaving. Only
#: the READ AUTHORITY may decide that a derived artifact is there.
#:
#: S15 added the four spellings the receiver-only detector could not see:
#: ``os.path.exists`` / ``os.path.isfile`` / ``os.path.getsize`` (a MODULE
#: function whose receiver is ``os.path``, never the path) and ``stat`` /
#: ``glob`` / ``rglob`` (a stat IS the rule-60 identity, and a glob is a
#: presence decision over a set of them).
PRESENCE_CALLS = frozenset({"is_file", "exists", "isfile", "getsize", "stat", "glob", "rglob"})

#: every file name the AC-01E registry declares under ``derived/`` …
DERIVED_FILE_NAMES = frozenset(f.name for a in derived_artifacts() for f in a.files)
#: … and the ``core/artifacts`` identifiers bound to them, because that is how
#: the source spells them. ``scenario.json`` / ``arrays.npz`` are scenario
#: -directory roots, not derived artifacts, so ``scenario_service.py``'s own
#: probes never match and need no allowlist entry.
DERIVED_NAME_IDENTIFIERS = frozenset(
    name
    for name, value in vars(artifact_names).items()
    if isinstance(value, str) and value in DERIVED_FILE_NAMES
)

#: WRITE-side cleanup, explicitly: after persisting a report whose sweep
#: produced no GLB, the writer removes the stale GLB beside it so a two-file
#: unit is never half-old (``design_service.generate_tunnel`` /
#: ``generate_development_mesh``, inside the publish lock). These probe a
#: derived path to DELETE it, never to decide that a read may proceed.
ALLOWED_PRESENCE_PROBES: dict[str, tuple[str, ...]] = {
    "design_service.py": ("generate_tunnel", "generate_development_mesh"),
}


def _modules() -> list[Path]:
    return sorted(p for package in SCANNED for p in package.rglob("*.py"))


def _derived_path_functions(tree: ast.AST) -> set[str]:
    """Functions of this module that RETURN a path naming a derived artifact
    (``return self.store.derived_dir(sid) / TUNNEL_MESH_GLB``) — the spelling
    every presence probe in the services layer goes through."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Return)
                and inner.value is not None
                and _names_a_derived_artifact(inner.value)
            ):
                found.add(node.name)
    return found


def _names_a_derived_artifact(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id in DERIVED_NAME_IDENTIFIERS:
            return True
        if isinstance(sub, ast.Constant) and sub.value in DERIVED_FILE_NAMES:
            return True
    return False


def _derived_path_locals(scope: ast.AST, path_functions: set[str]) -> set[str]:
    """Names assigned from one of those functions INSIDE one scope
    (``glb_path = self.tunnel_glb_path(scenario_id)``). Per-function, not
    per-module: ``design_service`` binds the name ``path`` from a derived
    path helper in one writer and from ``derived / file.name`` in the
    cascade, and a module-wide map would confuse the two."""
    found: set[str] = set()
    for node in ast.walk(scope):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        func = node.value.func
        called = func.attr if isinstance(func, ast.Attribute) else None
        if called is None and isinstance(func, ast.Name):
            called = func.id
        if called not in path_functions:
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                found.add(target.id)
    return found


def _enclosing_function_node(tree: ast.AST, node: ast.AST) -> ast.AST:
    """The innermost enclosing ``def`` NODE of ``node`` (module when none)."""
    best: ast.AST = tree
    for candidate in ast.walk(tree):
        if isinstance(candidate, ast.FunctionDef | ast.AsyncFunctionDef):
            end = getattr(candidate, "end_lineno", candidate.lineno)
            if candidate.lineno <= getattr(node, "lineno", 0) <= end:
                best = candidate
    return best


def _enclosing_function(tree: ast.AST, node: ast.AST) -> str:
    """The nearest enclosing ``def`` name of ``node`` (for the allowlist)."""
    best = "<module>"
    for candidate in ast.walk(tree):
        if isinstance(candidate, ast.FunctionDef | ast.AsyncFunctionDef):
            end = getattr(candidate, "end_lineno", candidate.lineno)
            start = candidate.lineno
            if start <= getattr(node, "lineno", 0) <= end:
                best = candidate.name
    return best


def test_no_module_outside_the_read_authority_reads_an_artifact_file() -> None:
    offenders: list[str] = []
    for module in _modules():
        if module.name == READ_AUTHORITY:
            continue
        tree = ast.parse(module.read_text(encoding="utf-8"))
        allowed = _allowed_reads(module)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            if name not in READ_CALLS:
                continue
            where = _enclosing_function(tree, node)
            if where in allowed:
                continue
            offenders.append(f"{module}:{node.lineno} {where}() calls {name}()")
    assert offenders == [], offenders


def test_no_module_outside_the_read_authority_parses_a_file_it_read() -> None:
    """``json.loads(path.read_text(...))`` — the exact expression the 21
    duplicate readers used (Stage A §1) — exists nowhere but the authority and
    the scenario document."""
    offenders: list[str] = []
    for module in _modules():
        if module.name == READ_AUTHORITY:
            continue
        tree = ast.parse(module.read_text(encoding="utf-8"))
        allowed = _allowed_reads(module)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "loads" or not node.args:
                continue
            arg = node.args[0]
            if not isinstance(arg, ast.Call) or not isinstance(arg.func, ast.Attribute):
                continue
            if arg.func.attr not in READ_CALLS:
                continue
            if _enclosing_function(tree, node) in allowed:
                continue
            offenders.append(f"{module}:{node.lineno}")
    assert offenders == [], offenders


def test_the_scan_is_not_empty() -> None:
    """An empty glob makes every ``assert offenders == []`` above vacuously
    true. The scan is anchored on this file and its size is pinned."""
    modules = _modules()
    assert len(modules) >= MINIMUM_SCANNED_MODULES, [m.name for m in modules]
    # the two packages the pre-S15 scan covered …
    assert {
        "artifact_reader.py",
        "design_service.py",
        "world_service.py",
        "effective_ramp.py",
        "infrastructure_service.py",
        "design.py",
        "world.py",
        "network.py",
        "infrastructure.py",
    } <= {m.name for m in modules}
    # … and one module from every sub-package that used to be outside it
    by_package = {m.parent.name for m in modules}
    assert {
        "layout",
        "design",
        "world",
        "network",
        "levels",
        "capability",
        "shafts",
        "regression",
        "core",
    } <= by_package, sorted(by_package)
    assert READ_AUTHORITY in {m.name for m in modules}
    # and the detector's vocabulary is the registry's, not a hand list
    assert len(DERIVED_FILE_NAMES) == 19
    assert {"LAYOUT_V2_ARTIFACT", "TUNNEL_MESH_GLB", "RAMP_SOURCE_FILE"} <= DERIVED_NAME_IDENTIFIERS


def _is_derived_expression(
    node: ast.AST | None, path_functions: set[str], path_locals: set[str]
) -> bool:
    """One EXPRESSION that denotes a derived-artifact path: a constant / name
    the registry declares, a local bound from a derived-path helper, or a call
    to one of those helpers."""
    if node is None:
        return False
    if _names_a_derived_artifact(node):
        return True
    if isinstance(node, ast.Name) and node.id in path_locals:
        return True
    if isinstance(node, ast.Call):
        called = node.func
        name = called.attr if isinstance(called, ast.Attribute) else None
        if name is None and isinstance(called, ast.Name):
            name = called.id
        if name in path_functions:
            return True
    return False


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _presence_offenders(module_name: str, source: str) -> list[str]:
    """Every presence probe of a derived-artifact path in one module, minus
    the explicitly allowed WRITE-side cleanups.

    S15: a probe is flagged whether the path is the RECEIVER
    (``p.is_file()``, ``p.stat()``) or an ARGUMENT
    (``os.path.exists(p)``, ``os.path.getsize(p)``) — the module-function
    spellings have ``os.path`` as their receiver and were invisible to a
    receiver-only detector."""
    tree = ast.parse(source)
    path_functions = _derived_path_functions(tree)
    allowed = ALLOWED_PRESENCE_PROBES.get(module_name, ())
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = _call_name(node)
        if called not in PRESENCE_CALLS:
            continue
        path_locals = _derived_path_locals(_enclosing_function_node(tree, node), path_functions)
        candidates: list[ast.AST] = list(node.args)
        if isinstance(node.func, ast.Attribute):
            candidates.append(node.func.value)
        probes_derived = any(
            _is_derived_expression(candidate, path_functions, path_locals)
            for candidate in candidates
        )
        if not probes_derived or _enclosing_function(tree, node) in allowed:
            continue
        offenders.append(
            f"{module_name}:{node.lineno} {_enclosing_function(tree, node)}() probes {called}()"
        )
    return offenders


def test_no_module_outside_the_read_authority_probes_an_artifact_for_presence() -> None:
    """``is_file`` / ``exists`` on a derived-artifact path is a read decision
    and belongs to the authority; the only exceptions are the two WRITE-side
    GLB cleanups, named explicitly in ``ALLOWED_PRESENCE_PROBES``."""
    offenders: list[str] = []
    for module in _modules():
        if module.name == READ_AUTHORITY:
            continue
        offenders += _presence_offenders(module.name, module.read_text(encoding="utf-8"))
    assert offenders == [], offenders


#: the probe C3 removed, transcribed from ``design_service._layout_object``
#: before the change, beside the two shapes that must NOT be flagged: the
#: allowlisted WRITE-side GLB cleanup and the cascade's registry-driven
#: ``derived / file.name`` unlink, which binds the same local name ``path``
#: that a writer binds from a path helper. A scanner that flags nothing is
#: not a proof (§29).
REMOVED_PROBE_SOURCE = "\n".join(
    (
        "from minegen.core.artifacts import LAYOUT_V2_ARTIFACT",
        "",
        "",
        "class Fake:",
        "    def layout_path(self, sid):",
        "        return self.store.derived_dir(sid) / LAYOUT_V2_ARTIFACT",
        "",
        "    def tunnel_glb_path(self, sid):",
        "        return self.store.derived_dir(sid) / 'tunnel_mesh.glb'",
        "",
        "    def _layout_object(self, sid):",
        "        if not self.layout_path(sid).is_file():",
        "            raise RuntimeError",
        "",
        "    def generate_tunnel(self, sid):",
        "        glb_path = self.tunnel_glb_path(sid)",
        "        if glb_path.exists():",
        "            glb_path.unlink()",
        "",
        "    def _invalidate_downstream(self, derived, file):",
        "        path = derived / file.name",
        "        if path.exists():",
        "            path.unlink()",
    )
)

#: S15's positive control: the four spellings a RECEIVER-only detector with
#: the ``{is_file, exists}`` vocabulary could not see. Each names a derived
#: artifact as a call ARGUMENT (``os.path.*``) or takes the rule-60 stat /
#: a glob directly off a derived path.
WIDENED_PROBE_SOURCE = "\n".join(
    (
        "import os",
        "from minegen.core.artifacts import LAYOUT_V2_ARTIFACT",
        "",
        "",
        "class Fake:",
        "    def layout_path(self, sid):",
        "        return self.store.derived_dir(sid) / LAYOUT_V2_ARTIFACT",
        "",
        "    def a(self, sid):",
        "        return os.path.exists(self.layout_path(sid))",
        "",
        "    def b(self, sid):",
        "        return os.path.isfile(self.layout_path(sid))",
        "",
        "    def c(self, sid):",
        "        return os.path.getsize(self.layout_path(sid))",
        "",
        "    def d(self, sid):",
        "        return self.layout_path(sid).stat().st_size",
        "",
        "    def e(self, derived):",
        "        return sorted(derived.glob(LAYOUT_V2_ARTIFACT))",
    )
)


def test_the_presence_detector_sees_the_probe_it_was_written_for() -> None:
    offenders = _presence_offenders("design_service.py", REMOVED_PROBE_SOURCE)
    assert offenders == ["design_service.py:12 _layout_object() probes is_file()"], offenders


def test_the_presence_detector_sees_the_four_spellings_s15_added() -> None:
    """A widened vocabulary that flags nothing new is not a widening (§29).
    Each of these is a presence decision about a derived artifact that the
    pre-S15 detector reported as clean."""
    offenders = _presence_offenders("design_service.py", WIDENED_PROBE_SOURCE)
    assert offenders == [
        "design_service.py:10 a() probes exists()",
        "design_service.py:13 b() probes isfile()",
        "design_service.py:16 c() probes getsize()",
        "design_service.py:19 d() probes stat()",
        "design_service.py:22 e() probes glob()",
    ], offenders


def test_the_removed_duplicate_readers_are_gone() -> None:
    """The named removals of commit 2: a duplicate raw reader, a dead one and
    the private loader of the ramp resolution."""
    from minegen.services import design_service, effective_ramp

    for gone in ("targets_if_present", "_layout_selected_if_present"):
        assert not hasattr(design_service.DesignService, gone), gone
    assert not hasattr(effective_ramp, "_load")


def test_read_specs_are_exactly_the_registered_derived_artifacts() -> None:
    registered = {a.name for a in derived_artifacts()}
    assert set(READ_SPECS) == registered
    assert RAMP_SOURCE_FILE in registered


def test_the_scene_assembles_every_registered_derived_artifact() -> None:
    """No registered artifact is silently left out of the scene: the 13 direct
    slots plus the four the Effective Ramp resolution and the layout view own
    (``layout_v2.json`` → ``layoutV2``, ``layout_v2_selected.json`` →
    ``layoutV2Selected`` and the ramp payload, ``level_accesses.json`` →
    ``levelAccesses``, ``ramp_source.json`` → ``rampSource``)."""
    from minegen.core.artifacts import (
        LAYOUT_V2_ARTIFACT,
        LAYOUT_V2_SELECTED_ARTIFACT,
        LEVEL_ACCESSES_ARTIFACT,
    )

    assembled = {name for _, name in SCENE_SLOTS} | {
        LAYOUT_V2_ARTIFACT,
        LAYOUT_V2_SELECTED_ARTIFACT,
        LEVEL_ACCESSES_ARTIFACT,
        RAMP_SOURCE_FILE,
    }
    assert assembled == set(READ_SPECS)
    assert len(SCENE_SLOTS) == 13
