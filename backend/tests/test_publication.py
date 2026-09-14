"""AC-01F.2 D1/D2 — the publication helper and the WRITE-side static proof.

Two halves, both FAST:

* the SEMANTICS of :mod:`minegen.core.publication` — the temp-sibling name,
  its exclusive (``O_CREAT | O_EXCL``) creation, the fsync of the written
  handle, the ``os.replace``, the exception path (temp removed, target
  untouched or still absent), the ignored directory fsync, and an NPZ that
  round-trips byte-identically to a direct ``np.savez_compressed`` of the
  same arrays;
* the mechanical proof that no raw persistence write survives outside that
  module (the ``tests/test_no_raw_artifact_reads.py`` pattern, mirrored on
  the WRITE side): ``write_text`` / ``write_bytes`` / ``np.savez*`` /
  write-mode ``open`` exist in the production package only inside
  ``core/publication.py``, with the ``regression/`` REPORT writers
  allowlisted by SRC-relative path — they write the rule-132 regression
  reports under ``backend/golden/``, never a persisted scenario artifact.

Stage A §7.1 measured 22 in-place write sites, ``os.replace`` = 0,
``fsync`` = 0, temp files = 0. This file is the "0 remaining" side of that
measurement.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from minegen.core import publication
from minegen.core.publication import publish_bytes, publish_npz, publish_text

# --------------------------------------------------------------------------- #
# D1 — helper semantics
# --------------------------------------------------------------------------- #


def _temps(directory: Path) -> list[Path]:
    return sorted(p for p in directory.iterdir() if ".tmp" in p.name)


def test_publish_text_writes_the_bytes_and_leaves_no_temp(tmp_path: Path) -> None:
    target = tmp_path / "stopes.json"
    publish_text(target, json.dumps({"a": 1}))
    assert target.read_bytes() == b'{"a": 1}'
    assert _temps(tmp_path) == []


def test_publish_text_encodes_utf8_by_default_like_every_migrated_call_site(
    tmp_path: Path,
) -> None:
    target = tmp_path / "scenario.json"
    publish_text(target, "µ—ok")
    assert target.read_bytes() == "µ—ok".encode()


def test_publish_bytes_replaces_an_existing_target(tmp_path: Path) -> None:
    target = tmp_path / "tunnel_mesh.glb"
    target.write_bytes(b"old")
    publish_bytes(target, b"new-and-longer")
    assert target.read_bytes() == b"new-and-longer"
    assert _temps(tmp_path) == []


def test_the_temp_sibling_name_pattern_and_directory(tmp_path: Path, monkeypatch) -> None:
    """``.<final name>.<8 random hex>.tmp`` in the TARGET's own directory —
    the same filesystem, which ``os.replace`` requires. Captured from inside
    the write, because a successful publication consumes the temp."""
    seen: list[Path] = []
    real_replace = os.replace

    def spy(src: Any, dst: Any) -> None:
        seen.append(Path(src))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    target = tmp_path / "derived" / "levels.json"
    target.parent.mkdir()
    publish_text(target, "{}")
    assert len(seen) == 1
    temp = seen[0]
    assert temp.parent == target.parent
    assert temp.name.startswith(".levels.json.")
    assert temp.name.endswith(".tmp")
    token = temp.name[len(".levels.json.") : -len(".tmp")]
    assert len(token) == 8 and all(c in "0123456789abcdef" for c in token)


def test_the_npz_temp_sibling_ends_in_npz(tmp_path: Path, monkeypatch) -> None:
    """numpy appends ``.npz`` to a PATH that does not end in it; the temp
    name carries the suffix so the name stays honest either way."""
    seen: list[Path] = []
    real_replace = os.replace

    def spy(src: Any, dst: Any) -> None:
        seen.append(Path(src))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    publish_npz(tmp_path / "arrays.npz", a=np.arange(3, dtype=np.float64))
    assert seen[0].name.startswith(".arrays.npz.")
    assert seen[0].name.endswith(".tmp.npz")


def test_the_written_handle_is_fsynced_and_then_replaced(tmp_path: Path, monkeypatch) -> None:
    """Order and completeness: the data fd is fsynced BEFORE the replace, and
    the directory fsync follows it."""
    events: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(fd: int) -> None:
        events.append("fsync-dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "fsync-file")
        real_fsync(fd)

    def replace(src: Any, dst: Any) -> None:
        events.append("replace")
        real_replace(src, dst)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "replace", replace)
    publish_text(tmp_path / "network.json", "{}")
    assert events == ["fsync-file", "replace", "fsync-dir"]


def test_npz_is_fsynced_and_replaced_too(tmp_path: Path, monkeypatch) -> None:
    events: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(fd: int) -> None:
        events.append("fsync-dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "fsync-file")
        real_fsync(fd)

    def replace(src: Any, dst: Any) -> None:
        events.append("replace")
        real_replace(src, dst)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "replace", replace)
    publish_npz(tmp_path / "arrays.npz", a=np.arange(3, dtype=np.float64))
    assert events == ["fsync-file", "replace", "fsync-dir"]


@pytest.mark.parametrize("failing", ["replace", "fsync", "write"])
def test_a_failure_leaves_the_previous_target_byte_identical_and_no_temp(
    tmp_path: Path, monkeypatch, failing: str
) -> None:
    target = tmp_path / "decline_smoothed.json"
    target.write_bytes(b'{"status": "SUCCESS"}')
    before = target.read_bytes()
    before_stat = os.stat(target)
    _inject(monkeypatch, failing)
    with pytest.raises(OSError):
        publish_text(target, json.dumps({"status": "REPLACED"}))
    assert target.read_bytes() == before
    assert os.stat(target).st_mtime_ns == before_stat.st_mtime_ns
    assert _temps(tmp_path) == []


@pytest.mark.parametrize("failing", ["replace", "fsync", "write"])
def test_a_failure_leaves_an_absent_target_absent_and_no_temp(
    tmp_path: Path, monkeypatch, failing: str
) -> None:
    target = tmp_path / "timeline.json"
    _inject(monkeypatch, failing)
    with pytest.raises(OSError):
        publish_text(target, json.dumps({"status": "SUCCESS"}))
    assert not target.exists()
    assert _temps(tmp_path) == []


@pytest.mark.parametrize("failing", ["replace", "fsync", "write"])
def test_an_npz_failure_leaves_the_previous_arrays_and_no_temp(
    tmp_path: Path, monkeypatch, failing: str
) -> None:
    """The NPZ path has the same contract, and its temp is removed even
    though ``np.savez_compressed`` owns the writing."""
    target = tmp_path / "arrays.npz"
    publish_npz(target, a=np.arange(4, dtype=np.float64))
    before = target.read_bytes()
    _inject(monkeypatch, failing)
    with pytest.raises(OSError):
        publish_npz(target, a=np.arange(400, dtype=np.float64))
    assert target.read_bytes() == before
    assert _temps(tmp_path) == []
    with np.load(target) as loaded:
        assert loaded["a"].tolist() == [0.0, 1.0, 2.0, 3.0]


def _inject(monkeypatch: pytest.MonkeyPatch, failing: str) -> None:
    """The three D5.1 faults, applied to the PUBLICATION only: a raising
    ``os.replace``, a raising ``os.fsync`` of the data fd (the directory
    fsync stays real — it is best effort), and a truncating temp write."""
    if failing == "replace":
        real = os.replace

        def replace(src: Any, dst: Any) -> None:
            if ".tmp" in Path(src).name:
                raise OSError(5, "injected: os.replace failed")
            real(src, dst)

        monkeypatch.setattr(os, "replace", replace)
        return
    if failing == "fsync":
        real_fsync = os.fsync

        def fsync(fd: int) -> None:
            if not stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError(5, "injected: os.fsync failed")
            real_fsync(fd)

        monkeypatch.setattr(os, "fsync", fsync)
        return
    _inject_truncating_write(monkeypatch)


def _inject_truncating_write(monkeypatch: pytest.MonkeyPatch) -> None:
    """Truncate the FIRST write to a temp sibling and then raise — the "short
    write" of a crashing writer.

    The temp file is created ``os.open(..., O_WRONLY|O_CREAT|O_EXCL)`` and
    wrapped in ``os.fdopen``, so the hook is on those two: ``os.open``
    records the fd of a temp sibling by NAME, ``os.fdopen`` wraps exactly
    that fd's handle. Every other path is delegated untouched, so the
    surrounding test machinery is unaffected."""
    real_os_open, real_fdopen = os.open, os.fdopen
    temp_fds: set[int] = set()

    class _Truncating:
        def __init__(self, handle: Any) -> None:
            self._handle = handle
            self._written = 0

        def write(self, data: Any) -> int:
            if self._written == 0 and len(data) > 1:
                self._handle.write(data[: len(data) // 2])
                self._written += 1
                raise OSError(28, "injected: short write on the temp sibling")
            self._written += 1
            return int(self._handle.write(data))

        def __getattr__(self, name: str) -> Any:
            return getattr(self._handle, name)

        def __enter__(self) -> _Truncating:
            self._handle.__enter__()
            return self

        def __exit__(self, *exc: Any) -> Any:
            return self._handle.__exit__(*exc)

    def opener(file: Any, *args: Any, **kwargs: Any) -> int:
        fd = real_os_open(file, *args, **kwargs)
        name = Path(str(file)).name
        if ".tmp" in name and name.startswith("."):
            temp_fds.add(fd)
        return fd

    def fdopen(fd: int, *args: Any, **kwargs: Any) -> Any:
        handle = real_fdopen(fd, *args, **kwargs)
        return _Truncating(handle) if fd in temp_fds else handle

    monkeypatch.setattr(os, "open", opener)
    monkeypatch.setattr(os, "fdopen", fdopen)


def test_a_temp_name_collision_raises_and_leaves_the_target_untouched(
    tmp_path: Path, monkeypatch
) -> None:
    """The temp is created ``O_CREAT | O_EXCL``, so a pre-existing file at
    that name — the 2**-32 token collision, or residue of a crashed
    publication — is an error rather than a silently shared file. The token
    generator is pinned to force the collision that randomness makes
    unobservable.

    What propagates is ``FileExistsError`` (an ``OSError``), and the TARGET
    is untouched — the helper never got as far as the replace. The ordinary
    exception path then removes the file at the temp name; that is
    deliberate (the name belongs to this module alone), not an accident."""
    from types import SimpleNamespace

    monkeypatch.setattr(publication, "secrets", SimpleNamespace(token_hex=lambda n: "deadbeef"))
    target = tmp_path / "stopes.json"
    target.write_bytes(b'{"status": "SUCCESS"}')
    before = target.read_bytes()
    before_stat = os.stat(target)
    collision = tmp_path / ".stopes.json.deadbeef.tmp"
    collision.write_bytes(b"residue of a crashed publication")

    with pytest.raises(FileExistsError):
        publish_text(target, json.dumps({"status": "REPLACED"}))

    assert target.read_bytes() == before
    assert os.stat(target).st_mtime_ns == before_stat.st_mtime_ns
    assert _temps(tmp_path) == []  # the exception path removed the collision


def test_a_temp_name_collision_on_an_absent_target_leaves_it_absent(
    tmp_path: Path, monkeypatch
) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(publication, "secrets", SimpleNamespace(token_hex=lambda n: "deadbeef"))
    target = tmp_path / "arrays.npz"
    (tmp_path / ".arrays.npz.deadbeef.tmp.npz").write_bytes(b"residue")
    with pytest.raises(FileExistsError):
        publish_npz(target, a=np.arange(3, dtype=np.float64))
    assert not target.exists()
    assert _temps(tmp_path) == []


def test_a_directory_fsync_failure_is_ignored(tmp_path: Path, monkeypatch) -> None:
    """Some platforms and filesystems refuse a directory fsync; the file is
    already published when it is attempted, so the publication stands."""
    real_fsync = os.fsync
    attempted: list[bool] = []

    def fsync(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            attempted.append(True)
            raise OSError(22, "injected: directory fsync refused")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fsync)
    target = tmp_path / "communication.json"
    publish_text(target, "{}")
    assert attempted == [True]
    assert target.read_bytes() == b"{}"
    assert _temps(tmp_path) == []


def test_a_missing_parent_directory_is_the_callers_problem(tmp_path: Path) -> None:
    """The helper never creates a directory (D1 step 1): callers keep their
    own ``mkdir``."""
    with pytest.raises(OSError):
        publish_text(tmp_path / "nope" / "levels.json", "{}")
    assert not (tmp_path / "nope").exists()


def test_publish_npz_bytes_equal_a_direct_savez_compressed(tmp_path: Path) -> None:
    """Only the DESTINATION of the serializer moved (D1): the published NPZ
    is byte-identical to ``np.savez_compressed`` of the same arrays, and
    ``np.load`` round-trips it."""
    arrays = {
        "rock_quality": np.linspace(0.0, 1.0, 512).reshape(8, 8, 8),
        "terrain_meta": np.array([1.0, 2.0, 3.0], dtype=np.float64),
        "lattice": np.arange(24, dtype=np.int64).reshape(2, 3, 4),
    }
    direct = tmp_path / "direct.npz"
    np.savez_compressed(direct, **arrays)
    published = tmp_path / "arrays.npz"
    publish_npz(published, **arrays)
    assert hashlib.sha256(published.read_bytes()).hexdigest() == (
        hashlib.sha256(direct.read_bytes()).hexdigest()
    )
    with np.load(published) as loaded:
        assert sorted(loaded.files) == ["lattice", "rock_quality", "terrain_meta"]
        for key, value in arrays.items():
            assert np.array_equal(loaded[key], value)


def test_publication_is_a_leaf_importing_stdlib_and_numpy_only() -> None:
    source = Path(publication.__file__).read_text(encoding="utf-8")
    imported = {
        node.module.split(".")[0] if isinstance(node, ast.ImportFrom) and node.module else None
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
    } | {
        alias.name.split(".")[0]
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert imported <= {"__future__", "contextlib", "os", "secrets", "pathlib", "typing", "numpy"}
    assert "minegen" not in imported


def test_every_publication_is_a_new_stat_identity(tmp_path: Path) -> None:
    """Rule 60 is unchanged in semantics: ``os.replace`` installs the temp
    file's inode, so a byte-identical republication is still a new revision
    (the identity is ``name:size:mtime_ns``)."""
    from minegen.core.revision import file_revision

    target = tmp_path / "targets.json"
    publish_text(target, "{}")
    first = file_revision(target)
    os.utime(target, ns=(0, 0))  # force a distinguishable previous mtime
    publish_text(target, "{}")
    assert file_revision(target) != first
    assert target.read_bytes() == b"{}"


# --------------------------------------------------------------------------- #
# D2 — the static proof: no raw persistence write outside this module
# --------------------------------------------------------------------------- #

#: anchored on THIS file, never on the process working directory (the §29
#: lesson of ``tests/test_no_raw_artifact_reads.py``: an empty glob asserts
#: ``[] == []``)
SRC = Path(__file__).resolve().parents[1] / "src" / "minegen"
#: measured at AC-01F.2: 109 modules under ``src/minegen``
MINIMUM_SCANNED_MODULES = 100

#: the ONE module allowed to write a persisted file
WRITE_AUTHORITY = "core/publication.py"

#: every spelling that PUTS BYTES on disk by NAME. The first four are the
#: pre-AC-01F.2 sites of Stage A §7.1; the rest are spellings that do not
#: occur today and must not appear tomorrow either — the proof stays closed
#: against a future writer that reaches for ``np.save``, ``ndarray.tofile``
#: or ``Path.touch`` instead.
WRITE_CALLS = frozenset(
    {
        "write_text",
        "write_bytes",
        "savez",
        "savez_compressed",
        "save",
        "savetxt",
        "tofile",
        "writelines",
        "touch",
    }
)
#: ``shutil``'s file-installing calls. They are flagged ONLY when the call is
#: ``shutil.<name>(...)`` or a bare ``<name>(...)`` imported from it: the bare
#: attribute ``copy`` is ``ndarray.copy`` / ``list.copy`` many dozens of times
#: in the engineering modules and is not a persistence write.
SHUTIL_WRITE_CALLS = frozenset({"copy", "copyfile", "copy2", "move"})
#: a write-mode ``open`` is the same write by another spelling
WRITE_MODES = frozenset({"w", "a", "x", "+"})

#: the ``regression/`` REPORT writers, by SRC-relative path and function —
#: ``python -m minegen.regression`` writes its own baselines and audits under
#: ``backend/golden/`` (rule 132), which are not persisted scenario artifacts
#: and are on no API path. The same allowlist shape as the READ proof's, so a
#: new writer anywhere else in those modules still fails this test.
ALLOWED_WRITES: dict[str, tuple[str, ...]] = {
    "regression/golden.py": ("write_report",),
    "regression/layout_v2.py": ("write_report",),
    "regression/warped_vein.py": ("write_report",),
    "regression/repool.py": ("main",),
    "regression/bench.py": ("main",),
    "regression/__main__.py": ("main",),
}


def _modules() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _is_shutil_write(node: ast.Call) -> bool:
    """``shutil.copy/copyfile/copy2/move(...)`` — or the same name called
    bare, as ``from shutil import move`` would spell it. An attribute call on
    anything else (``array.copy()``) is not a persistence write."""
    name = _call_name(node)
    if name not in SHUTIL_WRITE_CALLS:
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return True
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "shutil"
    )


def _is_write_open(node: ast.Call) -> bool:
    """``open(path, "w")`` / ``path.open("wb")`` / ``open(p, mode="a")`` —
    a write-mode open, whichever spelling. A ``mode`` that is not a literal
    is treated as a write (conservative: the proof must not be dodged by
    computing the mode)."""
    if _call_name(node) != "open":
        return False
    receiver_is_path = isinstance(node.func, ast.Attribute)
    index = 0 if receiver_is_path else 1
    mode: ast.expr | None = None
    if len(node.args) > index:
        mode = node.args[index]
    for keyword in node.keywords:
        if keyword.arg == "mode":
            mode = keyword.value
    if mode is None:
        return False  # the default mode is "r"
    if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
        return any(character in WRITE_MODES for character in mode.value)
    return True


def _enclosing_function(tree: ast.AST, node: ast.AST) -> str:
    best = "<module>"
    for candidate in ast.walk(tree):
        if isinstance(candidate, ast.FunctionDef | ast.AsyncFunctionDef):
            end = getattr(candidate, "end_lineno", candidate.lineno)
            if candidate.lineno <= getattr(node, "lineno", 0) <= end:
                best = candidate.name
    return best


def _write_offenders(module_name: str, source: str, allowed: tuple[str, ...] = ()) -> list[str]:
    tree = ast.parse(source)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name not in WRITE_CALLS and not _is_shutil_write(node) and not _is_write_open(node):
            continue
        where = _enclosing_function(tree, node)
        if where in allowed:
            continue
        offenders.append(f"{module_name}:{node.lineno} {where}() calls {name}()")
    return offenders


def test_no_module_outside_the_write_authority_writes_a_persisted_file() -> None:
    """Stage A §7.1's 22 in-place ``write_text`` / ``write_bytes`` /
    ``np.savez_compressed`` sites are 0 outside ``core/publication.py``."""
    offenders: list[str] = []
    for module in _modules():
        relative = module.relative_to(SRC).as_posix()
        if relative == WRITE_AUTHORITY:
            continue
        offenders += _write_offenders(
            relative, module.read_text(encoding="utf-8"), ALLOWED_WRITES.get(relative, ())
        )
    assert offenders == [], offenders


def test_every_write_allowlist_key_names_exactly_one_scanned_module() -> None:
    scanned = {m.relative_to(SRC).as_posix() for m in _modules()}
    missing = sorted(k for k in ALLOWED_WRITES if k not in scanned)
    assert missing == [], missing
    assert WRITE_AUTHORITY in scanned


def test_the_write_scan_is_not_empty() -> None:
    modules = _modules()
    assert len(modules) >= MINIMUM_SCANNED_MODULES, [m.name for m in modules]
    relative = {m.relative_to(SRC).as_posix() for m in modules}
    assert {
        "services/design_service.py",
        "services/world_service.py",
        "services/scenario_service.py",
        "services/infrastructure_service.py",
        "services/effective_ramp.py",
        "core/publication.py",
    } <= relative


#: the positive control (§29): a scanner that flags nothing is not a proof.
#: These are the five spellings of the pre-AC-01F.2 write sites, transcribed
#: from Stage A §7.1 — the ones this test exists to keep from coming back.
REMOVED_WRITE_SOURCE = "\n".join(
    (
        "import json",
        "import numpy as np",
        "",
        "",
        "class Fake:",
        "    def generate_stopes(self, path, serialized):",
        '        path.write_text(serialized, encoding="utf-8")',
        "",
        "    def generate_tunnel(self, glb_path, glb):",
        "        glb_path.write_bytes(glb)",
        "",
        "    def _save(self, path, fields):",
        "        np.savez_compressed(path, **fields)",
        "",
        "    def report(self, path, text):",
        '        with open(path, "w", encoding="utf-8") as fh:',
        "            fh.write(text)",
        "",
        "    def csv(self, path, rows):",
        '        with path.open("wb") as fh:',
        "            fh.write(rows)",
    )
)

#: the shapes that must NOT be flagged: a READ open (default mode and an
#: explicit "rb"), and the publication helper's own calls when the module is
#: the authority (checked by skipping the authority, above).
CLEAN_READ_SOURCE = "\n".join(
    (
        "class Fake:",
        "    def a(self, path):",
        "        return open(path).read()",
        "",
        "    def b(self, path):",
        '        return open(path, "rb").read()',
        "",
        "    def c(self, path):",
        '        return path.open("r").read()',
    )
)


def test_the_write_detector_sees_every_spelling_it_was_written_for() -> None:
    offenders = _write_offenders("fake.py", REMOVED_WRITE_SOURCE)
    assert offenders == [
        "fake.py:7 generate_stopes() calls write_text()",
        "fake.py:10 generate_tunnel() calls write_bytes()",
        "fake.py:13 _save() calls savez_compressed()",
        "fake.py:16 report() calls open()",
        "fake.py:20 csv() calls open()",
    ], offenders


def test_the_write_detector_does_not_flag_a_read_open() -> None:
    assert _write_offenders("fake.py", CLEAN_READ_SOURCE) == []


#: the spellings that do NOT occur at AC-01F.2 and are guarded against
#: anyway (the write-proof vocabulary amendment). A scanner that only knows
#: yesterday's five spellings is not closed against tomorrow's writer.
FUTURE_WRITE_SOURCE = "\n".join(
    (
        "import numpy as np",
        "import shutil",
        "",
        "",
        "class Fake:",
        "    def a(self, path, arr):",
        "        np.save(path, arr)",
        "",
        "    def b(self, path, arr):",
        "        np.savetxt(path, arr)",
        "",
        "    def c(self, path, arr):",
        "        arr.tofile(path)",
        "",
        "    def d(self, handle, lines):",
        "        handle.writelines(lines)",
        "",
        "    def e(self, path):",
        "        path.touch()",
        "",
        "    def f(self, src, dst):",
        "        shutil.copy(src, dst)",
        "",
        "    def g(self, src, dst):",
        "        shutil.copyfile(src, dst)",
        "",
        "    def h(self, src, dst):",
        "        shutil.copy2(src, dst)",
        "",
        "    def i(self, src, dst):",
        "        shutil.move(src, dst)",
        "",
        "    def j(self, src, dst):",
        "        move(src, dst)",
    )
)

#: the shape the shutil half must NOT flag: ``ndarray.copy()`` is the single
#: most common call in the engineering modules (26 sites at AC-01F.2) and
#: puts no byte on disk.
CLEAN_ARRAY_COPY_SOURCE = "\n".join(
    (
        "class Fake:",
        "    def a(self, points):",
        "        return points[::-1].copy()",
        "",
        "    def b(self, controls):",
        "        out = controls.copy()",
        "        return out",
    )
)


def test_the_write_detector_sees_the_future_spellings_too() -> None:
    offenders = _write_offenders("fake.py", FUTURE_WRITE_SOURCE)
    assert offenders == [
        "fake.py:7 a() calls save()",
        "fake.py:10 b() calls savetxt()",
        "fake.py:13 c() calls tofile()",
        "fake.py:16 d() calls writelines()",
        "fake.py:19 e() calls touch()",
        "fake.py:22 f() calls copy()",
        "fake.py:25 g() calls copyfile()",
        "fake.py:28 h() calls copy2()",
        "fake.py:31 i() calls move()",
        "fake.py:34 j() calls move()",
    ], offenders


def test_the_write_detector_does_not_flag_an_array_copy() -> None:
    assert _write_offenders("fake.py", CLEAN_ARRAY_COPY_SOURCE) == []


def test_the_production_package_has_no_os_replace_outside_the_authority() -> None:
    """The counterpart of Stage A's ``os.replace = 0``: exactly one module
    performs the atomic rename now, and it is the authority."""
    users: list[str] = []
    for module in _modules():
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node) == "replace":
                func = node.func
                if (
                    isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "os"
                ):
                    users.append(module.relative_to(SRC).as_posix())
    assert sorted(set(users)) == [WRITE_AUTHORITY], sorted(set(users))
