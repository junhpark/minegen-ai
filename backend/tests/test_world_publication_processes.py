"""AC-01F.2 correction B2 — cross-PROCESS coherence of the world COMMIT RECORD.

The property under test is the one the correction states:

    MineGen never serves a persisted state as VALID when its scenario, world
    or logically coupled artifact files belong to different publication
    generations, INCLUDING after writer process death and FROM A FRESH
    PROCESS.

Why a process boundary is the only honest instrument here. Before the commit
record, a world was bound to the document it was generated from ONLY in memory
(``WorldService._BoundWorld``). Every in-process proof of that binding is
therefore circular: the object that would notice the mismatch is the same
object that remembers the generation. A writer that dies between
``store.replace()`` and ``invalidate()`` leaves NEW ``scenario.json`` beside an
OLD ``arrays.npz`` PERMANENTLY, and the only reader that can testify about it
is one that has never seen the previous state — a different process, or at the
very least a brand-new set of service objects with empty caches.
``tests/test_artifact_read_api.py::cold_services`` is NOT a fresh process: it
rebuilds the services inside the SAME interpreter, so it can prove a cache is
not consulted but it can never prove a state survives writer death. Every case
below kills or stalls a REAL ``multiprocessing`` spawn child at an injected
publication point.

Synchronization. Every child is driven by ``multiprocessing.Pipe`` /
``Event`` / ``Barrier``. There is NO ``sleep`` anywhere in this module — not as
a synchronizer and not as a settling delay (``test_sw3_...`` asserts that
structurally). Every wait is bounded and carries an explicit message naming the
child and the checkpoint it never reached, so a broken child fails the run
instead of hanging it.

The cases:

* ``SW1``/``MP1`` a child replaces ``scenario.json`` and dies before
  ``invalidate()`` — the B1 hole — at the service layer and through the real
  API; the survivor state is refused typed on the world, the scene and a
  derived route, from a fresh process.
* ``SW2`` that state never becomes VALID by being read again (reads never
  repair), and a regeneration is what restores 200.
* ``MP2`` a child dies between ``publish_npz(arrays.npz)`` and the record
  publication, in both reachable shapes (record ABSENT after ``generate``'s
  rule-46 invalidation, record naming the PREVIOUS arrays after a direct
  ``_save``); a later successful generation recovers.
* ``MP3`` two concurrent generator processes interleaved at their four
  publications: at most ONE committed generation, never a 200 on a mixed pair.
* ``MP4`` the correction's Q1.1 interleaving exactly, WITH the counterfactual:
  the value a post-hoc ``file_revision(path)`` would have recorded at the
  interleaving instant is measured and shown to produce a FALSE 200, so this
  test dies if the fd-derived revision is ever reverted to a post-hoc stat.
* ``MP5`` a reader process against a writer loop of PUT + generate: zero
  unmapped 500s, every answer inside the typed set, distribution reported.

This module is marked ``slow`` + ``e2e`` CENTRALLY (rule 181,
``tests/conftest.py::MODULE_MARKERS``) so the tiering stays one auditable
table; no decorator here can drift from it.
"""

from __future__ import annotations

import ast
import inspect
import json
import multiprocessing as mp
import os
import time
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from minegen.api.deps import (
    get_design_service,
    get_infrastructure_service,
    get_job_service,
    get_scenario_store,
    get_world_service,
)
from minegen.core.models import ScenarioCreate
from minegen.core.revision import file_revision
from minegen.core.world_record import (
    PUBLICATION_KEY,
    WORLD_RECORD_FILE,
    build_world_record,
    record_rejection,
)
from minegen.main import create_app
from minegen.services.design_service import DesignService
from minegen.services.infrastructure_service import InfrastructureService
from minegen.services.job_service import JobService
from minegen.services.scenario_service import ScenarioStore
from minegen.services.world_service import WorldService
from tests.test_artifact_read_api import API, Stack, _answer, _make_stack

# --------------------------------------------------------------------------- #
# constants
# --------------------------------------------------------------------------- #

#: SPAWN, never fork: a forked child inherits the parent's imported modules,
#: its open TestClient and — the point of this module — its WARM world cache,
#: so a fork could not testify that a FRESH process reaches the same verdict.
SPAWN = mp.get_context("spawn")

#: the exit code an injected ``os._exit`` uses, and the one a child that got
#: PAST the injection point would use (so "it died where we said" is asserted,
#: not assumed)
EXIT_KILLED = 42
EXIT_UNREACHABLE = 97

#: every wait in this module is bounded. These are generous ceilings whose only
#: job is to turn a broken child into a failure instead of a hung run
#: (measured child start-up on this host: ≈ 1–2 s).
CHILD_TIMEOUT = 180.0
STEP_TIMEOUT = 120.0
BARRIER_TIMEOUT = 120.0
#: MP5's reader stops on the writer's Event; this is the safety ceiling that
#: makes a lost Event a failure rather than a hang — never a synchronizer
READER_DEADLINE = 120.0

#: the world surface, the scene and a DERIVED route — the three the correction
#: names as enforcement surfaces of the world guard
WORLD_SURFACES: tuple[str, ...] = ("/world", "/scene", "/design/targets")

STALE = "WORLD_PUBLICATION_STALE"

#: measured numbers, printed at module teardown so the run reports them
MEASURED: dict[str, dict[str, Any]] = {}


def _record(case: str, **numbers: Any) -> None:
    MEASURED[case] = numbers


@pytest.fixture(scope="module", autouse=True)
def _report() -> Iterator[None]:
    yield
    print("\n--- MEASURED (test_world_publication_processes) ---")
    for case, numbers in MEASURED.items():
        print(f"{case}: {json.dumps(numbers, sort_keys=True)}")


# --------------------------------------------------------------------------- #
# service / client construction, used identically in the parent and in children
# --------------------------------------------------------------------------- #


def _services(root: Path) -> tuple[ScenarioStore, WorldService, DesignService, JobService]:
    """A brand-new object graph over an EXISTING store directory. Nothing is
    shared with the caller's stack: in particular ``WorldService._cache`` is
    empty, which is what makes a read from these objects evidence about the
    DISK rather than about a remembered generation."""
    store = ScenarioStore(root / "scenarios")
    worlds = WorldService(store)
    design = DesignService(store, worlds)
    jobs = JobService(max_workers=1)
    return store, worlds, design, jobs


