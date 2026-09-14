"""AC-01F.2 D5.1 — every write site, under an injected publication failure.

For EACH of the 22 persistence write sites Stage A §7.1 measured (the table
below carries each one's ``file:line`` provenance at 450f9df, the commit
this change is based on), the REAL writer is driven three times through the
real service stack with one fault injected into its publication:

    replace   ``os.replace`` of THAT target raises OSError
    fsync     ``os.fsync`` of THAT target's temp handle raises OSError
    write     the first write to THAT target's temp sibling is TRUNCATED
              and then raises OSError

and after each injected failure:

* the previous target is byte-identical (or still absent) — before this
  change an in-place ``write_text`` / ``write_bytes`` /
  ``np.savez_compressed`` left a TORN file on disk instead;
* no ``*.tmp*`` sibling remains anywhere in the scenario directory;
* the exception propagates as the OSError-class failure it has always been
  (no new error code is minted; ``test_the_route_answer_for_an_io_fault_is
  _the_unmapped_500`` records the route answer, which is the unmapped 500 an
  I/O fault has always produced);
* the invalidation cascade did NOT run and every other persisted file is
  byte-identical — with ONE declared exception per pair site, the file the
  D3 order publishes FIRST (``level_accesses.json`` before the selection,
  the GLB before its report), which is recorded per row in ``co_published``.

The stacks are module-scoped and are driven 66 times (22 sites × 3 faults);
every case restores
the whole scenario directory (bytes AND ``st_mtime_ns``, the Stage A C-12
lesson) so no case can contaminate the next, and every case asserts that
the injector actually FIRED — a fault that never fires would make the whole
table vacuous (§29).
"""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from minegen.core.models import ScenarioCreate
from tests.test_artifact_read_api import API, Stack, _build

# --------------------------------------------------------------------------- #
# the 22 sites (Stage A §7.1, verbatim, with the 450f9df line numbers)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Site:
    number: int
    origin: str  # file:line at 450f9df, before the migration
    file: str  # the published file name
    stack: str  # the fixture that owns a stack able to drive it
    driver: str  # the DRIVERS key
    co_published: tuple[str, ...] = ()  # files the D3 order publishes BEFORE it


SITES: tuple[Site, ...] = (
    Site(1, "design_service.py:429", "targets.json", "legacy", "targets"),
    Site(2, "design_service.py:496", "decline.json", "legacy", "decline"),
    Site(3, "design_service.py:557", "decline_smoothed.json", "legacy", "smoothed"),
    Site(4, "design_service.py:602", "layout_v2.json", "layout_v2", "layout"),
    Site(
        5,
        "design_service.py:721",
        "layout_v2_selected.json",
        "layout_v2",
        "select",
        ("level_accesses.json",),
    ),
    Site(6, "design_service.py:722", "level_accesses.json", "layout_v2", "select"),
    Site(7, "design_service.py:1000", "levels.json", "legacy", "levels"),
    Site(8, "design_service.py:1050", "stopes.json", "legacy", "stopes"),
    Site(9, "design_service.py:1100", "timeline.json", "legacy", "timeline"),
    Site(10, "design_service.py:1151", "shafts.json", "legacy", "shafts"),
    Site(11, "design_service.py:1206", "capability_graph.json", "legacy", "capability"),
    Site(12, "design_service.py:1299", "network.json", "legacy", "network"),
    Site(
        13,
        "design_service.py:1377",
        "tunnel_mesh.json",
        "legacy",
        "tunnel",
        ("tunnel_mesh.glb",),
    ),
    Site(14, "design_service.py:1380", "tunnel_mesh.glb", "legacy", "tunnel"),
    Site(
        15,
        "design_service.py:1482",
        "development_mesh.json",
        "legacy",
        "development_mesh",
        ("development_mesh.glb",),
    ),
    Site(16, "design_service.py:1485", "development_mesh.glb", "legacy", "development_mesh"),
    Site(17, "infrastructure_service.py:104", "communication.json", "legacy", "communication"),
    Site(18, "infrastructure_service.py:153", "sensors.json", "legacy", "sensors"),
    Site(19, "effective_ramp.py:99", "ramp_source.json", "layout_v2", "ramp_source"),
    Site(20, "scenario_service.py:130", "scenario.json", "legacy", "scenario"),
    Site(21, "world_service.py:241", "arrays.npz", "legacy", "world_save"),
    Site(22, "world_service.py:244", "world.json", "legacy", "world_save", ("arrays.npz",)),
)

FAULTS = ("replace", "fsync", "write")


