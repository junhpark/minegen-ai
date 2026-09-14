"""AC-01F T6 — the scene is ONE snapshot (F06-A, derived half).

Stage A §6 measured what ``GET /scene`` used to be: up to 18 unsynchronised
reads with no linearization point, so a single response could mix observations
from two sides of a locked write. Probe 4 reproduced three of them —

    R1  an OLD ``levels`` beside downstream artifacts its own regeneration
        had already deleted                                (measured: MIXED)
    R2  ``decline`` at revision R1 beside ``decline_smoothed`` at R2
                                               (measured: OLD_A_PLUS_NEW_B)
    R4  the active ramp read twice per response, the two reads disagreeing

— and a **45 s** writer/reader loop measured **218 failed artifact reads and
16 failed scene reads** on HEAD (Stage A §7.2, ``p4_f06b_e2e_race.py``:
``{'writes': 266, 'reads': 31968, 'read_err': 218, 'scene': 1681,
'scene_err': 16}``; earlier copies of this header said 20 s, which was never
the measured duration). Those four numbers are the pre-change literals this
module asserts the AFTER of; the hooks below change TIMING only. This module's
own ``duration = 10.0`` is deliberately shorter — the AFTER is 0, and 0 does
not need the same wall time to be visible.

Marked ``slow``/``e2e`` centrally in ``tests/conftest.py``.
"""

from __future__ import annotations

import threading
import time
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from minegen.core.artifacts import LEVELS_ARTIFACT, TARGETS_ARTIFACT
from minegen.services.artifact_reader import READ_SPECS
from tests.test_artifact_read_api import API, Stack, _build, _make_stack, derived_restored

#: probe 4, measured on HEAD 12d7725 over a **45 s** loop (Stage A §7.2,
#: ``p4_f06b_e2e_race.py``: 266 writes, 31,968 reads, 1,681 scene reads)
PRE_CHANGE_READ_ERRORS = 218
PRE_CHANGE_SCENE_ERRORS = 16

#: the slots a levels regeneration deletes (rules 74/79/86/92/98/184): the
#: null-set that separates an all-OLD scene from an all-NEW one
LEVELS_CASCADE_SLOTS = ("network", "shafts", "stopes", "timeline", "communication", "sensors")


@pytest.fixture(scope="module")
def legacy(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Stack]:
    stack, context = _build(tmp_path_factory.mktemp("snapshot"), "LEGACY")
    yield stack
    context.__exit__(None, None, None)
    stack.jobs.shutdown()


@pytest.fixture
def world_only(tmp_path: Path) -> Iterator[Stack]:
    """A world plus ONE derived artifact — the cheapest stack that still has
    something for a snapshot to observe. Function-scoped on purpose: the
    scenario/world half of T6 mutates the SCENARIO, which no module-scoped
    fixture could survive."""
    stack, context = _make_stack(tmp_path / "world_only")
    assert stack.post("/world/generate") == (200, None)
    assert stack.post("/design/targets") == (200, None)
    yield stack
    context.__exit__(None, None, None)
    stack.jobs.shutdown()


class _PauseInsideSnapshot:
    """Pause the FIRST snapshot that reads ``trigger`` — i.e. inside the lock
    the reader holds — and let the test decide when it continues."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, trigger: str) -> None:
        self.inside = threading.Event()
        self.release = threading.Event()
        self._armed = True
        original = Path.read_bytes
        trigger_name = trigger

        def patched(path: Path) -> bytes:
            if self._armed and path.name == trigger_name:
                self._armed = False
                self.inside.set()
                assert self.release.wait(30), "the test never released the paused snapshot"
            return original(path)

        monkeypatch.setattr(Path, "read_bytes", patched)


def _run(target: Any) -> tuple[threading.Thread, dict[str, Any]]:
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


def test_a_writer_cannot_interleave_with_the_scenes_snapshot(
    legacy: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R1, impossible: the scene observes every derived file under the SAME
    lock every writer holds across its write AND its cascade, so a response
    can never carry an old ``levels`` beside the downstream artifacts that
    levels regeneration deleted."""
    with derived_restored(legacy):
        before = legacy.scene().json()
        assert all(before[slot] is not None for slot in LEVELS_CASCADE_SLOTS)

        pause = _PauseInsideSnapshot(monkeypatch, LEVELS_ARTIFACT)
        reader, read_box = _run(lambda: legacy.worlds.scene(legacy.sid))
        assert pause.inside.wait(30), "the scene never reached its lock-held read"

        writer, write_box = _run(lambda: legacy.post("/design/levels"))
        time.sleep(0.75)
        assert not write_box.get("done"), (
            "POST …/design/levels ran while the scene held the snapshot lock"
        )

        pause.release.set()
        reader.join(60)
        writer.join(120)
        assert "error" not in read_box, read_box.get("error")
        assert write_box.get("value") == (200, None), write_box

        scene = read_box["value"]
        # ALL-OLD: the snapshot completed before the writer's locked section
        assert all(scene[slot] is not None for slot in LEVELS_CASCADE_SLOTS), {
            slot: scene[slot] is None for slot in LEVELS_CASCADE_SLOTS
        }
        assert scene["levels"] == before["levels"]
        # and the store really did move on afterwards (ALL-NEW for a later read)
        after = legacy.scene().json()
        assert all(after[slot] is None for slot in LEVELS_CASCADE_SLOTS)