@contextmanager
def _client(
    store: ScenarioStore, worlds: WorldService, design: DesignService, jobs: JobService
) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_scenario_store] = lambda: store
    app.dependency_overrides[get_world_service] = lambda: worlds
    app.dependency_overrides[get_design_service] = lambda: design
    app.dependency_overrides[get_infrastructure_service] = lambda: InfrastructureService(
        store, design
    )
    app.dependency_overrides[get_job_service] = lambda: jobs
    import minegen.api.jobs as jobs_module

    jobs_module.get_job_service = lambda: jobs  # type: ignore[assignment]
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def _answers(client: TestClient, sid: str, routes: Sequence[str]) -> dict[str, list[Any]]:
    """``route -> [status, code]`` (a list, so the mapping survives the Pipe's
    pickling and a JSON round trip unchanged)."""
    return {route: list(_answer(client.get(f"{API}/{sid}{route}"))) for route in routes}


# --------------------------------------------------------------------------- #
# child targets (module level: spawn re-imports this module and pickles by name)
# --------------------------------------------------------------------------- #


def _die(*_args: Any, **_kwargs: Any) -> None:
    """The injected crash. ``os._exit`` skips every ``finally``, every atexit
    hook and every buffer flush — the closest a test can get to the writer
    losing its process at exactly this instruction."""
    os._exit(EXIT_KILLED)


def child_replace_scenario_and_die(root: str, sid: str, document: str) -> None:
    """SW1's writer: publish a NEW ``scenario.json`` and die BEFORE
    ``invalidate()``. ``WorldService.replace_scenario`` is the production
    mutation (``store.replace()`` then ``self.invalidate()`` in one locked
    section); only the second half is replaced by the crash, so the surviving
    disk state is exactly the Q2 kill point B."""
    store = ScenarioStore(Path(root) / "scenarios")
    worlds = WorldService(store)
    worlds.invalidate = _die  # type: ignore[method-assign]
    worlds.replace_scenario(sid, ScenarioCreate.model_validate(json.loads(document)))
    os._exit(EXIT_UNREACHABLE)  # pragma: no cover - the crash is before this


def child_replace_scenario_via_api_and_die(root: str, sid: str, document: str) -> None:
    """MP1's writer: the SAME crash reached through the real ``PUT
    /api/v1/scenarios/{id}`` route, so the router's dependency wiring is part
    of the proof and not assumed away."""
    store, worlds, design, jobs = _services(Path(root))
    worlds.invalidate = _die  # type: ignore[method-assign]
    with _client(store, worlds, design, jobs) as client:
        client.put(f"{API}/{sid}", json=json.loads(document))
    os._exit(EXIT_UNREACHABLE)  # pragma: no cover - the crash is before this


def child_generate_and_die_before_the_record(root: str, sid: str) -> None:
    """MP2 shape (a): a REGENERATION that publishes ``arrays.npz`` and dies
    before the record. ``generate`` runs rule 46's ``invalidate`` first, so the
    record is ABSENT when the process dies — an uncommitted generation."""
    import minegen.services.world_service as ws

    ws.publish_text = _die  # type: ignore[assignment]
    ws.WorldService(ScenarioStore(Path(root) / "scenarios")).generate(sid)
    os._exit(EXIT_UNREACHABLE)  # pragma: no cover - the crash is before this


def child_save_and_die_before_the_record(root: str, sid: str) -> None:
    """MP2 shape (b): ``WorldService._save`` — the production publisher of the
    pair — driven directly so no invalidation precedes it. The record left on
    disk is the PREVIOUS generation's and names the PREVIOUS ``arrays.npz``,
    which the new publication has already replaced."""
    import minegen.services.world_service as ws

    store = ScenarioStore(Path(root) / "scenarios")
    worlds = ws.WorldService(store)
    scenario, world = worlds.load(sid)
    stats = world.stats(scenario)
    revision = file_revision(store.scenario_path(sid))
    assert revision is not None, "the fixture must leave a readable scenario.json"
    ws.publish_text = _die  # type: ignore[assignment]
    worlds._save(scenario, world, stats, revision)
    os._exit(EXIT_UNREACHABLE)  # pragma: no cover - the crash is before this


def _await_go(conn: Connection) -> None:
    assert conn.poll(STEP_TIMEOUT), f"child: no release within {STEP_TIMEOUT}s"
    token = conn.recv()
    assert token == "go", f"child: unexpected release token {token!r}"


def _checkpoint(conn: Connection, tag: str) -> None:
    conn.send((tag, None))
    _await_go(conn)


def child_checkpointed_generate(
    root: str, sid: str, conn: Connection, stall_inside_arrays: bool = False
) -> None:
    """A REAL ``WorldService.generate`` whose publications are individually
    released by the parent, so an interleaving is CHOSEN rather than hoped for.

    The wrappers add checkpoints around the module-level ``publish_npz`` /
    ``publish_text`` that ``_save`` calls; the publication primitives, the
    ordering (arrays FIRST, record LAST) and the record contents are the
    production ones. Each wrapper reports the revision the publication
    RETURNED — the fd-derived identity of the bytes this process installed.

    ``stall_inside_arrays`` adds the extra checkpoint MP4 needs, at exactly the
    place correction Q1.1 stalls P2: inside ``publish_npz``'s
    ``_fsync_directory``, i.e. AFTER ``os.replace`` has installed this
    process's bytes and BEFORE ``publish_npz`` returns. It has to be there and
    not at the record publication, because the pre-fix code's post-hoc
    ``file_revision(path)`` ran the instant ``publish_npz`` returned: a stall
    placed any later would let that stat read this process's OWN file and the
    counterfactual would prove nothing. The fd ``os.fstat`` the returned
    revision is built from was already taken before the replace, so the
    correct value is fixed before the stall and the two can be compared. The
    patch is one-shot (``armed``), so only the ARRAYS publication stalls and
    the record publication uses the untouched helper."""
    import minegen.core.publication as publication
    import minegen.services.world_service as ws

    real_npz, real_text = ws.publish_npz, ws.publish_text
    real_fsync = publication._fsync_directory
    armed = [stall_inside_arrays]

    def fsync(directory: Path) -> None:
        if armed[0]:
            armed[0] = False
            _checkpoint(conn, "arrays.replaced")
        real_fsync(directory)

    def npz(path: Path, **arrays: Any) -> str:
        _checkpoint(conn, "arrays.before")
        revision = real_npz(path, **arrays)
        conn.send(("arrays.after", revision))
        return revision

    def text(path: Path, data: str, **kwargs: Any) -> str:
        _checkpoint(conn, "record.before")
        revision = real_text(path, data, **kwargs)
        conn.send(("record.after", revision))
        return revision

    publication._fsync_directory = fsync  # type: ignore[assignment]
    ws.publish_npz = npz  # type: ignore[assignment]
    ws.publish_text = text  # type: ignore[assignment]
    worlds = ws.WorldService(ScenarioStore(Path(root) / "scenarios"))
    conn.send(("ready", None))
    _await_go(conn)
    worlds.generate(sid)
    assert not armed[0], "the arrays publication never reached its stall point"
    conn.send(("done", None))
    conn.close()