def test_the_site_table_is_the_stage_a_table() -> None:
    """22 sites, each named once, each with a ``file:line`` provenance."""
    assert len(SITES) == 22
    assert len({s.number for s in SITES}) == 22
    assert sorted(s.number for s in SITES) == list(range(1, 23))
    # a FILE may appear twice only when one writer publishes it twice; here
    # every file is published by exactly one site
    assert len({s.file for s in SITES}) == 22
    assert all(":" in s.origin and s.origin.endswith(tuple("0123456789")) for s in SITES)


# --------------------------------------------------------------------------- #
# the stacks
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def legacy(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Stack]:
    stack, context = _build(tmp_path_factory.mktemp("fi_legacy"), "LEGACY")
    yield stack
    context.__exit__(None, None, None)
    stack.jobs.shutdown()


@pytest.fixture(scope="module")
def layout_v2(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Stack]:
    stack, context = _build(tmp_path_factory.mktemp("fi_layout"), "LAYOUT_V2")
    yield stack
    context.__exit__(None, None, None)
    stack.jobs.shutdown()


# --------------------------------------------------------------------------- #
# the drivers — the REAL writers, called exactly as the API calls them
# --------------------------------------------------------------------------- #


def _other_feasible_candidate(stack: Stack) -> str:
    """A FEASIBLE candidate that is NOT the selected one: re-selecting the
    selected candidate at the same catalogue revision is an explicit no-op
    (AC-01D idempotency), which would never reach the publication."""
    import json

    catalogue = json.loads((stack.derived / "layout_v2.json").read_text(encoding="utf-8"))
    selected = json.loads((stack.derived / "layout_v2_selected.json").read_text(encoding="utf-8"))[
        "candidateId"
    ]
    feasible = [
        c["candidateId"]
        for c in catalogue["candidates"]
        if c["status"] == "FEASIBLE" and c["candidateId"] != selected
    ]
    assert feasible, "the layout-v2 fixture must offer a second feasible candidate"
    return feasible[0]


def _world_save(stack: Stack) -> None:
    """``WorldService._save`` directly — the production publisher of
    ``arrays.npz`` + ``derived/world.json``. ``generate`` is NOT used here
    because it runs the rule-46 invalidation FIRST (every derived artifact is
    deleted before the world is rebuilt), which is a documented lifecycle
    behaviour with nothing to say about publication atomicity and would leave
    no previous artifact set to compare against."""
    scenario, world = stack.worlds.load(stack.sid)
    stack.worlds._save(scenario, world, world.stats(scenario))


def _scenario_write(stack: Stack) -> None:
    """``ScenarioStore.replace`` → ``_write`` → ``scenario.json``."""
    document = stack.store.get(stack.sid)
    payload = ScenarioCreate(**document.model_dump(exclude={"id", "schema_version"}))
    stack.store.replace(stack.sid, payload)


DRIVERS: dict[str, Any] = {
    "targets": lambda s: s.design.generate_targets(s.sid),
    "decline": lambda s: s.design.generate_decline(s.sid, max_levels=2),
    "smoothed": lambda s: s.design.generate_smoothed(s.sid),
    "layout": lambda s: s.design.generate_layout_v2(s.sid),
    "select": lambda s: s.design.select_layout_candidate(s.sid, _other_feasible_candidate(s)),
    "levels": lambda s: s.design.generate_levels(s.sid),
    "stopes": lambda s: s.design.generate_stopes(s.sid),
    "timeline": lambda s: s.design.generate_timeline(s.sid),
    "shafts": lambda s: s.design.generate_shafts(s.sid),
    "capability": lambda s: s.design.generate_capability_graph(s.sid),
    "network": lambda s: s.design.generate_network(s.sid),
    "tunnel": lambda s: s.design.generate_tunnel(s.sid),
    "development_mesh": lambda s: s.design.generate_development_mesh(s.sid),
    "communication": lambda s: s.infra.generate_communication(s.sid),
    "sensors": lambda s: s.infra.generate_sensors(s.sid),
    # LAYOUT_V2 → LEGACY: the only switch the layout-v2 stack can perform
    # that actually WRITES (``set_ramp_source`` writes only on a change)
    "ramp_source": lambda s: s.design.set_ramp_source(s.sid, "LEGACY"),
    "scenario": _scenario_write,
    "world_save": _world_save,
}


def test_every_site_has_a_driver() -> None:
    assert {s.driver for s in SITES} <= set(DRIVERS)
    assert set(DRIVERS) == {s.driver for s in SITES}


# --------------------------------------------------------------------------- #
# the injector
# --------------------------------------------------------------------------- #