def test_a_ramp_regeneration_cannot_interleave_with_the_scenes_snapshot(
    legacy: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R2, impossible: ``decline`` and ``decline_smoothed`` are two files of
    one snapshot; a smoothing that rewrites one of them (and cascades over the
    other slots) either happens entirely before or entirely after it."""
    with derived_restored(legacy):
        before = legacy.scene().json()
        pause = _PauseInsideSnapshot(monkeypatch, LEVELS_ARTIFACT)
        reader, read_box = _run(lambda: legacy.worlds.scene(legacy.sid))
        assert pause.inside.wait(30)

        writer, write_box = _run(
            lambda: legacy.post("/design/decline/smooth", params={"sync": "true"})
        )
        time.sleep(0.75)
        assert not write_box.get("done"), (
            "POST …/design/decline/smooth ran while the scene held the snapshot lock"
        )

        pause.release.set()
        reader.join(120)
        writer.join(300)
        assert "error" not in read_box, read_box.get("error")
        assert write_box.get("value") == (200, None), write_box

        scene = read_box["value"]
        assert scene["decline"] == before["decline"]
        assert scene["smoothedDecline"] == before["smoothedDecline"]
        assert scene["tunnelMesh"] is not None  # the smoothing cascade had not run yet


def test_a_catalogue_regeneration_cannot_interleave_with_the_scenes_snapshot(
    legacy: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same boundary for the layout-v2 catalogue: the scene's ``layoutV2``
    slot is either the pre-generation ``null`` or the whole summary, never a
    catalogue caught mid-publication."""
    with derived_restored(legacy):
        assert legacy.scene().json()["layoutV2"] is None
        pause = _PauseInsideSnapshot(monkeypatch, LEVELS_ARTIFACT)
        reader, read_box = _run(lambda: legacy.worlds.scene(legacy.sid))
        assert pause.inside.wait(30)

        writer, write_box = _run(lambda: legacy.post("/design/layout-v2", params={"sync": "true"}))
        time.sleep(0.75)
        assert not write_box.get("done"), (
            "POST …/design/layout-v2 ran while the scene held the snapshot lock"
        )

        pause.release.set()
        reader.join(120)
        writer.join(600)
        assert "error" not in read_box, read_box.get("error")
        assert write_box.get("value") == (200, None), write_box
        assert read_box["value"]["layoutV2"] is None  # ALL-OLD
        assert legacy.scene().json()["layoutV2"] is not None  # ALL-NEW afterwards


def test_every_file_is_observed_exactly_once_per_scene(
    legacy: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R4, impossible: the active ramp owner used to be read TWICE per scene
    and probed a third time (``effective_ramp.py`` ``is_file``), so one
    response could carry a ramp and an availability flag that disagreed. One
    observation per file per snapshot."""
    counts: Counter[str] = Counter()
    original = Path.read_bytes

    def patched(path: Path) -> bytes:
        counts[path.name] += 1
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", patched)
    response = legacy.scene()
    assert response.status_code == 200
    for name in READ_SPECS:
        assert counts[name] <= 1, (name, counts[name])
    scene = response.json()
    # the two ramp slots are projections of the SAME observation
    assert scene["legacySmoothedDecline"]["segments"] == scene["smoothedDecline"]["segments"]
    assert scene["rampSource"]["layoutV2Selected"] is (scene["layoutV2Selected"] is not None)
    assert scene["rampSource"]["legacyAvailable"] is (scene["legacySmoothedDecline"] is not None)


def test_a_writer_loop_never_tears_a_concurrent_read(legacy: Stack) -> None:
    """The torn-read measurement, repeated: a writer looping
    ``generate_stopes`` against readers looping the artifact GET and the whole
    scene. HEAD measured 218 failed artifact reads and 16 failed scene reads
    over **45 s** (Stage A §7.2, ``p4_f06b_e2e_race.py``); a reader that holds
    the writer's own lock while it observes bytes cannot see half a document,
    so both must be 0 — which is why this repetition needs only 10 s."""
    duration = 10.0
    stop = threading.Event()
    read_err: list[str] = []
    scene_err: list[str] = []
    reads = Counter[str]()

    def write() -> None:
        while not stop.is_set():
            legacy.design.generate_stopes(legacy.sid)
            reads["writes"] += 1

    def read_artifact() -> None:
        while not stop.is_set():
            try:
                legacy.design.stopes(legacy.sid)
                reads["artifact"] += 1
            except Exception as exc:  # counted, never raised
                read_err.append(f"{type(exc).__name__}: {exc}")

    def read_scene() -> None:
        while not stop.is_set():
            try:
                legacy.worlds.scene(legacy.sid)
                reads["scene"] += 1
            except Exception as exc:  # counted, never raised
                scene_err.append(f"{type(exc).__name__}: {exc}")

    with derived_restored(legacy):
        threads = [
            threading.Thread(target=write, daemon=True),
            threading.Thread(target=read_artifact, daemon=True),
            threading.Thread(target=read_scene, daemon=True),
        ]
        for thread in threads:
            thread.start()
        time.sleep(duration)
        stop.set()
        for thread in threads:
            thread.join(120)

    assert reads["writes"] > 0 and reads["artifact"] > 0 and reads["scene"] > 0, reads
    assert read_err == [], (PRE_CHANGE_READ_ERRORS, read_err[:5])
    assert scene_err == [], (PRE_CHANGE_SCENE_ERRORS, scene_err[:5])


def test_the_scene_route_and_the_service_agree(legacy: Stack) -> None:
    """The API answer IS the assembly (no second read path)."""
    served = legacy.client.get(f"{API}/{legacy.sid}/scene")
    assert served.status_code == 200
    assert served.json() == legacy.worlds.scene(legacy.sid)


def test_a_scenario_put_waits_for_the_scenes_lock_held_snapshot(
    world_only: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T6, the scenario/world half. The derived half above proves a DERIVED
    writer cannot interleave with the snapshot; the scenario PUT is the other
    mutation that used to run straight through it — at HEAD it was two
    unlocked/locked sections (``api/scenarios.py:80-81``) and a scene in flight
    could serve a world the PUT had already deleted (Stage A R3b: **200**,
    ``terrain.zMax 120.638291``, every derived slot ``null``).

    ``WorldService.replace_scenario`` is now ONE locked section, so a PUT that
    arrives while the scene holds the snapshot lock BLOCKS until the
    observation is complete; the scene then answers the consistent OLD state
    and the mutation lands after it."""
    before = world_only.worlds.scene(world_only.sid)
    assert before["accessTargets"] is not None

    pause = _PauseInsideSnapshot(monkeypatch, TARGETS_ARTIFACT)
    reader, read_box = _run(lambda: world_only.worlds.scene(world_only.sid))
    assert pause.inside.wait(30), "the scene never reached its lock-held read"

    document = world_only.client.get(f"{API}/{world_only.sid}").json()
    document.pop("id")
    document.pop("schemaVersion")
    document["seed"] = 555
    writer, write_box = _run(
        lambda: world_only.client.put(f"{API}/{world_only.sid}", json=document).status_code
    )
    time.sleep(0.75)
    assert not write_box.get("done"), "PUT /scenarios/{id} ran while the scene held the lock"

    pause.release.set()
    reader.join(60)
    writer.join(60)
    assert "error" not in read_box, read_box.get("error")
    assert write_box.get("value") == 200, write_box

    # the scene that held the lock is the consistent OLD snapshot …
    scene = read_box["value"]
    assert scene["accessTargets"] == before["accessTargets"]
    assert scene["terrain"]["zMax"] == before["terrain"]["zMax"]
    # … and the mutation really did land afterwards
    assert not world_only.store.arrays_path(world_only.sid).exists()
    assert world_only.get("/scene") == (409, "WORLD_NOT_GENERATED")