def child_read_routes(root: str, sid: str, routes: tuple[str, ...], conn: Connection) -> None:
    """The FRESH-PROCESS reader: a brand-new interpreter, brand-new services,
    an empty world cache, and no knowledge whatsoever of the state that existed
    before the writer died."""
    store, worlds, design, jobs = _services(Path(root))
    assert worlds._cache == {}, "a fresh process must start with an EMPTY world cache"
    try:
        with _client(store, worlds, design, jobs) as client:
            answers = _answers(client, sid, routes)
    finally:
        jobs.shutdown()
    conn.send(answers)
    conn.close()


def child_read_loop(
    root: str,
    sid: str,
    routes: tuple[str, ...],
    stop: Any,
    ready: Any,
    conn: Connection,
) -> None:
    """MP5's reader: a separate process hammering the read surfaces while the
    parent runs a PUT + generate writer loop. It stops on the writer's Event
    (never on a timer); the deadline exists only so a lost Event is a failure
    instead of a hang."""
    store, worlds, design, jobs = _services(Path(root))
    counts: Counter[str] = Counter()
    reads = 0
    try:
        with _client(store, worlds, design, jobs) as client:
            ready.wait(BARRIER_TIMEOUT)
            deadline = time.monotonic() + READER_DEADLINE
            while not stop.is_set() and time.monotonic() < deadline:
                for route in routes:
                    status, code = _answer(client.get(f"{API}/{sid}{route}"))
                    counts[f"{route} -> {status} {code}"] += 1
                    reads += 1
    finally:
        jobs.shutdown()
    conn.send({"reads": reads, "counts": dict(counts)})
    conn.close()


# --------------------------------------------------------------------------- #
# parent-side process helpers — bounded waits, explicit messages, no sleep
# --------------------------------------------------------------------------- #

#: how many spawn children this module actually started (reported at teardown)
PROCESS_COUNT: list[int] = [0]


#: every child started by this module, so a FAILING case cannot leave an
#: orphan behind (``_no_orphans`` kills the survivors at teardown)
_LIVE: list[Any] = []


def _spawn(target: Any, *args: Any) -> Any:
    proc = SPAWN.Process(target=target, args=args, name=target.__name__)
    proc.start()
    PROCESS_COUNT[0] += 1
    _LIVE.append(proc)
    return proc


@pytest.fixture(autouse=True)
def _no_orphans() -> Iterator[None]:
    """A case that fails between two checkpoints leaves its child stalled on a
    ``Pipe`` that will never be released. Killing the survivors here keeps the
    failure a failure instead of a hung run."""
    yield
    for proc in _LIVE:
        if proc.is_alive():
            proc.kill()
            proc.join(10.0)
    _LIVE.clear()


def _join(proc: Any, *, expect_exitcode: int, timeout: float = CHILD_TIMEOUT) -> None:
    proc.join(timeout)
    if proc.exitcode is None:
        proc.kill()
        proc.join(10.0)
        raise AssertionError(f"child {proc.name} did not exit within {timeout}s")
    assert proc.exitcode == expect_exitcode, (
        f"child {proc.name} exited {proc.exitcode}, expected {expect_exitcode} "
        f"({EXIT_KILLED} = died at the injected point, "
        f"{EXIT_UNREACHABLE} = ran PAST the injected point)"
    )


def _run_child(target: Any, *args: Any, expect_exitcode: int = EXIT_KILLED) -> None:
    """Start a spawn child, wait for it with a bound, and pin WHERE it died."""
    _join(_spawn(target, *args), expect_exitcode=expect_exitcode)


def _child_answers(
    root: Path, sid: str, routes: Sequence[str] = WORLD_SURFACES
) -> dict[str, tuple[int, str | None]]:
    """The read surfaces answered by a FRESH PROCESS."""
    parent_conn, child_conn = SPAWN.Pipe()
    proc = _spawn(child_read_routes, str(root), sid, tuple(routes), child_conn)
    if not parent_conn.poll(STEP_TIMEOUT):
        proc.kill()
        proc.join(10.0)
        raise AssertionError(
            f"the fresh-process reader sent no answers within {STEP_TIMEOUT}s "
            f"(exitcode={proc.exitcode})"
        )
    raw = parent_conn.recv()
    _join(proc, expect_exitcode=0)
    return {route: (int(pair[0]), pair[1]) for route, pair in raw.items()}


@dataclass
class FreshRead:
    """A read performed by brand-new service objects in THIS process."""

    answers: dict[str, tuple[int, str | None]]
    services_token: int
    cache_before: int
    cache_after: int


#: monotonic token proving two ``_fresh_answers`` calls never share objects
_FRESH_TOKEN: list[int] = [0]


def _fresh_answers(root: Path, sid: str, routes: Sequence[str] = WORLD_SURFACES) -> FreshRead:
    """Brand-new ``ScenarioStore`` / ``WorldService`` / ``DesignService`` over
    the same directory. The empty-cache assertion is the point: whatever these
    objects answer, they answered it from the FILES."""
    store, worlds, design, jobs = _services(root)
    _FRESH_TOKEN[0] += 1
    before = len(worlds._cache)
    assert before == 0, "a fresh WorldService must start with an EMPTY world cache"
    try:
        with _client(store, worlds, design, jobs) as client:
            answers = _answers(client, sid, routes)
    finally:
        jobs.shutdown()
    return FreshRead(
        answers={route: (int(pair[0]), pair[1]) for route, pair in answers.items()},
        services_token=_FRESH_TOKEN[0],
        cache_before=before,
        cache_after=len(worlds._cache),
    )


