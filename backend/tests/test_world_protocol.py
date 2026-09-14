"""AC-01F T7 / T15 / T17 — the scenario ⇄ world snapshot protocol (F06-A, the
scenario/world half).

Stage A measured what the world half of a read used to be: ``WorldService``
read the scenario document at one instant (`world_service.py:100`) and took the
world object at another (`:101-103`) with **nothing binding the two**, the
scenario PUT was two separate critical sections (`api/scenarios.py:80-81`), and
``WorldService._save`` ran unlocked and unfingerprinted (§7.5). Four literals
were measured on HEAD ``12d7725`` and are the pre-change oracles of this
module — each is quoted at the test that closes it:

    R3b   an in-flight ``GET /scene`` answered **200** describing a world the
          PUT had already deleted (``terrain.zMax 120.638291``, every derived
          slot ``null``)                                (p4_f06a_world_race2.py)
    R3d   ONE response carried ``world.depth 250.0 / referenceElevation 100.0 /
          bottomElevation −150.0`` from the OLD document beside
          ``terrain.zMax 267.508616`` from the NEW world object
          (``SCENARIO_WORLD_MISMATCH = True``)         (p4_f06a_load_mismatch.py)
    §7.5A a scenario PUT landing inside ``generate_world`` left ``arrays.npz``,
          ``derived/world.json`` and the cache holding a world built for the
          REPLACED document, and ``GET /world`` answered **200**
                                              (p4_f06b_unlocked_world_save.py)
    §4.9  with the world warm in memory and ``arrays.npz`` deleted,
          ``GET /world`` and ``GET /world/slice`` answered **200** — "is the
          world there?" depended on process state          (probe 2 audit.json)

Two more literals were measured on the INTERMEDIATE commit-3 draft (the state
this module's C4 / cold-load tests close) and are quoted at their tests:

    C4    ``POST /world/generate`` on a schemaVersion-1 document answered
          **409 JOB_INPUTS_CHANGED** — the A10 migration-on-read rewrote
          ``scenario.json`` from inside the draft's own ``store.get``, so the
          revision captured before it missed and the generation blamed a race
          that had not happened. At HEAD ``12d7725`` (no guard at all) the same
          call answered **200**              (scratch ac01f_C/c4_probe.py)
    cold  with the cold ``np.load`` paused and a real scenario PUT landing in
          the pause, ``GET /world`` answered **500 Internal Server Error** —
          ``FileNotFoundError`` escaped ``load_bound`` untyped
                                       (scratch ac01f_C/arrays_race_probe.py)
    moved with the same pause and a world REGENERATION landing in it,
          ``GET /world`` answered **200** for a world loaded from a file the
          reader had never stat'ed, reported under the OLD arrays revision
                                      (scratch ac01f_C/arrays_moved_probe.py,
                                       the draft body replayed verbatim)

Every hook below changes TIMING only (the Stage A probe-4 technique): a
``threading.Event`` pause wrapped around an unmodified call, or an ``os.utime``
bump of a file whose BYTES are never touched. No read or write primitive,
ordering or payload is changed by a hook.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from minegen.core.models import ScenarioCreate
from minegen.core.revision import file_revision
from minegen.services.artifact_errors import ReadSnapshotChangedError, StaleInputsError
from minegen.services.scenario_service import ScenarioStore
from minegen.services.world_service import SNAPSHOT_ATTEMPTS, WorldService
from tests.conftest import small_scenario

API = "/api/v1/scenarios"

#: Stage A pre-change literals, quoted so a reader of this module never has to
#: leave it to see what the AFTER is being contrasted with.
PRE_CHANGE_R3B = "200 describing a deleted world: terrain.zMax 120.638291, every derived slot null"
PRE_CHANGE_R3D = (
    "SCENARIO_WORLD_MISMATCH = True: world.depth 250.0 / referenceElevation 100.0 / "
    "bottomElevation -150.0 (OLD document) with terrain.zMax 267.508616 (NEW world)"
)
PRE_CHANGE_UNLOCKED_SAVE = (
    "arrays.npz + derived/world.json + cache holding a world built for the REPLACED "
    "document (terrain zMax 120.6383 while scenario.json said baseElevation 400); GET /world 200"
)
PRE_CHANGE_WARM_CACHE = "GET /world and /world/slice 200 after arrays.npz was deleted"
#: the two INTERMEDIATE-draft literals (HEAD 12d7725 answered 200 for the first)
PRE_CHANGE_MIGRATION_GENERATE = (
    "POST /world/generate on a schemaVersion-1 document: 409 JOB_INPUTS_CHANGED "
    "(HEAD 12d7725: 200), nothing persisted, the migration blamed as a race"
)
PRE_CHANGE_COLD_LOAD_VANISHED = "GET /world 500 Internal Server Error (FileNotFoundError escaped)"
PRE_CHANGE_COLD_LOAD_MOVED = (
    "GET /world 200 for a world loaded from a file the reader never stat'ed, "
    "reported under the OLD arrays revision"
)


def _v1_document(store: ScenarioStore, sid: str) -> None:
    """Rewrite the persisted document as a schemaVersion-1 one, so the next
    ``ScenarioStore.get`` takes the A10 migration branch. Only the FILE is
    touched; the migration itself is production code and is unchanged."""
    path = store.scenario_path(sid)
    document = json.loads(path.read_text(encoding="utf-8"))
    document.pop("fieldSampling")
    document["blockModel"] = {"dx": 10.0, "dy": 10.0, "dz": 10.0}
    document["schemaVersion"] = 1
    path.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _create(client: TestClient) -> str:
    payload = small_scenario().model_dump(by_alias=True, exclude={"id", "schema_version"})
    created = client.post(API, json=payload)
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _generated(client: TestClient) -> str:
    sid = _create(client)
    assert client.post(f"{API}/{sid}/world/generate").status_code == 200
    return sid


def _document(client: TestClient, sid: str) -> dict[str, Any]:
    doc = client.get(f"{API}/{sid}").json()
    doc.pop("id")
    doc.pop("schemaVersion")
    return dict(doc)


def _answer(response: Any) -> tuple[int, str | None]:
    try:
        body = response.json()
    except ValueError:  # pragma: no cover - a JSON body is always returned here
        return response.status_code, None
    if isinstance(body, dict) and isinstance(body.get("detail"), dict):
        return response.status_code, str(body["detail"].get("code"))
    return response.status_code, None


def _identity(scene: dict[str, Any]) -> tuple[float, float, float, float]:
    """The four numbers Stage A R3d found disagreeing inside ONE response:
    three from the scenario DOCUMENT and one from the WORLD object."""
    return (
        float(scene["world"]["depth"]),
        float(scene["world"]["referenceElevation"]),
        float(scene["world"]["bottomElevation"]),
        float(scene["terrain"]["zMax"]),
    )


def _run(target: Callable[[], Any]) -> tuple[threading.Thread, dict[str, Any]]:
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = target()
        except BaseException as exc:  # the thread reports through the box
            box["error"] = exc
        box["done"] = True

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, box


class _PauseAfterLoadBound:
    """Pause the FIRST ``WorldService.load_bound`` AFTER it has returned — i.e.
    between the scenario/world binding and the lock-held artifact observation,
    OUTSIDE the store lock, so the concurrent mutation really runs. TIMING
    only: the original call is made, unmodified, and its result is returned."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.inside = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        original = WorldService.load_bound
        armed = [True]

        def patched(svc: WorldService, scenario_id: str) -> Any:
            result = original(svc, scenario_id)
            self.calls += 1
            if armed[0]:
                armed[0] = False
                self.inside.set()
                assert self.release.wait(30), "the test never released the paused read"
            return result

        monkeypatch.setattr(WorldService, "load_bound", patched)