class PublicationFault:
    """One fault, aimed at ONE target file name.

    Aimed, not global: a writer that publishes two files must be able to fail
    on the second one with the first already published (the D3 pair order),
    and the surrounding test machinery must keep working. The temp sibling of
    ``<name>`` is ``.<name>.<hex>.tmp`` (``.tmp.npz`` for the NPZ), so the
    name alone identifies the publication in flight — no private helper of
    the module under test is monkeypatched. The temp is created with
    ``os.open(..., O_WRONLY|O_CREAT|O_EXCL)`` and wrapped in ``os.fdopen``,
    so the hooks are ``os.open`` (which sees the NAME and records the fd),
    ``os.fdopen`` (which wraps that fd's handle), ``os.fsync`` and
    ``os.replace``.
    """

    def __init__(self, target: str, mode: str) -> None:
        self.target = target
        self.mode = mode
        self.fired = 0
        self._fds: set[int] = set()
        self._prefix = f".{target}."

    def _is_my_temp(self, name: str) -> bool:
        return name.startswith(self._prefix) and ".tmp" in name

    @contextmanager
    def applied(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
        real_os_open, real_fdopen = os.open, os.fdopen
        real_fsync, real_replace = os.fsync, os.replace
        fault = self

        class _Handle:
            def __init__(self, handle: Any) -> None:
                self._handle = handle
                self._writes = 0

            def write(self, data: Any) -> int:
                if fault.mode == "write" and self._writes == 0 and len(data) > 1:
                    self._handle.write(data[: len(data) // 2])
                    self._writes += 1
                    fault.fired += 1
                    raise OSError(28, "injected: short write on the temp sibling")
                self._writes += 1
                return int(self._handle.write(data))

            def __getattr__(self, name: str) -> Any:
                return getattr(self._handle, name)

            def __enter__(self) -> Any:
                self._handle.__enter__()
                return self

            def __exit__(self, *exc: Any) -> Any:
                return self._handle.__exit__(*exc)

        def os_open(file: Any, *args: Any, **kwargs: Any) -> int:
            fd = real_os_open(file, *args, **kwargs)
            if fault._is_my_temp(Path(str(file)).name):
                fault._fds.add(fd)
            return fd

        def fdopen(fd: int, *args: Any, **kwargs: Any) -> Any:
            handle = real_fdopen(fd, *args, **kwargs)
            return _Handle(handle) if fd in fault._fds else handle

        def fsync(fd: int) -> None:
            if fault.mode == "fsync" and fd in fault._fds:
                fault.fired += 1
                raise OSError(5, "injected: os.fsync failed")
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                real_fsync(fd)
                return
            real_fsync(fd)

        def replace(src: Any, dst: Any) -> None:
            if fault.mode == "replace" and Path(str(dst)).name == fault.target:
                fault.fired += 1
                raise OSError(5, "injected: os.replace failed")
            real_replace(src, dst)

        monkeypatch.setattr(os, "open", os_open)
        monkeypatch.setattr(os, "fdopen", fdopen)
        monkeypatch.setattr(os, "fsync", fsync)
        monkeypatch.setattr(os, "replace", replace)
        try:
            yield
        finally:
            monkeypatch.setattr(os, "open", real_os_open)
            monkeypatch.setattr(os, "fdopen", real_fdopen)
            monkeypatch.setattr(os, "fsync", real_fsync)
            monkeypatch.setattr(os, "replace", real_replace)


# --------------------------------------------------------------------------- #
# state capture / restore
# --------------------------------------------------------------------------- #


def _digest(directory: Path) -> dict[str, str]:
    return {
        str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }


def _temp_residue(directory: Path) -> list[str]:
    return sorted(str(p.relative_to(directory)) for p in directory.rglob("*") if ".tmp" in p.name)


@contextmanager
def restored(directory: Path) -> Iterator[None]:
    """Exact undo of the whole scenario directory: bytes AND ``st_mtime_ns``
    (Stage A C-12 — restoring bytes alone changes ``file_revision`` and
    contaminates every later case), and any file that appeared is removed."""
    saved = {
        p: (p.read_bytes(), os.stat(p).st_atime_ns, os.stat(p).st_mtime_ns)
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }
    try:
        yield
    finally:
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path not in saved:
                path.unlink()
        for path, (data, atime, mtime) in saved.items():
            if not path.exists() or path.read_bytes() != data:
                path.write_bytes(data)
            os.utime(path, ns=(atime, mtime))


# --------------------------------------------------------------------------- #
# the table
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("fault_mode", FAULTS)
@pytest.mark.parametrize("site", SITES, ids=lambda s: f"{s.number:02d}-{s.file}")
def test_a_failed_publication_never_damages_the_previous_artifact(
    site: Site,
    fault_mode: str,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stack: Stack = request.getfixturevalue(site.stack)
    root = stack.store.scenario_dir(stack.sid)
    target = next(p for p in root.rglob("*") if p.name == site.file)
    before_digest = _digest(root)
    before_bytes = target.read_bytes()
    before_mtime = os.stat(target).st_mtime_ns
    fault = PublicationFault(site.file, fault_mode)
    with restored(root):
        with fault.applied(monkeypatch), pytest.raises(OSError) as raised:
            DRIVERS[site.driver](stack)
        # the fault really fired — a table of never-injected faults proves
        # nothing (§29)
        assert fault.fired >= 1, (site, fault_mode)
        # 1. the previous target survived untouched, bytes AND stat identity
        assert target.read_bytes() == before_bytes, (site, fault_mode)
        assert os.stat(target).st_mtime_ns == before_mtime, (site, fault_mode)
        # 2. no temp sibling anywhere in the scenario directory
        assert _temp_residue(root) == [], (site, fault_mode)
        # 3. the exception is the OSError-class failure it has always been
        assert isinstance(raised.value, OSError)
        # 4. the cascade did not run: the file SET is unchanged, and every
        #    file except the declared co-published one is byte-identical
        after_digest = _digest(root)
        assert set(after_digest) == set(before_digest), (site, fault_mode)
        co_published = {name for name in after_digest if Path(name).name in set(site.co_published)}
        assert len(co_published) == len(site.co_published), (site, site.co_published)
        changed = {
            name
            for name, digest in after_digest.items()
            if before_digest[name] != digest and name not in co_published
        }
        assert changed == set(), (site, fault_mode, sorted(changed))


def test_the_npz_site_is_covered_by_the_table() -> None:
    """``arrays.npz`` is the one site whose serializer is
    ``np.savez_compressed``; the table drives it like every other."""
    npz = [s for s in SITES if s.file.endswith(".npz")]
    assert [s.number for s in npz] == [21]
    assert npz[0].driver == "world_save"


# --------------------------------------------------------------------------- #
# the route answer (recorded, not changed)
# --------------------------------------------------------------------------- #


def test_the_route_answer_for_an_io_fault_is_the_unmapped_500(
    legacy: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D5.1: "the writer's exception propagates typed-or-not exactly as an
    OSError does today". No new code is minted for a failed publication: the
    route answers the same unmapped 500 (no ``detail.code``) that an I/O
    fault on the old in-place write answered — the difference is what is on
    disk afterwards, which the table above pins."""
    root = legacy.store.scenario_dir(legacy.sid)
    fault = PublicationFault("stopes.json", "replace")
    with restored(root), fault.applied(monkeypatch):
        status, code = legacy.post("/design/stopes")
    assert fault.fired >= 1
    assert (status, code) == (500, None)
    assert _temp_residue(root) == []


def test_no_temp_residue_after_a_complete_build(legacy: Stack, layout_v2: Stack) -> None:
    """D4: the normal path leaves no ``*.tmp*`` file — the replace consumes
    the temp on success and the exception path removes it. Asserted over the
    complete LEGACY and LAYOUT_V2 stacks (every writer of the suite, both
    sources), not over a single publication."""
    for stack in (legacy, layout_v2):
        root = stack.store.scenario_dir(stack.sid)
        assert _temp_residue(root) == [], stack.sid
        assert (root / "arrays.npz").is_file()
        assert (root / "derived" / "world.json").is_file()


def test_the_stacks_are_still_healthy_after_every_injected_failure(
    legacy: Stack, layout_v2: Stack
) -> None:
    """The closing evidence for "the previous artifact set is intact": after
    the whole injected table has run against them, both stacks still serve
    their scene and their ramp.

    FILE ORDER MATTERS here, and deliberately: this case is meaningful only
    once the parametrized fault table above has run against the two
    module-scoped stacks, so it is the LAST test in the file and pytest's
    declaration order is what puts it there. Every OTHER case in this module
    is self-contained (each restores the scenario directory it touched
    through ``restored``); this one is the single aggregate, and running it
    alone (``-k`` on its name) asserts only that a freshly built stack is
    healthy — a weaker, still true, statement."""
    for stack in (legacy, layout_v2):
        scene = stack.client.get(f"{API}/{stack.sid}/scene")
        assert scene.status_code == 200, (stack.sid, scene.text[:300])
        ramp = stack.client.get(f"{API}/{stack.sid}/design/ramp")
        assert ramp.status_code == 200, (stack.sid, ramp.text[:300])
        assert _temp_residue(stack.store.scenario_dir(stack.sid)) == []