@dataclass
class Checkpointed:
    """A stalled generator process the parent steps through its publications."""

    proc: Any
    conn: Connection
    label: str
    seen: list[str] = field(default_factory=list)

    def expect(self, tag: str, timeout: float = STEP_TIMEOUT) -> Any:
        assert self.conn.poll(timeout), (
            f"{self.label}: checkpoint '{tag}' never arrived within {timeout}s "
            f"(alive={self.proc.is_alive()}, exitcode={self.proc.exitcode}, "
            f"seen={self.seen})"
        )
        try:
            got, payload = self.conn.recv()
        except EOFError as exc:  # pragma: no cover - only on a crashed child
            raise AssertionError(
                f"{self.label}: died before checkpoint '{tag}' "
                f"(exitcode={self.proc.exitcode}, seen={self.seen})"
            ) from exc
        self.seen.append(got)
        assert got == tag, f"{self.label}: expected checkpoint '{tag}', got '{got}'"
        return payload

    def release(self) -> None:
        self.conn.send("go")

    def begin(self) -> None:
        """Release the child into ``generate``; it stalls at its next publish."""
        self.release()

    def stall(self, what: str) -> None:
        """Run until the child is about to publish ``what``, and leave it there."""
        self.expect(f"{what}.before")

    def resume(self, what: str) -> str:
        """Let the stalled publication happen; return the INSTALLED revision."""
        self.release()
        revision = self.expect(f"{what}.after")
        assert isinstance(revision, str) and revision, f"{self.label}: no {what} revision"
        return revision

    def publish(self, what: str) -> str:
        self.stall(what)
        return self.resume(what)

    def replace_arrays(self) -> None:
        """Run until ``os.replace`` has installed this child's ``arrays.npz``
        and leave it stalled INSIDE ``publish_npz`` (correction Q1.1's stall
        point). Only a child started with ``stall_inside_arrays`` gets here."""
        self.stall("arrays")
        self.release()
        self.expect("arrays.replaced")

    def finish_arrays(self) -> str:
        """Let the stalled ``publish_npz`` return; its fd-derived revision."""
        return self.resume("arrays")

    def finish(self) -> None:
        self.expect("done")
        _join(self.proc, expect_exitcode=0)


def _start_checkpointed(
    root: Path, sid: str, label: str, *, stall_inside_arrays: bool = False
) -> Checkpointed:
    parent_conn, child_conn = SPAWN.Pipe()
    proc = _spawn(child_checkpointed_generate, str(root), sid, child_conn, stall_inside_arrays)
    runner = Checkpointed(proc, parent_conn, label)
    runner.expect("ready")
    return runner


def _start_reader(root: Path, sid: str, routes: Sequence[str]) -> tuple[Any, Any, Any, Connection]:
    """MP5's reader process plus the Barrier that starts it with the writer and
    the Event that stops it."""
    stop = SPAWN.Event()
    ready = SPAWN.Barrier(2)
    parent_conn, child_conn = SPAWN.Pipe()
    proc = _spawn(child_read_loop, str(root), sid, tuple(routes), stop, ready, child_conn)
    return proc, stop, ready, parent_conn


# --------------------------------------------------------------------------- #
# disk observation (the parent never repairs, only measures)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DiskState:
    scenario_revision: str | None
    arrays_revision: str | None
    record: dict[str, Any] | None

    @property
    def recorded_scenario(self) -> Any:
        return (self.record or {}).get(PUBLICATION_KEY, {}).get("scenarioRevision")

    @property
    def recorded_arrays(self) -> Any:
        return (self.record or {}).get(PUBLICATION_KEY, {}).get("arraysRevision")

    def rejection(self, sid: str) -> str | None:
        assert self.scenario_revision is not None and self.arrays_revision is not None
        return record_rejection(
            self.record,
            scenario_id=sid,
            scenario_revision=self.scenario_revision,
            arrays_revision=self.arrays_revision,
        )


def _disk(store: ScenarioStore, sid: str) -> DiskState:
    record_path = store.derived_dir(sid) / WORLD_RECORD_FILE
    record: dict[str, Any] | None = None
    if record_path.is_file():
        loaded = json.loads(record_path.read_text())
        record = loaded if isinstance(loaded, dict) else None
    return DiskState(
        scenario_revision=file_revision(store.scenario_path(sid)),
        arrays_revision=file_revision(store.arrays_path(sid)),
        record=record,
    )