# --------------------------------------------------------------------------- #
# T7 — R3b: a PUT during a paused scene
# --------------------------------------------------------------------------- #


def test_a_scenario_put_during_a_paused_scene_never_serves_a_deleted_world(
    client: TestClient, store: ScenarioStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3b, impossible. The scene is paused after ``load_bound`` and a scenario
    PUT lands (one locked section now: document write + arrays/derived
    invalidation + cache drop). The bound snapshot then misses, the read is
    retried, and the retry finds no world.

    Pre-change literal: ``{PRE_CHANGE_R3B}``."""
    sid = _generated(client)
    assert client.get(f"{API}/{sid}/scene").status_code == 200

    pause = _PauseAfterLoadBound(monkeypatch)
    reader, read_box = _run(lambda: client.get(f"{API}/{sid}/scene"))
    assert pause.inside.wait(30), "the scene never reached its binding"

    doc = _document(client, sid)
    doc["seed"] = 777
    assert client.put(f"{API}/{sid}", json=doc).status_code == 200
    # the PUT completed WHILE the scene is in flight: the world is gone
    assert not store.arrays_path(sid).exists()
    assert list(store.derived_dir(sid).iterdir()) == []

    pause.release.set()
    reader.join(60)
    assert "error" not in read_box, read_box.get("error")
    status, code = _answer(read_box["value"])
    assert status == 409, (status, code, PRE_CHANGE_R3B)
    assert code in {"WORLD_NOT_GENERATED", "READ_SNAPSHOT_CHANGED"}, code


def test_a_put_and_regeneration_during_a_paused_scene_cannot_mix_two_documents(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3d, impossible. The mutation is a PUT **plus** a world regeneration, so
    a world exists on both sides of it and the read can complete. The four
    numbers of ``_identity`` must then all come from the SAME document — never
    three from one and the terrain from the other.

    Pre-change literal: ``{PRE_CHANGE_R3D}``."""
    sid = _generated(client)
    old = _identity(client.get(f"{API}/{sid}/scene").json())

    pause = _PauseAfterLoadBound(monkeypatch)
    reader, read_box = _run(lambda: client.get(f"{API}/{sid}/scene"))
    assert pause.inside.wait(30)

    doc = _document(client, sid)
    doc["seed"] = 777
    doc["world"]["depth"] = 300.0
    assert client.put(f"{API}/{sid}", json=doc).status_code == 200
    assert client.post(f"{API}/{sid}/world/generate").status_code == 200
    new = _identity(client.get(f"{API}/{sid}/scene").json())
    # the two documents really are distinguishable in all four numbers
    assert old[0] == 250.0 and old[2] == -150.0
    assert new[0] == 300.0 and new[2] == -200.0
    assert old[3] != new[3], (old, new)

    pause.release.set()
    reader.join(60)
    assert "error" not in read_box, read_box.get("error")
    response = read_box["value"]
    assert response.status_code == 200, _answer(response)
    served = _identity(response.json())
    assert served in (old, new), (served, old, new, PRE_CHANGE_R3D)


# --------------------------------------------------------------------------- #
# T17 — the world writer's optimistic publish guard
# --------------------------------------------------------------------------- #


def test_a_scenario_put_during_world_generation_fails_the_publish_closed(
    client: TestClient,
    store: ScenarioStore,
    world_service: WorldService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§7.5 case A, closed. ``generate_world`` is paused (it runs OUTSIDE the
    store lock by contract) and a scenario PUT lands; the publish then finds a
    ``scenario.json`` that moved and refuses — nothing persisted, nothing
    cached, 409 ``JOB_INPUTS_CHANGED`` (a GENERATION whose inputs moved, never
    ``READ_SNAPSHOT_CHANGED``).

    Pre-change literal: ``{PRE_CHANGE_UNLOCKED_SAVE}``."""
    import minegen.services.world_service as world_module

    sid = _create(client)
    original = world_module.generate_world
    inside = threading.Event()
    release = threading.Event()

    def paused(*args: Any, **kwargs: Any) -> Any:
        world = original(*args, **kwargs)
        inside.set()
        assert release.wait(60), "the test never released the paused generation"
        return world

    monkeypatch.setattr(world_module, "generate_world", paused)
    worker, box = _run(lambda: _answer(client.post(f"{API}/{sid}/world/generate")))
    assert inside.wait(60), "the generation never started"

    doc = _document(client, sid)
    doc["seed"] = 4242
    assert client.put(f"{API}/{sid}", json=doc).status_code == 200

    release.set()
    worker.join(60)
    assert "error" not in box, box.get("error")
    assert box["value"] == (409, "JOB_INPUTS_CHANGED"), (box, PRE_CHANGE_UNLOCKED_SAVE)
    # nothing was published for the REPLACED document
    assert not store.arrays_path(sid).exists()
    assert not (store.derived_dir(sid) / "world.json").exists()
    assert sid not in world_service._cache
    assert _answer(client.get(f"{API}/{sid}/world")) == (409, "WORLD_NOT_GENERATED")

    # and the normal path, with nothing moving, still answers 200
    monkeypatch.setattr(world_module, "generate_world", original)
    assert client.post(f"{API}/{sid}/world/generate").status_code == 200
    assert client.get(f"{API}/{sid}/world").status_code == 200


def test_a_warm_cache_without_arrays_is_no_longer_a_world(
    client: TestClient, store: ScenarioStore, world_service: WorldService
) -> None:
    """Probe 2 §4.9, closed for the world routes too (the scene's half is
    ``tests/test_artifact_read_api.py::test_the_scene_refuses_a_warm_cache_without_arrays``).
    The cache entry carries the ``arrays.npz`` revision it was built at, so a
    deleted world is a cache MISS — not a repair and not a lie.

    Pre-change literal: ``{PRE_CHANGE_WARM_CACHE}``."""
    sid = _generated(client)
    assert client.get(f"{API}/{sid}/world").status_code == 200
    assert sid in world_service._cache  # warm

    store.arrays_path(sid).unlink()
    assert sid in world_service._cache  # still warm: nothing invalidated it
    assert _answer(client.get(f"{API}/{sid}/world")) == (409, "WORLD_NOT_GENERATED")
    assert _answer(client.get(f"{API}/{sid}/world/slice", params={"axis": "z", "index": 0})) == (
        409,
        "WORLD_NOT_GENERATED",
    )
    assert _answer(client.get(f"{API}/{sid}/scene")) == (409, "WORLD_NOT_GENERATED")
    # the same fact, stated where it lives: the world guard is ``arrays.npz``
    # on disk (S11 deleted ``WorldService.is_generated``, which had no
    # production caller and used a ``Path.is_file`` probe the live guard —
    # ``file_revision`` — does not share)
    assert not store.arrays_path(sid).exists()


# --------------------------------------------------------------------------- #
# T15 — the bounded snapshot retry
# --------------------------------------------------------------------------- #


class _BumpAfterLoadBound:
    """Move ``scenario.json``'s mtime AFTER each of the first ``misses``
    bindings, so the snapshot's lock-held re-stat cannot agree with it. The
    BYTES are never touched — only ``st_mtime_ns``, which is what
    ``file_revision`` (rule 60) hashes — so a read that does get through
    assembles exactly the scene it would have assembled anyway."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, store: ScenarioStore, misses: int) -> None:
        self.calls = 0
        original = WorldService.load_bound

        def patched(svc: WorldService, scenario_id: str) -> Any:
            result = original(svc, scenario_id)
            self.calls += 1
            if self.calls <= misses:
                path = store.scenario_path(scenario_id)
                st = os.stat(path)
                os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
            return result

        monkeypatch.setattr(WorldService, "load_bound", patched)


def test_the_snapshot_retry_is_bounded_and_answers_read_snapshot_changed(
    client: TestClient,
    store: ScenarioStore,
    world_service: WorldService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A9 / T15: a scenario whose inputs keep moving answers 409
    ``READ_SNAPSHOT_CHANGED`` — NOT ``JOB_INPUTS_CHANGED``, which means a
    GENERATION whose inputs moved (nothing was built or discarded here). The
    retry is bounded: exactly :data:`SNAPSHOT_ATTEMPTS` bindings are made per
    read, and a second read pays the same bound rather than a growing one."""
    sid = _generated(client)
    assert client.get(f"{API}/{sid}/scene").status_code == 200

    hook = _BumpAfterLoadBound(monkeypatch, store, misses=2 * SNAPSHOT_ATTEMPTS)
    assert _answer(client.get(f"{API}/{sid}/scene")) == (409, "READ_SNAPSHOT_CHANGED")
    assert hook.calls == SNAPSHOT_ATTEMPTS == 3, hook.calls
    with pytest.raises(ReadSnapshotChangedError):
        world_service.scene(sid)
    assert hook.calls == 2 * SNAPSHOT_ATTEMPTS, hook.calls

    # the two codes are structurally distinct, not merely different strings in
    # one table: a read-snapshot failure can never be reported as a GENERATION
    # whose inputs moved, whatever a router does with it
    assert ReadSnapshotChangedError.code == "READ_SNAPSHOT_CHANGED"
    assert StaleInputsError.code == "JOB_INPUTS_CHANGED"
    assert not issubclass(ReadSnapshotChangedError, StaleInputsError)
    assert not issubclass(StaleInputsError, ReadSnapshotChangedError)


def test_a_snapshot_that_misses_twice_still_answers_a_consistent_scene(
    client: TestClient, store: ScenarioStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other side of the bound: misses on attempts 1 and 2 followed by a
    hit is a 200, byte-equal to the undisturbed read. A bounded retry that
    could not succeed would be a fail-closed pathology, not a protocol."""
    sid = _generated(client)
    undisturbed = client.get(f"{API}/{sid}/scene")
    assert undisturbed.status_code == 200

    hook = _BumpAfterLoadBound(monkeypatch, store, misses=SNAPSHOT_ATTEMPTS - 1)
    retried = client.get(f"{API}/{sid}/scene")
    assert retried.status_code == 200, _answer(retried)
    assert hook.calls == SNAPSHOT_ATTEMPTS
    assert retried.json() == undisturbed.json()


# --------------------------------------------------------------------------- #
# A10 — migration-on-read inside the scene (the NON-injected Stage A case)
# --------------------------------------------------------------------------- #


def test_a_schema_v1_document_read_inside_the_scene_never_serves_the_warm_cache(
    client: TestClient, store: ScenarioStore, world_service: WorldService
) -> None:
    """Stage A §7.3 / probe 2 §4.8 — the one read-that-writes (A10) and the
    ONLY F06-A demonstration that needs no injected hook at all: rewriting
    ``scenario.json`` with ``"schemaVersion": 1`` makes ``ScenarioStore.get``
    migrate the document and ``clear_derived`` FROM INSIDE the scene's own
    read, deleting ``arrays.npz`` and every derived file.

    Pre-change literal, MEASURED at HEAD: ``GET /scene`` still answered **200**
    with all 17 derived keys ``null``, served from a warm ``WorldService._cache``
    that ``clear_derived`` does not drop. The migration is unchanged (A10); the
    cache is now bound to the revisions it was built at, so the stale entry is
    simply never returned."""
    sid = _generated(client)
    assert client.get(f"{API}/{sid}/scene").status_code == 200
    assert sid in world_service._cache  # warm, exactly as at HEAD

    path = store.scenario_path(sid)
    _v1_document(store, sid)

    status, code = _answer(client.get(f"{API}/{sid}/scene"))
    assert (status, code) == (409, "WORLD_NOT_GENERATED"), (status, code)
    # the migration DID happen on that read (A10 is unchanged) and it really
    # did clear the derived state the warm cache used to paper over
    migrated = json.loads(path.read_text(encoding="utf-8"))
    assert migrated["schemaVersion"] == 2 and "blockModel" not in migrated
    assert not store.arrays_path(sid).exists()
    assert list(store.derived_dir(sid).iterdir()) == []

    # regenerating is the explicit repair; a read never performs one
    assert client.post(f"{API}/{sid}/world/generate").status_code == 200
    assert client.get(f"{API}/{sid}/scene").status_code == 200


def test_generating_the_world_of_a_schema_v1_document_absorbs_the_migration(
    client: TestClient, store: ScenarioStore, world_service: WorldService
) -> None:
    """C4. ``WorldService._bound_scenario`` reads the document as stat →
    ``store.get`` → re-stat and REPEATS while the revision moves, so the A10
    migration-on-read (the ONE documented read that writes) is absorbed by the
    re-read instead of being reported as a race: the FIRST
    ``POST …/world/generate`` on a schemaVersion-1 document succeeds, and the
    world it publishes is bound to the MIGRATED document.

    Pre-change literal (intermediate commit-3 draft):
    ``{PRE_CHANGE_MIGRATION_GENERATE}``. HEAD ``12d7725`` answered 200 with no
    guard at all, so this is a restoration of the HEAD answer under a guard
    that is now only ever true, not a new behaviour."""
    sid = _create(client)
    _v1_document(store, sid)
    path = store.scenario_path(sid)
    assert json.loads(path.read_text(encoding="utf-8"))["schemaVersion"] == 1

    generated = client.post(f"{API}/{sid}/world/generate")
    assert generated.status_code == 200, _answer(generated)

    # the document really was migrated by that very call (A10 unchanged) …
    migrated = json.loads(path.read_text(encoding="utf-8"))
    assert migrated["schemaVersion"] == 2 and "blockModel" not in migrated
    assert "fieldSampling" in migrated
    # … and the world was published for the MIGRATED revision, not discarded
    assert store.arrays_path(sid).exists()
    assert (store.derived_dir(sid) / "world.json").is_file()
    cached = world_service._cache[sid]
    assert cached.scenario_revision == file_revision(path)
    assert cached.arrays_revision == file_revision(store.arrays_path(sid))
    assert client.get(f"{API}/{sid}/world").status_code == 200
    assert client.get(f"{API}/{sid}/scene").status_code == 200
    # a second generation is an ordinary one: nothing migrates, nothing 409s
    assert client.post(f"{API}/{sid}/world/generate").status_code == 200


def test_the_bound_document_read_gives_up_with_read_snapshot_changed(
    store: ScenarioStore, world_service: WorldService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other end of C4's bound: a document whose revision moves on EVERY
    attempt is a READ that could not be bound — 409 ``READ_SNAPSHOT_CHANGED``
    after exactly :data:`SNAPSHOT_ATTEMPTS` ``store.get`` calls, never
    ``JOB_INPUTS_CHANGED`` (nothing was generated and nothing discarded).

    The hook bumps ``st_mtime_ns`` only; the document BYTES are untouched, so
    the bound read is refused purely by the rule-60 identity it captured."""
    scenario = small_scenario()
    store.create(ScenarioCreate(**scenario.model_dump(exclude={"id", "schema_version"})))
    sid = next(p.name for p in store.root.iterdir())
    path = store.scenario_path(sid)
    original = ScenarioStore.get
    calls = {"n": 0}

    def patched(self: ScenarioStore, scenario_id: str) -> Any:
        result = original(self, scenario_id)
        calls["n"] += 1
        st = os.stat(path)
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
        return result

    monkeypatch.setattr(ScenarioStore, "get", patched)
    with pytest.raises(ReadSnapshotChangedError):
        world_service._bound_scenario(sid)
    assert calls["n"] == SNAPSHOT_ATTEMPTS == 3, calls


# --------------------------------------------------------------------------- #
# the cold-load window: arrays stat → lock (cache probe) → np.load
# --------------------------------------------------------------------------- #


class _PauseBeforeArraysLoad:
    """Pause the FIRST ``WorldService._read_arrays`` BEFORE it runs — i.e.
    inside the cold-load window, after ``load_bound`` has stat'ed
    ``arrays.npz`` and probed the cache and before ``np.load`` opens the file,
    OUTSIDE the store lock. TIMING only: the original call is then made,
    unmodified, and its result returned."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.inside = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        original = WorldService._read_arrays
        armed = [True]

        def patched(svc: WorldService, scenario: Any, path: Any) -> Any:
            self.calls += 1
            if armed[0]:
                armed[0] = False
                self.inside.set()
                assert self.release.wait(30), "the test never released the paused load"
            return original(svc, scenario, path)

        monkeypatch.setattr(WorldService, "_read_arrays", patched)


def _cold(world_service: WorldService, sid: str) -> None:
    """Drop the in-memory entry so the next read takes the COLD path, exactly
    as a freshly started process would. Nothing on disk is touched."""
    world_service._cache.pop(sid, None)


def test_arrays_deleted_inside_the_cold_load_window_is_world_not_generated(
    client: TestClient,
    store: ScenarioStore,
    world_service: WorldService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real scenario PUT deletes ``arrays.npz`` while a cold read is paused
    between its stat and ``np.load``. ``FileNotFoundError`` is TYPED as
    ``WorldNotGeneratedError``, so both routes answer 409
    ``WORLD_NOT_GENERATED`` — the honest "there is no world", never a 500.

    Pre-change literal: ``{PRE_CHANGE_COLD_LOAD_VANISHED}``."""

    def answer_of(route: str) -> tuple[int, str | None]:
        sid = _generated(client)
        _cold(world_service, sid)
        pause = _PauseBeforeArraysLoad(monkeypatch)
        reader, box = _run(lambda: client.get(f"{API}/{sid}{route}"))
        assert pause.inside.wait(30), f"{route} never reached the cold load"

        doc = _document(client, sid)
        doc["seed"] = 4141
        assert client.put(f"{API}/{sid}", json=doc).status_code == 200
        assert not store.arrays_path(sid).exists()

        pause.release.set()
        reader.join(60)
        assert "error" not in box, box.get("error")
        monkeypatch.undo()
        return _answer(box["value"])

    assert answer_of("/world") == (409, "WORLD_NOT_GENERATED"), PRE_CHANGE_COLD_LOAD_VANISHED
    assert answer_of("/scene") == (409, "WORLD_NOT_GENERATED"), PRE_CHANGE_COLD_LOAD_VANISHED


def test_arrays_regenerated_inside_the_cold_load_window_is_never_a_mixed_body(
    client: TestClient, world_service: WorldService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The MOVED half of the same window: the world is regenerated while the
    cold read is paused, so ``np.load`` opens a file the reader never stat'ed.
    The world in hand cannot be attested to the captured revision, so the load
    raises ``ReadSnapshotChangedError``:

    * ``GET …/world`` takes no artifact snapshot and answers 409
      ``READ_SNAPSHOT_CHANGED``;
    * ``GET …/scene`` repeats the whole bound load and answers a consistent
      200 — byte-equal to an undisturbed scene, never a body mixing the two
      observations.

    Pre-change literal: ``{PRE_CHANGE_COLD_LOAD_MOVED}``."""
    sid = _generated(client)
    undisturbed = client.get(f"{API}/{sid}/scene")
    assert undisturbed.status_code == 200

    _cold(world_service, sid)
    pause = _PauseBeforeArraysLoad(monkeypatch)
    reader, box = _run(lambda: client.get(f"{API}/{sid}/world"))
    assert pause.inside.wait(30), "/world never reached the cold load"
    assert client.post(f"{API}/{sid}/world/generate").status_code == 200
    pause.release.set()
    reader.join(60)
    assert "error" not in box, box.get("error")
    assert _answer(box["value"]) == (409, "READ_SNAPSHOT_CHANGED"), PRE_CHANGE_COLD_LOAD_MOVED
    monkeypatch.undo()

    _cold(world_service, sid)
    scene_pause = _PauseBeforeArraysLoad(monkeypatch)
    scene_reader, scene_box = _run(lambda: client.get(f"{API}/{sid}/scene"))
    assert scene_pause.inside.wait(30), "/scene never reached the cold load"
    assert client.post(f"{API}/{sid}/world/generate").status_code == 200
    scene_pause.release.set()
    scene_reader.join(60)
    assert "error" not in scene_box, scene_box.get("error")
    served = scene_box["value"]
    assert served.status_code == 200, _answer(served)
    assert _identity(served.json()) == _identity(undisturbed.json())
    assert served.json() == client.get(f"{API}/{sid}/scene").json()


# --------------------------------------------------------------------------- #
# Stage D B1 — the SCENARIO half of load_bound's re-check binds the RESULT
# --------------------------------------------------------------------------- #

#: Stage D B1, measured at commit 3 on this very interleaving (the pause after
#: the bound document read, the writers the real API): ONE ``GET …/world`` body
#: equal to NEITHER the before nor the after state —
#: ``orebody.center [40.0, 20.0, -50.0]`` from the OLD document beside
#: ``terrain.zMax 116.367159085105`` and ``rockQuality.mean 64.97196970309594``
#: from the NEW world. ``GET …/scene`` was already protected (its
#: ``expect_scenario_revision`` binding forces the retry), which is exactly why
#: the two world routes were the surviving R3d surface.
PRE_CHANGE_B1 = (
    "GET /world 200 mixing the OLD document's orebody with the NEW world's "
    "terrain + fields (== BEFORE False, == AFTER False)"
)


class _PauseInsideLoadBound:
    """Pause the FIRST ``WorldService._bound_scenario`` AFTER it returns — i.e.
    INSIDE ``load_bound``, between the bound document read and the
    ``arrays.npz`` stat that precedes the cold ``np.load``, and OUTSIDE the
    store lock so the concurrent mutation really runs. TIMING only: the
    original call is made, unmodified, and its result returned."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.inside = threading.Event()
        self.release = threading.Event()
        original = WorldService._bound_scenario
        armed = [True]

        def patched(svc: WorldService, scenario_id: str) -> Any:
            result = original(svc, scenario_id)
            if armed[0]:
                armed[0] = False
                self.inside.set()
                assert self.release.wait(30), "the test never released the paused read"
            return result

        monkeypatch.setattr(WorldService, "_bound_scenario", patched)


def _world_identity(body: dict[str, Any]) -> tuple[Any, ...]:
    """The three numbers Stage D B1 found disagreeing inside ONE
    ``GET …/world`` body: the orebody comes from the scenario DOCUMENT
    (``build_orebody(scenario.orebody)`` inside ``_read_arrays``), the terrain
    and the field statistics from ``arrays.npz``."""
    return (
        tuple(body["orebody"]["center"]),
        float(body["terrain"]["zMax"]),
        float(body["fields"]["rockQuality"]["mean"]),
    )


@pytest.mark.parametrize(
    "route,params",
    [("/world", {}), ("/world/slice", {"axis": "z", "index": 0})],
    ids=["world", "slice"],
)
def test_a_put_and_regeneration_inside_load_bound_never_mixes_two_documents(
    route: str,
    params: dict[str, Any],
    client: TestClient,
    world_service: WorldService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B1. ``load_bound`` re-stats BOTH inputs under the lock, but the scenario
    half used to gate only the CACHE PUBLISH while the ``return`` was
    unconditional — so the arrays half was typed and the scenario half was
    not, and the R3d mixed body this protocol claims to have made impossible
    was still served by the two world routes. The two halves are symmetric now.

    The mutation is a PUT **plus** a world regeneration, so a world exists on
    both sides of it and the read CAN complete; what it may not do is complete
    with a body that was never true.

    Pre-change literal: ``{PRE_CHANGE_B1}``."""
    sid = _generated(client)
    before = client.get(f"{API}/{sid}/world").json()
    _cold(world_service, sid)

    pause = _PauseInsideLoadBound(monkeypatch)
    reader, box = _run(lambda: client.get(f"{API}/{sid}{route}", params=params))
    assert pause.inside.wait(30), f"{route} never reached the bound document read"

    doc = _document(client, sid)
    doc["seed"] = 777
    doc["orebody"]["center"] = {"x": -60.0, "y": -70.0, "z": -50.0}
    assert client.put(f"{API}/{sid}", json=doc).status_code == 200
    assert client.post(f"{API}/{sid}/world/generate").status_code == 200
    after = client.get(f"{API}/{sid}/world").json()
    # the two documents really are distinguishable in all three numbers
    assert _world_identity(before) != _world_identity(after)
    for i in range(3):
        assert _world_identity(before)[i] != _world_identity(after)[i], i

    pause.release.set()
    reader.join(60)
    assert "error" not in box, box.get("error")
    status, code = _answer(box["value"])
    if status == 409:
        assert code == "READ_SNAPSHOT_CHANGED", (code, PRE_CHANGE_B1)
    else:  # pragma: no cover - the fix makes the 409 deterministic here
        assert status == 200, (status, code)
        assert route == "/world", route
        assert _world_identity(box["value"].json()) in (
            _world_identity(before),
            _world_identity(after),
        ), PRE_CHANGE_B1
    monkeypatch.undo()
    # the undisturbed read still answers the post-mutation truth
    assert _world_identity(client.get(f"{API}/{sid}/world").json()) == _world_identity(after)


# --------------------------------------------------------------------------- #
# Stage D S6 — the revision-bound world cache, pinned
# --------------------------------------------------------------------------- #


def test_a_warm_world_cache_is_never_served_across_a_mutation(
    client: TestClient, store: ScenarioStore, world_service: WorldService
) -> None:
    """S6. The headline mechanism of commit 3 — the world cache entry carrying
    the two revisions it was built at — was pinned by NO test: mutation M14
    (``cached.bound_to(scenario_revision, arrays_revision)`` →
    ``cached is not None``, ``world_service.py``) left 63 targeted tests and
    the whole FAST tier green, with the mutation observable measured as
    ``MIXED_OLD_WORLD_WITH_NEW_DOCUMENT`` False at HEAD and **True** under M14.

    The mutation happens through a SECOND ``WorldService`` over the SAME
    ``ScenarioStore`` — a second process, in effect — so the first service's
    cache is never invalidated in memory and can only be rejected by its
    binding."""
    sid = _generated(client)
    warm = client.get(f"{API}/{sid}/scene")
    assert warm.status_code == 200
    assert sid in world_service._cache  # warm

    other = WorldService(store)
    replacement = small_scenario(seed=777).model_dump(exclude={"id", "schema_version"})
    replacement["world"]["depth"] = 300.0
    other.replace_scenario(sid, ScenarioCreate(**replacement))
    other.generate(sid)

    # the first service still holds its entry: nothing in memory dropped it
    assert sid in world_service._cache
    stale_entry = world_service._cache[sid]
    assert stale_entry.scenario_revision != file_revision(store.scenario_path(sid))
    assert stale_entry.arrays_revision != file_revision(store.arrays_path(sid))

    served = client.get(f"{API}/{sid}/scene")
    assert served.status_code == 200, _answer(served)
    assert _identity(served.json()) == _identity(other.scene(sid))
    assert _identity(served.json()) != _identity(warm.json())
    # … and the entry it published is bound to the CURRENT revisions of both
    published = world_service._cache[sid]
    assert published.scenario_revision == file_revision(store.scenario_path(sid))
    assert published.arrays_revision == file_revision(store.arrays_path(sid))
