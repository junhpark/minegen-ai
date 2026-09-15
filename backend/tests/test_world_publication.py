"""AC-01F.2 CORRECTION — the WORLD COMMIT RECORD (report finding B1).

What was measured on PR #34 HEAD ``57c64a5`` and is closed here: publication
was atomic per FILE, but nothing on disk bound ``arrays.npz`` to the
``scenario.json`` it was generated from. A writer that died between
``ScenarioStore.replace`` and ``WorldService.invalidate`` therefore left a NEW
document beside an OLD world PERMANENTLY, and a FRESH process — with no
in-memory ``_BoundWorld`` to contradict it — bound whatever the two current
revisions were and answered **200**. The pre-change literal is asserted in
:func:`test_the_pre_change_state_is_a_mixed_generation_on_disk`: the state this
module refuses is exactly the one a 200 used to describe.

``derived/world.json`` — until the correction an unread statistics snapshot —
is now that binding, published LAST by ``WorldService._save`` so its
publication is the COMMIT POINT of a generation. The cross-process half of the
proof (real process death, spawned children, interleaved generators) is
``tests/test_world_publication_processes.py``; this module is the in-process
contract: the record's content, the five enforcement points, the guard
precedence, and that a read never repairs it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from minegen.core.models import ScenarioCreate
from minegen.core.publication import publish_bytes, publish_npz, publish_text
from minegen.core.revision import file_revision, revision_of_stat
from minegen.core.world_record import (
    WORLD_RECORD_FILE,
    build_world_record,
    record_rejection,
)
from minegen.services.artifact_errors import (
    WorldNotGeneratedError,
    WorldPublicationStaleError,
)
from minegen.services.scenario_service import ScenarioStore
from minegen.services.world_service import WorldService
from tests.conftest import small_scenario

API = "/api/v1/scenarios"

#: the state a 200 used to describe (report finding B1, PR #34 HEAD 57c64a5)
PRE_CHANGE_B1 = (
    "a NEW scenario.json beside the OLD arrays.npz, permanently, with a fresh "
    "process unable to prove the arrays were generated from that document"
)


def _create(client: TestClient) -> str:
    payload = small_scenario().model_dump(by_alias=True, exclude={"id", "schema_version"})
    return str(client.post(API, json=payload).json()["id"])


def _generated(client: TestClient) -> str:
    sid = _create(client)
    assert client.post(f"{API}/{sid}/world/generate").status_code == 200
    return sid


def _record(store: ScenarioStore, sid: str) -> dict[str, Any]:
    return dict(json.loads((store.derived_dir(sid) / WORLD_RECORD_FILE).read_text()))


def _replace_document_without_invalidating(store: ScenarioStore, sid: str) -> None:
    """The B1 kill point: ``ScenarioStore.replace`` has run, ``invalidate``
    has not. ``WorldService.replace_scenario`` is the API path and does both
    under one lock; calling the STORE directly is what a process death between
    the two leaves on disk."""
    document = store.get(sid)
    other = small_scenario(seed=document.seed + 1)
    store.replace(sid, ScenarioCreate(**other.model_dump(exclude={"id", "schema_version"})))


# --------------------------------------------------------------------------- #
# the record itself
# --------------------------------------------------------------------------- #


def test_a_publication_returns_the_identity_of_the_file_it_installed(tmp_path: Path) -> None:
    """Q1.1. The three helpers return ``file_revision`` of the bytes THEY
    published, from the temp file's own ``os.fstat`` before the rename. A
    post-hoc stat of the path names whatever file is there — across processes
    that can be another generation's, which is how a record could certify
    bytes its own generation never wrote."""
    import numpy as np

    for name, publish in (
        ("a.json", lambda p: publish_text(p, '{"x": 1}')),
        ("b.bin", lambda p: publish_bytes(p, b"bytes")),
        ("c.npz", lambda p: publish_npz(p, q=np.arange(3))),
    ):
        path = tmp_path / name
        returned = publish(path)
        assert returned == file_revision(path), name
        st = path.stat()
        assert returned == revision_of_stat(path.name, st.st_size, st.st_mtime_ns), name


def test_the_rule_60_formula_is_unchanged(tmp_path: Path) -> None:
    """``revision_of_stat`` only NAMES the existing formula (rule 60). No
    content hash is introduced anywhere by this correction."""
    path = tmp_path / "f.json"
    path.write_text("x", encoding="utf-8")
    st = path.stat()
    assert file_revision(path) == revision_of_stat(path.name, st.st_size, st.st_mtime_ns)
    assert file_revision(tmp_path / "missing.json") is None


def test_the_record_names_the_two_live_files_and_keeps_the_stats(
    client: TestClient, store: ScenarioStore
) -> None:
    stats = client.post(f"{API}/{(sid := _create(client))}/world/generate").json()
    record = _record(store, sid)
    assert record["publication"] == {
        "scenarioId": sid,
        "scenarioRevision": file_revision(store.scenario_path(sid)),
        "arraysRevision": file_revision(store.arrays_path(sid)),
    }
    # the payload the file used to be is still there, and the POST body is
    # unchanged — the response is ``stats``, never the record
    assert record["stats"] == stats


def test_record_rejection_is_a_pure_typed_comparison() -> None:
    good = build_world_record(
        scenario_id="s", scenario_revision="rev-s", arrays_revision="rev-a", stats={}
    )
    live = {"scenario_id": "s", "scenario_revision": "rev-s", "arrays_revision": "rev-a"}
    assert record_rejection(good, **live) is None
    for bad, expect in (
        (None, "missing"),
        ([], "missing"),
        ({}, "no publication record"),
        ({"publication": "x"}, "no publication record"),
        ({"publication": {}}, "was published for scenario"),
    ):
        reason = record_rejection(bad, **live)
        assert reason is not None and expect in reason, (bad, reason)
    for field, value in (
        ("scenarioId", "other"),
        ("scenarioRevision", "x"),
        ("arraysRevision", "y"),
    ):
        mutated = json.loads(json.dumps(good))
        mutated["publication"][field] = value
        assert record_rejection(mutated, **live) is not None, field


# --------------------------------------------------------------------------- #
# the B1 state
# --------------------------------------------------------------------------- #


def test_the_pre_change_state_is_a_mixed_generation_on_disk(
    client: TestClient, store: ScenarioStore
) -> None:
    """The state itself, asserted before the refusal is: the document on disk
    is the NEW one, the arrays are the OLD generation's, and the record still
    names the OLD document — which is the only evidence that says so."""
    sid = _generated(client)
    recorded = _record(store, sid)["publication"]
    arrays_before = file_revision(store.arrays_path(sid))
    _replace_document_without_invalidating(store, sid)
    assert file_revision(store.scenario_path(sid)) != recorded["scenarioRevision"], PRE_CHANGE_B1
    assert file_revision(store.arrays_path(sid)) == arrays_before == recorded["arraysRevision"]


def test_a_new_document_beside_an_old_world_is_refused_by_a_fresh_service(
    client: TestClient, store: ScenarioStore
) -> None:
    """A FRESH ``WorldService`` — no ``_BoundWorld`` entry, the situation of a
    restarted process — refuses instead of binding the two current files."""
    sid = _generated(client)
    _replace_document_without_invalidating(store, sid)
    with pytest.raises(WorldPublicationStaleError):
        WorldService(store).load(sid)


def test_a_replaced_arrays_file_is_refused_even_though_it_loads(
    client: TestClient, store: ScenarioStore
) -> None:
    """The other half: the document is untouched and ``arrays.npz`` is a
    perfectly loadable world — of another generation."""
    sid = _generated(client)
    other = _generated(client)
    store.arrays_path(sid).write_bytes(store.arrays_path(other).read_bytes())
    with pytest.raises(WorldPublicationStaleError):
        WorldService(store).load(sid)


def test_regeneration_is_the_remedy(client: TestClient, store: ScenarioStore) -> None:
    sid = _generated(client)
    _replace_document_without_invalidating(store, sid)
    assert client.get(f"{API}/{sid}/world").status_code == 409
    assert client.post(f"{API}/{sid}/world/generate").status_code == 200
    assert client.get(f"{API}/{sid}/world").status_code == 200


# --------------------------------------------------------------------------- #
# the five enforcement points and the guard order
# --------------------------------------------------------------------------- #


def test_every_enforcement_point_refuses_the_same_state(
    client: TestClient, store: ScenarioStore
) -> None:
    """ONE definition (``ArtifactReader.require_world``), five call sites. The
    last three never pass through ``_read_bound``; before the correction
    ``/design/ramp`` and ``/design/ramp-source`` answered **200** for a world
    whose generation no longer matched the document."""
    sid = _generated(client)
    assert client.post(f"{API}/{sid}/design/targets").status_code == 200
    _replace_document_without_invalidating(store, sid)
    for route in (
        f"{API}/{sid}/world",  # WorldService.load_bound
        f"{API}/{sid}/world/slice?axis=z&index=0",
        f"{API}/{sid}/scene",
        f"{API}/{sid}/design/targets",  # ArtifactReader._read_bound
        f"{API}/{sid}/design/ramp",  # DesignService._ramp_snapshot
        f"{API}/{sid}/design/ramp-source",
    ):
        response = client.get(route)
        assert response.status_code == 409, route
        assert response.json()["detail"]["code"] == "WORLD_PUBLICATION_STALE", route
    put = client.put(f"{API}/{sid}/design/ramp-source", json={"activeSource": "LEGACY"})
    assert put.status_code == 409 and put.json()["detail"]["code"] == "WORLD_PUBLICATION_STALE"
    select = client.post(f"{API}/{sid}/design/layout-v2/select", json={"candidateId": "x"})
    assert select.status_code == 409
    assert select.json()["detail"]["code"] == "WORLD_PUBLICATION_STALE"


def test_an_absent_world_keeps_its_own_code(client: TestClient, store: ScenarioStore) -> None:
    """Guard ORDER: ``WORLD_NOT_GENERATED`` (no arrays) is unchanged and still
    wins — the correction adds a rung, it does not re-label the existing one."""
    sid = _generated(client)
    store.arrays_path(sid).unlink()
    for route in (f"{API}/{sid}/world", f"{API}/{sid}/scene", f"{API}/{sid}/design/targets"):
        response = client.get(route)
        assert response.status_code == 409, route
        assert response.json()["detail"]["code"] == "WORLD_NOT_GENERATED", route
    with pytest.raises(WorldNotGeneratedError):
        WorldService(store).load(sid)


def test_a_read_never_repairs_the_record(client: TestClient, store: ScenarioStore) -> None:
    """The predicate is a PURE comparison: no repair, no re-publication, no
    read-side mutation (the directive's prohibition, and the standing
    ``test_no_read_surface_writes_anything`` contract)."""
    sid = _generated(client)
    _replace_document_without_invalidating(store, sid)
    record_path = store.derived_dir(sid) / WORLD_RECORD_FILE
    before = record_path.read_bytes(), record_path.stat().st_mtime_ns
    for _ in range(3):
        assert client.get(f"{API}/{sid}/world").status_code == 409
        assert client.get(f"{API}/{sid}/scene").status_code == 409
    assert (record_path.read_bytes(), record_path.stat().st_mtime_ns) == before


def test_a_missing_record_beside_present_arrays_is_uncommitted(
    client: TestClient, store: ScenarioStore
) -> None:
    """Q3 kill point B: ``arrays.npz`` published, the process died before its
    record. The generation is not visible until it is complete."""
    sid = _generated(client)
    (store.derived_dir(sid) / WORLD_RECORD_FILE).unlink()
    response = client.get(f"{API}/{sid}/world")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "WORLD_PUBLICATION_STALE"


def test_an_unparseable_record_is_uncommitted(client: TestClient, store: ScenarioStore) -> None:
    sid = _generated(client)
    (store.derived_dir(sid) / WORLD_RECORD_FILE).write_text("{", encoding="utf-8")
    assert client.get(f"{API}/{sid}/scene").status_code == 409


def test_the_record_check_does_not_preempt_the_incompatible_artifact_code(
    client: TestClient, store: ScenarioStore, world_service: WorldService
) -> None:
    """A1 precedence: a Phase-17 NPZ dropped beside a current document changes
    the arrays revision, so the record no longer commits it — but
    ``WORLD_ARTIFACT_INCOMPATIBLE`` is strictly more specific and still wins on
    every surface that LOADS the world. That is why ``load_bound`` validates
    the record AFTER the load."""
    import numpy as np

    sid = _generated(client)
    shape = (4, 4, 3)
    np.savez_compressed(
        store.arrays_path(sid),
        rock_type=np.ones(shape, dtype=np.uint8),
        ore_fraction=np.zeros(shape, dtype=np.float32),
        grid_origin=np.zeros(3),
        grid_spacing=np.full(3, 10.0),
        grid_shape=np.array(shape, dtype=np.float64),
        terrain_z=np.zeros((5, 5)),
        terrain_meta=np.array([0.0, 0.0, 10.0]),
    )
    world_service._cache.clear()
    for route in (f"{API}/{sid}/world", f"{API}/{sid}/scene"):
        response = client.get(route)
        assert response.status_code == 409, route
        assert response.json()["detail"]["code"] == "WORLD_ARTIFACT_INCOMPATIBLE", route


def test_a_warm_cache_is_not_a_second_authority(
    client: TestClient, store: ScenarioStore, world_service: WorldService
) -> None:
    """The CACHE-HIT rung, exercised as such (Stage D D5-4).

    The cached entry is keyed on the two live revisions, so tampering with an
    INPUT busts the binding and the refusal would come from the cold path
    instead. Here only the RECORD is rewritten: both live revisions are
    untouched, ``_BoundWorld.bound_to`` still returns True, and the 409 can
    only come from the check on the warm branch."""
    sid = _generated(client)
    assert client.get(f"{API}/{sid}/world").status_code == 200  # warm
    assert sid in world_service._cache
    scenario_revision = file_revision(store.scenario_path(sid))
    arrays_revision = file_revision(store.arrays_path(sid))
    record_path = store.derived_dir(sid) / WORLD_RECORD_FILE
    record = json.loads(record_path.read_text())
    record["publication"]["arraysRevision"] = "0" * 16  # a foreign generation
    record_path.write_text(json.dumps(record), encoding="utf-8")

    assert file_revision(store.scenario_path(sid)) == scenario_revision
    assert file_revision(store.arrays_path(sid)) == arrays_revision
    cached = world_service._cache[sid]
    assert scenario_revision is not None and arrays_revision is not None
    assert cached.bound_to(scenario_revision, arrays_revision), (
        "the cache entry must still be bound, or this test would exercise the cold path"
    )
    response = client.get(f"{API}/{sid}/world")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "WORLD_PUBLICATION_STALE"


# --------------------------------------------------------------------------- #
# Stage D — degenerate records are TYPED, never an escaping 500
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("label", "payload"),
    [
        ("empty", b""),
        ("null", b"null"),
        ("not utf-8", b"\xff\xfe\x00"),
        ("a list", b"[]"),
        ("publication is a list", b'{"publication": []}'),
        ("publication is a string", b'{"publication": "x"}'),
        ("revisions are numbers", b'{"publication": {"scenarioId": 1, "scenarioRevision": 2}}'),
        ("deeply nested", b"[" * 200_000),
    ],
)
def test_a_degenerate_record_is_a_typed_refusal_not_a_500(
    client: TestClient, store: ScenarioStore, label: str, payload: bytes
) -> None:
    """Stage D D1-F1: ``json.loads`` raises ``RecursionError`` — a
    ``RuntimeError``, NOT a ``ValueError`` — on a deeply nested document, and
    the first draft caught ``ValueError`` only. MEASURED before the fix: a
    ``derived/world.json`` of ``b"[" * 200000`` escaped as an **unmapped 500**
    on ``/world``, ``/scene``, ``/design/targets`` AND ``/design/ramp`` — three
    of which never parsed a file under ``derived/`` before this guard existed.
    Every shape must be the typed 409 instead."""
    sid = _generated(client)
    (store.derived_dir(sid) / WORLD_RECORD_FILE).write_bytes(payload)
    for route in (f"{API}/{sid}/world", f"{API}/{sid}/scene", f"{API}/{sid}/design/ramp"):
        response = client.get(route)
        assert response.status_code == 409, (label, route, response.status_code)
        assert response.json()["detail"]["code"] == "WORLD_PUBLICATION_STALE", (label, route)


def test_an_unstattable_record_is_absent_not_an_escaping_oserror(
    client: TestClient, store: ScenarioStore
) -> None:
    """Stage D D1-F2: the record observation is the first thing that made
    ``GET …/world`` and ``GET …/world/slice`` touch ``derived/`` at all.
    MEASURED before the fix, with ``derived/`` replaced by a regular file:
    ``/world`` answered **500** where HEAD answered 200, because
    ``file_revision`` swallows ``FileNotFoundError`` only and a
    ``NotADirectoryError`` escaped. An unstattable record is an ABSENT record
    — the world is uncommitted, typed."""
    sid = _generated(client)
    derived = store.derived_dir(sid)
    for child in sorted(derived.rglob("*"), reverse=True):
        child.unlink() if child.is_file() else child.rmdir()
    derived.rmdir()
    derived.write_text("not a directory", encoding="utf-8")
    response = client.get(f"{API}/{sid}/world")
    assert response.status_code == 409, response.status_code
    assert response.json()["detail"]["code"] == "WORLD_PUBLICATION_STALE"


def test_a_present_but_unreadable_record_does_not_claim_to_be_missing(
    client: TestClient, store: ScenarioStore
) -> None:
    """Stage D D1-F3: ``_observe`` deliberately distinguishes UNREADABLE from
    ABSENT; the first draft collapsed that back into "is missing" in the
    message. The 409 was already right — the sentence was not."""
    sid = _generated(client)
    record = store.derived_dir(sid) / WORLD_RECORD_FILE
    record.unlink()
    record.mkdir()  # present, stattable, unreadable as bytes
    response = client.get(f"{API}/{sid}/world")
    assert response.status_code == 409
    message = response.json()["detail"]["message"]
    assert "present but its bytes could not be read" in message, message
    assert "is missing" not in message, message