def _tree(store: ScenarioStore, sid: str) -> dict[str, tuple[int, int]]:
    """Every persisted file with its (size, mtime_ns) — the rule-60 inputs. A
    read that repaired ANYTHING would move one of these."""
    root = store.scenario_dir(sid)
    return {
        str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _document(stack: Stack, name: str) -> str:
    doc = stack.client.get(f"{API}/{stack.sid}").json()
    doc.pop("id")
    doc.pop("schemaVersion")
    doc["name"] = name
    return json.dumps(doc)


# --------------------------------------------------------------------------- #
# fixture — a committed world plus ONE derived artifact, per test
# --------------------------------------------------------------------------- #


@pytest.fixture
def stack(tmp_path: Path) -> Iterator[Stack]:
    """A committed world and a ``targets.json``, so every case has a derived
    route that answers 200 BEFORE the writer dies (measured on this host:
    ≈ 0.26 s to build)."""
    built, context = _make_stack(tmp_path / "root")
    assert built.client.post(f"{API}/{built.sid}/world/generate").status_code == 200
    assert built.client.post(f"{API}/{built.sid}/design/targets").status_code == 200
    yield built
    context.__exit__(None, None, None)
    built.jobs.shutdown()


def _root_of(stack: Stack) -> Path:
    return stack.store.root.parent


# --------------------------------------------------------------------------- #
# SW1 / MP1 — the B1 hole: a NEW document beside an OLD world, permanently
# --------------------------------------------------------------------------- #


def _assert_b1_hole_is_refused(stack: Stack, case: str, child: Any) -> None:
    root, sid = _root_of(stack), stack.sid
    before_fresh = _fresh_answers(root, sid)
    assert all(a == (200, None) for a in before_fresh.answers.values()), (
        f"{case}: the premise failed — the committed state must answer 200 first "
        f"({before_fresh.answers})"
    )
    before = _disk(stack.store, sid)

    _run_child(child, str(root), sid, _document(stack, f"{case}-replaced"))

    after = _disk(stack.store, sid)
    # the writer really published the document and really did NOT invalidate
    assert after.scenario_revision != before.scenario_revision, (
        f"{case}: the child did not publish a new scenario.json"
    )
    assert after.arrays_revision == before.arrays_revision, (
        f"{case}: arrays.npz moved — the child got past the crash point"
    )
    assert after.record is not None, f"{case}: derived/world.json was cleared — invalidate ran"
    assert (stack.derived / "targets.json").is_file(), f"{case}: derived/ was cleared"

    # the ONLY thing that distinguishes this state from a coherent one is the
    # record: both live files exist, so every pre-record guard passes. Without
    # the record a fresh process would bind these two revisions and answer 200.
    assert after.scenario_revision is not None and after.arrays_revision is not None
    rejection = after.rejection(sid)
    assert rejection is not None and "scenario.json revision" in rejection, rejection
    assert (
        record_rejection(
            build_world_record(
                scenario_id=sid,
                scenario_revision=after.scenario_revision,
                arrays_revision=after.arrays_revision,
                stats={},
            ),
            scenario_id=sid,
            scenario_revision=after.scenario_revision,
            arrays_revision=after.arrays_revision,
        )
        is None
    ), f"{case}: the counterfactual record is not the discriminator it claims to be"

    fresh = _fresh_answers(root, sid)
    child_view = _child_answers(root, sid)
    for route in WORLD_SURFACES:
        assert fresh.answers[route] == (409, STALE), (route, fresh.answers)
        assert child_view[route] == (409, STALE), (route, child_view)
        assert fresh.answers[route] != (200, None)
    assert fresh.cache_before == 0
    _record(
        case,
        processes=2,
        surfaces=len(WORLD_SURFACES),
        before=before_fresh.answers,
        after=fresh.answers,
        fresh_process_after=child_view,
        rejection=rejection,
    )


def test_sw1_a_document_published_without_the_invalidation_is_refused_from_a_fresh_process(
    stack: Stack,
) -> None:
    """WHAT IT PROVES. A child publishes a NEW ``scenario.json`` through
    ``WorldService.replace_scenario`` and is killed with ``os._exit`` BEFORE
    ``invalidate()``. The surviving disk state — NEW document, OLD
    ``arrays.npz``, OLD ``derived/world.json`` — is refused 409
    ``WORLD_PUBLICATION_STALE`` on the world, the scene AND a derived route,
    both by brand-new service objects in this process and by a second REAL
    process, and the 200 those routes answered a moment earlier is now
    impossible.

    WHY THE PROCESS BOUNDARY MATTERS. This is AC-01F.2 finding B1, and it is
    the one defect that CANNOT be staged in one process: the state only exists
    because the writer died, and any reader that lived through the write is
    disqualified as a witness — the in-memory ``_BoundWorld`` that used to be
    the only binding between document and world is exactly the thing whose
    absence is under test. ``os._exit`` in a spawn child is the only way to
    produce the survivor state without hand-writing it."""
    _assert_b1_hole_is_refused(stack, "SW1", child_replace_scenario_and_die)


def test_mp1_the_same_hole_driven_through_the_real_put_route(stack: Stack) -> None:
    """WHAT IT PROVES. SW1 again, with the writer driving the REAL
    ``PUT /api/v1/scenarios/{id}`` route inside the child instead of calling
    the service directly: the router's dependency wiring (rule 40 — routers
    obtain services through FastAPI dependencies) is part of the proof, and the
    crash lands in the same locked section between ``store.replace()`` and
    ``invalidate()``.

    WHY THE PROCESS BOUNDARY MATTERS. The API layer cannot be killed mid-request
    in-process without taking the test runner with it; a spawn child gives the
    request a process of its own to lose. It also proves the hole is reachable
    by an ordinary client action, not only by a service-level call."""
    _assert_b1_hole_is_refused(stack, "MP1", child_replace_scenario_via_api_and_die)


# --------------------------------------------------------------------------- #
# SW2 — the refusal is permanent; only a regeneration restores 200
# --------------------------------------------------------------------------- #


def test_sw2_a_world_for_a_replaced_document_never_becomes_valid_without_a_regeneration(
    stack: Stack,
) -> None:
    """WHAT IT PROVES. Once the B1 state exists, reading it does not repair it:
    three reads with brand-new services and one read from a separate process
    all answer 409 ``WORLD_PUBLICATION_STALE``, and the persisted tree
    (every file's size and mtime_ns — the rule-60 inputs) is byte-for-byte and
    stat-for-stat unchanged across all of them. A ``POST …/world/generate``
    then answers 200, and only then do the surfaces answer 200 again.

    WHY THE PROCESS BOUNDARY MATTERS. "It never becomes valid" is a claim about
    state, not about one object's memory. A repeated read inside one process
    would prove only that one cache stayed cold; repeating it in a FRESH
    process proves the disk itself carries the refusal, and repeating it after
    the regeneration proves the refusal was not a permanent poisoning of the
    scenario."""
    root, sid = _root_of(stack), stack.sid
    _run_child(child_replace_scenario_and_die, str(root), sid, _document(stack, "sw2-replaced"))

    tree_before = _tree(stack.store, sid)
    repeats = [_fresh_answers(root, sid).answers for _ in range(3)]
    from_child = _child_answers(root, sid)
    for index, answers in enumerate(repeats):
        for route in WORLD_SURFACES:
            assert answers[route] == (409, STALE), (index, route, answers)
    for route in WORLD_SURFACES:
        assert from_child[route] == (409, STALE), (route, from_child)
    assert _tree(stack.store, sid) == tree_before, (
        "a refused read REPAIRED or re-published something — the world guard is a PURE "
        "comparison and must never write"
    )

    regenerated = stack.client.post(f"{API}/{sid}/world/generate")
    assert regenerated.status_code == 200, regenerated.text[:300]
    assert stack.client.post(f"{API}/{sid}/design/targets").status_code == 200

    after = _fresh_answers(root, sid).answers
    after_child = _child_answers(root, sid)
    for route in WORLD_SURFACES:
        assert after[route] == (200, None), (route, after)
        assert after_child[route] == (200, None), (route, after_child)
    _record(
        "SW2",
        processes=5,
        stale_reads=len(repeats) * len(WORLD_SURFACES) + len(WORLD_SURFACES),
        tree_unchanged=True,
        after_regeneration=after,
    )


# --------------------------------------------------------------------------- #
# MP2 — death between arrays.npz and the record; recovery by regeneration
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("label", "child", "fragment"),
    [
        ("generate", child_generate_and_die_before_the_record, "missing"),
        ("save", child_save_and_die_before_the_record, "arrays.npz revision"),
    ],
    ids=["record_absent_after_generate", "record_names_the_previous_arrays"],
)
def test_mp2_an_uncommitted_generation_is_refused_and_a_later_one_recovers(
    stack: Stack, label: str, child: Any, fragment: str
) -> None:
    """WHAT IT PROVES. A child publishes ``arrays.npz`` and dies before the
    record publication — correction Q3 kill point B — in BOTH reachable shapes:
    after ``generate``'s rule-46 invalidation the record is ABSENT, and after a
    direct ``_save`` the record on disk is the PREVIOUS generation's and names
    an ``arrays.npz`` that has just been replaced. Both are refused 409
    ``WORLD_PUBLICATION_STALE`` on every surface, with the rejection reason
    naming the actual defect, and a subsequent successful generation answers
    200. The record being published LAST is what makes a generation visible
    only when it is complete.

    WHY THE PROCESS BOUNDARY MATTERS. The window between the two publications
    is a few hundred microseconds inside one function; the only way to leave a
    state INSIDE it is to remove the process that would have closed it. In
    process, the store lock closes this window by construction, so an
    in-process test cannot even construct the state — it would have to
    hand-write the files, which proves nothing about what a real writer
    leaves."""
    root, sid = _root_of(stack), stack.sid
    before = _disk(stack.store, sid)

    _run_child(child, str(root), sid)

    after = _disk(stack.store, sid)
    assert after.arrays_revision != before.arrays_revision, (
        f"MP2/{label}: arrays.npz was not republished — the child never reached the window"
    )
    assert after.scenario_revision == before.scenario_revision
    assert after.recorded_arrays != after.arrays_revision, (
        f"MP2/{label}: the surviving record names the LIVE arrays — no window was left"
    )
    rejection = after.rejection(sid)
    assert rejection is not None and fragment in rejection, (label, rejection)

    fresh = _fresh_answers(root, sid).answers
    from_child = _child_answers(root, sid)
    for route in WORLD_SURFACES:
        assert fresh[route] == (409, STALE), (route, fresh)
        assert from_child[route] == (409, STALE), (route, from_child)

    assert stack.client.post(f"{API}/{sid}/world/generate").status_code == 200
    assert stack.client.post(f"{API}/{sid}/design/targets").status_code == 200
    recovered = _fresh_answers(root, sid).answers
    recovered_child = _child_answers(root, sid)
    for route in WORLD_SURFACES:
        assert recovered[route] == (200, None), (route, recovered)
        assert recovered_child[route] == (200, None), (route, recovered_child)
    _record(
        f"MP2[{label}]",
        processes=3,
        rejection=rejection,
        refused=fresh,
        recovered=recovered,
    )


# --------------------------------------------------------------------------- #
# MP3 — two concurrent generators, both record orderings
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("order", "expected"),
    [("A_records_last", (409, STALE)), ("B_records_last", (200, None))],
)
def test_mp3_two_concurrent_generators_commit_at_most_one_generation(
    stack: Stack, order: str, expected: tuple[int, str | None]
) -> None:
    """WHAT IT PROVES. Two REAL generator processes are stepped through their
    four publications by the parent. Their ``arrays.npz`` publications are
    ordered A then B (so B's bytes are the live ones), and the parameter
    chooses which record lands LAST. Whichever way it falls, AT MOST ONE
    generation is committed: when B's record lands last it names the live
    arrays and every surface answers 200; when A's record lands last it names
    an ``arrays.npz`` that B has replaced and every surface answers 409
    ``WORLD_PUBLICATION_STALE``. A mixed pair is NEVER a 200. This is
    correction Q4's optimistic-writer claim measured rather than argued: a lost
    update costs a regeneration, never a wrong answer.

    WHY THE PROCESS BOUNDARY MATTERS. ``ScenarioStore.lock`` is an in-process
    ``RLock``. Two generators inside one interpreter are SERIALIZED by it and
    can never interleave their publications, so the interleaving this test
    measures is unreachable without two processes — it is precisely the
    concurrency the lock does not cover."""
    root, sid = _root_of(stack), stack.sid
    a = _start_checkpointed(root, sid, "generator-A")
    b = _start_checkpointed(root, sid, "generator-B")

    a.begin()
    revision_a = a.publish("arrays")
    a.stall("record")
    b.begin()
    revision_b = b.publish("arrays")
    b.stall("record")
    assert revision_a != revision_b, "the two generators installed the same arrays revision"

    first, second = (b, a) if order == "A_records_last" else (a, b)
    first.resume("record")
    second.resume("record")
    a.finish()
    b.finish()

    disk = _disk(stack.store, sid)
    assert disk.arrays_revision == revision_b, (
        "B published its arrays last, so B's bytes must be the live ones"
    )
    committed = [
        revision
        for revision in (revision_a, revision_b)
        if disk.recorded_arrays == revision == disk.arrays_revision
    ]
    assert len(committed) <= 1, f"more than one generation claims to be committed: {committed}"

    fresh = _fresh_answers(root, sid).answers
    from_child = _child_answers(root, sid)
    assert fresh["/world"] == expected, fresh
    assert fresh["/scene"] == expected, fresh
    assert from_child["/world"] == expected, from_child
    assert from_child["/scene"] == expected, from_child
    if expected == (200, None):
        assert committed == [revision_b], committed
        # both generators ran rule 46's invalidation, so the derived set is
        # gone — its typed ABSENT code is what proves the world guard passed
        assert fresh["/design/targets"] == (409, "TARGETS_NOT_GENERATED"), fresh
    else:
        assert committed == [], committed
        assert fresh["/design/targets"] == (409, STALE), fresh
    _record(
        f"MP3[{order}]",
        processes=4,
        arrays_revisions=[revision_a, revision_b],
        recorded_arrays=disk.recorded_arrays,
        live_arrays=disk.arrays_revision,
        committed_generations=len(committed),
        answers=fresh,
    )


# --------------------------------------------------------------------------- #
# MP4 — the Q1.1 interleaving, WITH the post-hoc-stat counterfactual
# --------------------------------------------------------------------------- #


def test_mp4_the_q1_1_interleaving_is_refused_and_a_post_hoc_stat_would_have_passed_it(
    stack: Stack,
) -> None:
    """WHAT IT PROVES. Correction Q1.1's interleaving, exactly, INCLUDING its
    stall point: P2 replaces its ``arrays.npz`` and stalls inside
    ``publish_npz``'s ``_fsync_directory``; P1 then runs a whole generation
    (arrays + record); P2 wakes, its ``publish_npz`` returns and it publishes
    ITS record. The surviving state is live arrays = P1's bytes beside a record
    naming P2's bytes, and every surface refuses it typed from a fresh process.

    AND THE COUNTERFACTUAL, which is the real point. While P2 is stalled and
    after P1 has committed, this test measures ``file_revision(arrays.npz)``:
    from that instant on, EVERY post-hoc stat of the path P2 could take — and
    the pre-fix code took one the moment ``publish_npz`` returned — yields
    P1's revision. The test then shows that a record built from that value is
    ACCEPTED by ``record_rejection`` — a FALSE 200 — while the record P2
    actually published, built from the revision ``publish_npz`` returned from
    its own ``os.fstat`` (taken before the replace, so already fixed when the
    stall began), is refused. Revert the publication helpers to a post-hoc stat
    and the published record becomes the counterfactual: this test then fails
    on ``recorded_arrays != counterfactual`` before it ever reaches the API
    assertions. The stall has to be INSIDE the arrays publication for that to
    be true — a stall at the record publication would let a reverted post-hoc
    stat run early and read P2's own file.

    MEASURED (mutation M5, replayed on this host with ``publish_npz``'s
    returned identity replaced by ``file_revision(path)`` taken after the
    call): P1's revision, P2's reported revision, the post-hoc stat, the
    recorded revision and the live file all collapse onto ONE value, and
    ``GET …/world`` and ``GET …/scene`` answer **200** on a state whose live
    ``arrays.npz`` P2 never wrote — the false 200 this assertion exists to
    catch.

    WHY THE PROCESS BOUNDARY MATTERS. A post-hoc stat of a path is only WRONG
    when another process can replace that path in between. Inside one process
    the store lock makes the post-hoc stat and the fd-derived revision
    identical, so the defect is literally invisible without a second
    process."""
    root, sid = _root_of(stack), stack.sid
    arrays_path = stack.store.arrays_path(sid)

    p2 = _start_checkpointed(root, sid, "P2", stall_inside_arrays=True)
    p2.begin()
    p2.replace_arrays()  # P2 is now exactly where Q1.1 stalls it

    p1 = _start_checkpointed(root, sid, "P1")
    p1.begin()
    revision_1 = p1.publish("arrays")
    p1.publish("record")
    p1.finish()

    # the interleaving instant: what a post-hoc stat of the PATH says from here
    # on — the value a reverted ``_save`` would record inside P2
    counterfactual = file_revision(arrays_path)

    revision_2 = p2.finish_arrays()
    p2.publish("record")
    p2.finish()

    disk = _disk(stack.store, sid)
    assert revision_1 != revision_2, "the two generations installed the same arrays revision"
    assert counterfactual == revision_1, (
        "P1's arrays must be the live ones at the interleaving instant"
    )
    assert disk.arrays_revision == revision_1, "P1's arrays must still be the live ones"
    assert disk.recorded_arrays == revision_2, (
        "the surviving record must name the bytes P2's OWN publish_npz installed"
    )
    assert disk.recorded_arrays != counterfactual, (
        "the record names the value a POST-HOC stat of arrays.npz would have produced: "
        "the Q1.1 defect is back — publish_npz's fd-derived revision was reverted to "
        f"a stat of the path (record={disk.recorded_arrays}, post-hoc={counterfactual})"
    )

    assert disk.scenario_revision is not None and disk.arrays_revision is not None
    real_rejection = disk.rejection(sid)
    assert real_rejection is not None and "arrays.npz revision" in real_rejection, real_rejection
    counterfactual_record = build_world_record(
        scenario_id=sid,
        scenario_revision=disk.scenario_revision,
        arrays_revision=counterfactual,
        stats={},
    )
    assert (
        record_rejection(
            counterfactual_record,
            scenario_id=sid,
            scenario_revision=disk.scenario_revision,
            arrays_revision=disk.arrays_revision,
        )
        is None
    ), "the counterfactual must be ACCEPTED — that is what makes it a FALSE 200"

    fresh = _fresh_answers(root, sid).answers
    from_child = _child_answers(root, sid)
    for route in ("/world", "/scene"):
        assert fresh[route] == (409, STALE), (route, fresh)
        assert from_child[route] == (409, STALE), (route, from_child)
    _record(
        "MP4",
        processes=3,
        p1_arrays=revision_1,
        p2_arrays=revision_2,
        post_hoc_stat=counterfactual,
        recorded_arrays=disk.recorded_arrays,
        counterfactual_would_be="200 (accepted)",
        actual="409 " + STALE,
        rejection=real_rejection,
    )


# --------------------------------------------------------------------------- #
# MP5 — a reader process against a writer loop: no unmapped 500s
# --------------------------------------------------------------------------- #

#: the typed answers a reader may observe while a writer loops PUT + generate.
#: Every one of them is a deliberate contract: 200, the world guard's two 409s,
#: the snapshot-protocol 409 and the derived artifact's own ABSENT code.
ALLOWED_ANSWERS: frozenset[str] = frozenset(
    {
        "200 None",
        f"409 {STALE}",
        "409 WORLD_NOT_GENERATED",
        "409 READ_SNAPSHOT_CHANGED",
        "409 TARGETS_NOT_GENERATED",
    }
)

WRITER_ITERATIONS = 6


def test_mp5_a_reader_process_against_a_writer_loop_answers_only_typed_codes(
    stack: Stack,
) -> None:
    """WHAT IT PROVES. A separate reader process hammers ``/world``, ``/scene``
    and ``/design/targets`` while this process runs a writer loop of
    ``PUT`` + ``POST …/world/generate`` + ``POST …/design/targets``. Every
    answer the reader observes is in the typed set (200, the world guard's two
    409s, the bound-read 409 and the derived artifact's ABSENT code); there are
    ZERO 500s and zero answers with no code at all. The measured distribution
    is reported in the assertion message, so the test states what it actually
    saw rather than only that nothing broke.

    WHY THE PROCESS BOUNDARY MATTERS. The reader must be able to land INSIDE a
    writer's critical section — between the document publication and the
    invalidation, or between ``arrays.npz`` and the record. Inside one process
    the store lock forbids exactly that, so an in-process reader can only ever
    observe committed states and the whole question goes unasked. The reader
    starts on a ``Barrier`` shared with the writer and stops on the writer's
    ``Event``; nothing here is timed."""
    root, sid = _root_of(stack), stack.sid
    proc, stop, ready, conn = _start_reader(root, sid, WORLD_SURFACES)

    writes = 0
    try:
        ready.wait(BARRIER_TIMEOUT)
        for index in range(WRITER_ITERATIONS):
            document = json.loads(_document(stack, f"mp5-{index}"))
            put = stack.client.put(f"{API}/{sid}", json=document)
            assert put.status_code == 200, put.text[:300]
            generated = stack.client.post(f"{API}/{sid}/world/generate")
            assert generated.status_code == 200, generated.text[:300]
            targets = stack.client.post(f"{API}/{sid}/design/targets")
            assert targets.status_code == 200, targets.text[:300]
            writes += 3
    finally:
        stop.set()

    assert conn.poll(STEP_TIMEOUT), (
        f"the reader process sent no counts within {STEP_TIMEOUT}s "
        f"(alive={proc.is_alive()}, exitcode={proc.exitcode})"
    )
    report = conn.recv()
    _join(proc, expect_exitcode=0)

    counts: dict[str, int] = report["counts"]
    distribution: Counter[str] = Counter()
    for key, count in counts.items():
        distribution[key.split(" -> ", 1)[1]] += count
    pretty = ", ".join(f"{answer}={n}" for answer, n in sorted(distribution.items()))

    assert report["reads"] >= 30, (
        f"MP5 is vacuous: only {report['reads']} reads against {writes} writes ({pretty})"
    )
    unmapped = {a: n for a, n in distribution.items() if a.endswith(" None") and a != "200 None"}
    assert not unmapped, (
        f"MP5 observed answers with NO error code (an unmapped 500 has no code at all): "
        f"{unmapped} — full distribution: {pretty}"
    )
    outside = {a: n for a, n in distribution.items() if a not in ALLOWED_ANSWERS}
    assert not outside, (
        f"MP5 observed answers outside the typed set {sorted(ALLOWED_ANSWERS)}: {outside} — "
        f"full distribution over {report['reads']} reads and {writes} writes: {pretty}"
    )
    _record(
        "MP5",
        processes=1,
        reads=report["reads"],
        writes=writes,
        per_route=counts,
        distribution=dict(distribution),
    )


# --------------------------------------------------------------------------- #
# SW3 — the structural requirement: every case reads from a fresh process /
#        fresh services, and no in-memory cache participates
# --------------------------------------------------------------------------- #

#: every case of this module, by function name. SW3 checks each one
#: STRUCTURALLY, so the requirement holds even when a case is run alone and
#: even when a future edit rewrites a case's body.
PROCESS_CASES: tuple[str, ...] = (
    "test_sw1_a_document_published_without_the_invalidation_is_refused_from_a_fresh_process",
    "test_mp1_the_same_hole_driven_through_the_real_put_route",
    "test_sw2_a_world_for_a_replaced_document_never_becomes_valid_without_a_regeneration",
    "test_mp2_an_uncommitted_generation_is_refused_and_a_later_one_recovers",
    "test_mp3_two_concurrent_generators_commit_at_most_one_generation",
    "test_mp4_the_q1_1_interleaving_is_refused_and_a_post_hoc_stat_would_have_passed_it",
    "test_mp5_a_reader_process_against_a_writer_loop_answers_only_typed_codes",
)
#: the helpers that start a REAL separate process
CHILD_LAUNCHERS: frozenset[str] = frozenset(
    {"_run_child", "_spawn", "_child_answers", "_start_checkpointed", "_start_reader"}
)
#: the helpers whose answers come from an empty-cache reader (a fresh process,
#: or brand-new service objects)
FRESH_READERS: frozenset[str] = frozenset({"_fresh_answers", "_child_answers", "_start_reader"})
#: SW1 / MP1 delegate their body to this shared assertion helper
DELEGATES: dict[str, str] = {
    "test_sw1_a_document_published_without_the_invalidation_is_refused_from_a_fresh_process": (
        "_assert_b1_hole_is_refused"
    ),
    "test_mp1_the_same_hole_driven_through_the_real_put_route": "_assert_b1_hole_is_refused",
}


def _called_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def _module_tree() -> ast.Module:
    return ast.parse(inspect.getsource(inspect.getmodule(_module_tree)))  # type: ignore[arg-type]


def _functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


def test_sw3_every_case_reads_from_a_fresh_process_and_no_cache_participates(
    stack: Stack,
) -> None:
    """WHAT IT PROVES, structurally and then live.

    STRUCTURALLY, over this module's own AST: (1) every case in
    ``PROCESS_CASES`` starts a REAL spawn child and takes its verdict from an
    empty-cache reader; (2) this module contains NO ``sleep`` call anywhere, so
    nothing here is synchronized by waiting a while; (3) every ``join`` /
    ``poll`` / ``wait`` call passes a timeout, and every ``recv`` sits in a
    function that polled first — so no wait can hang the suite; (4) every
    process is created from the SPAWN context, never fork.

    LIVE: ``_fresh_answers`` really does build a new object graph each time (a
    different token, and ``cache_before == 0`` every time), and its answers
    match a genuinely separate process's on the same committed state.

    WHY THE PROCESS BOUNDARY MATTERS, and why this test is structural. The
    other cases' claims all reduce to "a reader that never saw the previous
    state still refuses it". That claim is only as good as the reader, so the
    reader is audited here rather than trusted per case.
    ``tests/test_artifact_read_api.py::cold_services`` rebuilds services inside
    the SAME interpreter: it is a fresh-SERVICES reader and a fine one, but it
    is NOT a fresh process and cannot witness a state that only exists because
    a writer died — which is why this module launches real children instead of
    reusing it."""
    tree = _module_tree()
    functions = _functions(tree)

    missing = [name for name in PROCESS_CASES if name not in functions]
    assert not missing, f"PROCESS_CASES names functions that do not exist: {missing}"

    for name in PROCESS_CASES:
        called = _called_names(functions[name])
        delegate = DELEGATES.get(name)
        if delegate is not None:
            assert delegate in called, f"{name}: does not delegate to {delegate}"
            called |= _called_names(functions[delegate])
        assert called & CHILD_LAUNCHERS, (
            f"{name}: starts no real separate process (expected one of "
            f"{sorted(CHILD_LAUNCHERS)}) — an in-process 'cold' reader does not satisfy SW3"
        )
        assert called & FRESH_READERS, (
            f"{name}: takes its verdict from no empty-cache reader (expected one of "
            f"{sorted(FRESH_READERS)})"
        )

    all_called = _called_names(tree)
    assert "sleep" not in all_called, "this module must never synchronize (or settle) by sleeping"

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr in {"join", "poll", "wait"}:
            assert node.args or node.keywords, (
                f"line {node.lineno}: {node.func.attr}() without a timeout can hang the suite"
            )
    for name, function in functions.items():
        called = _called_names(function)
        if "recv" in called:
            assert "poll" in called, f"{name}: recv() without a preceding bounded poll()"

    processes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "Process"
    ]
    assert processes, "no process is created at all"
    for node in processes:
        assert isinstance(node.func.value, ast.Name) and node.func.value.id == "SPAWN", (
            f"line {node.lineno}: a Process must come from the SPAWN context — a forked "
            "child inherits the parent's warm world cache and proves nothing"
        )
    assert SPAWN.get_start_method() == "spawn"

    root, sid = _root_of(stack), stack.sid
    first = _fresh_answers(root, sid)
    second = _fresh_answers(root, sid)
    assert first.services_token != second.services_token, "the two reads shared service objects"
    assert (first.cache_before, second.cache_before) == (0, 0), (
        "a fresh read started with a POPULATED world cache"
    )
    from_child = _child_answers(root, sid)
    assert first.answers == second.answers == from_child, (
        f"fresh services and a fresh PROCESS disagree: {first.answers} vs {from_child}"
    )
    assert all(answer == (200, None) for answer in from_child.values()), from_child
    _record(
        "SW3",
        cases=len(PROCESS_CASES),
        processes=1,
        spawn_children_started_so_far=PROCESS_COUNT[0],
        sleep_calls=0,
    )
