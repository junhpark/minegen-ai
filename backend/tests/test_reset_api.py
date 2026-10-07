"""Hardening H1 §4.4 — ``GET …/design/reset-plan`` and
``DELETE …/design/stages/{stage}`` through the API.

The reset never reads the documents it removes, so the closure contract is
pinned with fabricated derived files (a STALE / MALFORMED artifact is a
legitimate reset target — recovery), and the real-artifact path is pinned
on the cheapest real chain (world + access targets).
"""

from __future__ import annotations

import json
import threading
from typing import Any

from fastapi.testclient import TestClient

from minegen.core.artifacts import (
    CAPABILITY_GRAPH_ARTIFACT,
    DEVELOPMENT_MESH_ARTIFACT,
    DEVELOPMENT_MESH_GLB,
    LAYOUT_V2_ARTIFACT,
    LAYOUT_V2_SELECTED_ARTIFACT,
    LEGACY_RAMP_ARTIFACT,
    LEVEL_ACCESSES_ARTIFACT,
    LEVELS_ARTIFACT,
    NETWORK_ARTIFACT,
    RAMP_SOURCE_FILE,
    SENSORS_ARTIFACT,
    STOPES_ARTIFACT,
    TARGETS_ARTIFACT,
    TIMELINE_ARTIFACT,
    TUNNEL_MESH_ARTIFACT,
    TUNNEL_MESH_GLB,
)
from minegen.services.job_service import JobService
from minegen.services.scenario_service import ScenarioStore
from tests.test_world_api import _create


def _fabricate(store: ScenarioStore, sid: str, *names: str) -> None:
    derived = store.derived_dir(sid)
    derived.mkdir(parents=True, exist_ok=True)
    for name in names:
        (derived / name).write_bytes(b"{" if name.endswith(".json") else b"glTF")


def _files(store: ScenarioStore, sid: str) -> set[str]:
    return {p.name for p in store.derived_dir(sid).iterdir() if p.is_file()}


def test_reset_plan_and_delete_are_the_same_closure(
    client: TestClient, store: ScenarioStore
) -> None:
    sid = _create(client)
    client.post(f"/api/v1/scenarios/{sid}/world/generate")
    base = f"/api/v1/scenarios/{sid}/design"
    # a LAYOUT_V2 mine with every level-chain artifact present, all MALFORMED
    (store.derived_dir(sid) / RAMP_SOURCE_FILE).write_text(
        json.dumps({"activeSource": "LAYOUT_V2"})
    )
    _fabricate(
        store,
        sid,
        LAYOUT_V2_ARTIFACT,
        LAYOUT_V2_SELECTED_ARTIFACT,
        LEVEL_ACCESSES_ARTIFACT,
        TUNNEL_MESH_ARTIFACT,
        TUNNEL_MESH_GLB,
        LEVELS_ARTIFACT,
        DEVELOPMENT_MESH_ARTIFACT,
        DEVELOPMENT_MESH_GLB,
        NETWORK_ARTIFACT,
        CAPABILITY_GRAPH_ARTIFACT,
        STOPES_ARTIFACT,
        TIMELINE_ARTIFACT,
        SENSORS_ARTIFACT,
    )
    before = _files(store, sid)

    r = client.get(f"{base}/reset-plan", params={"from": "LEVELS"})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["from"] == "LEVELS" and plan["activeSource"] == "LAYOUT_V2"
    assert plan["stageArtifacts"] == [LEVELS_ARTIFACT] and plan["present"] is True
    expected = [
        LEVELS_ARTIFACT,
        DEVELOPMENT_MESH_ARTIFACT,
        DEVELOPMENT_MESH_GLB,
        STOPES_ARTIFACT,
        TIMELINE_ARTIFACT,
        SENSORS_ARTIFACT,
        NETWORK_ARTIFACT,
        CAPABILITY_GRAPH_ARTIFACT,
    ]
    assert plan["willDelete"] == expected
    # the preview wrote nothing
    assert _files(store, sid) == before

    r = client.delete(f"{base}/stages/LEVELS")
    assert r.status_code == 200, r.text
    assert r.json() == {"from": "LEVELS", "activeSource": "LAYOUT_V2", "deleted": expected}
    # exactly the plan is gone; the tunnel (rule 74), the catalogue, the
    # selection pair and the ramp-source root survive
    assert _files(store, sid) == before - set(expected)
    for kept in (
        TUNNEL_MESH_ARTIFACT,
        TUNNEL_MESH_GLB,
        LAYOUT_V2_ARTIFACT,
        LAYOUT_V2_SELECTED_ARTIFACT,
        LEVEL_ACCESSES_ARTIFACT,
        RAMP_SOURCE_FILE,
    ):
        assert kept in _files(store, sid), kept
    # the scene no longer carries the deleted artifacts
    assert client.get(f"{base}/levels").status_code == 409

    # a second reset from the same stage has nothing of its own → typed 404
    r = client.delete(f"{base}/stages/LEVELS")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "RESET_TARGET_NOT_GENERATED"
    assert "levels.json" in r.json()["detail"]["message"]
    # the preview still answers (nothing present, nothing to delete)
    r = client.get(f"{base}/reset-plan", params={"from": "LEVELS"})
    assert r.status_code == 200 and r.json()["present"] is False and r.json()["willDelete"] == []


def test_source_gate_world_root_and_unknown_stage(client: TestClient, store: ScenarioStore) -> None:
    sid = _create(client)
    client.post(f"/api/v1/scenarios/{sid}/world/generate")
    base = f"/api/v1/scenarios/{sid}/design"
    _fabricate(store, sid, LEGACY_RAMP_ARTIFACT, TUNNEL_MESH_ARTIFACT, LEVELS_ARTIFACT)
    # LEGACY is the absence of the switch file: the legacy chain is live
    r = client.get(f"{base}/reset-plan", params={"from": "SMOOTH"})
    assert r.json()["activeSource"] == "LEGACY"
    assert r.json()["willDelete"] == [LEGACY_RAMP_ARTIFACT, TUNNEL_MESH_ARTIFACT, LEVELS_ARTIFACT]
    # under LAYOUT_V2 the legacy ramp's edges are dead (rule 151): itself only
    (store.derived_dir(sid) / RAMP_SOURCE_FILE).write_text(
        json.dumps({"activeSource": "LAYOUT_V2"})
    )
    r = client.get(f"{base}/reset-plan", params={"from": "SMOOTH"})
    assert r.json()["activeSource"] == "LAYOUT_V2"
    assert r.json()["willDelete"] == [LEGACY_RAMP_ARTIFACT]
    r = client.delete(f"{base}/stages/SMOOTH")
    assert r.status_code == 200 and r.json()["deleted"] == [LEGACY_RAMP_ARTIFACT]
    assert {TUNNEL_MESH_ARTIFACT, LEVELS_ARTIFACT, RAMP_SOURCE_FILE} <= _files(store, sid)

    # WORLD: preview lists every present derived artifact; delete is refused
    r = client.get(f"{base}/reset-plan", params={"from": "WORLD"})
    assert r.status_code == 200
    assert set(r.json()["willDelete"]) == {TUNNEL_MESH_ARTIFACT, LEVELS_ARTIFACT, RAMP_SOURCE_FILE}
    r = client.delete(f"{base}/stages/WORLD")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "RESET_STAGE_NOT_DELETABLE"
    assert {TUNNEL_MESH_ARTIFACT, LEVELS_ARTIFACT, RAMP_SOURCE_FILE} <= _files(store, sid)

    # unknown stage / artifact name: schema validation, never a guess
    assert client.get(f"{base}/reset-plan", params={"from": "levels.json"}).status_code == 422
    assert client.delete(f"{base}/stages/STOPES").status_code == 422
    assert client.get(f"{base}/reset-plan").status_code == 422
    # unknown scenario
    assert client.get("/api/v1/scenarios/nope/design/reset-plan?from=LEVELS").status_code == 404
    assert client.delete("/api/v1/scenarios/nope/design/stages/LEVELS").status_code == 404


def test_an_unusable_ramp_source_plans_the_union_of_both_chains(
    client: TestClient, store: ScenarioStore
) -> None:
    sid = _create(client)
    client.post(f"/api/v1/scenarios/{sid}/world/generate")
    base = f"/api/v1/scenarios/{sid}/design"
    _fabricate(store, sid, LEGACY_RAMP_ARTIFACT, LAYOUT_V2_SELECTED_ARTIFACT, LEVELS_ARTIFACT)
    (store.derived_dir(sid) / RAMP_SOURCE_FILE).write_text("{")
    r = client.get(f"{base}/reset-plan", params={"from": "SMOOTH"})
    assert r.status_code == 200
    # strictly more, never a guessed LEGACY: the legacy ramp AND the level chain
    assert r.json()["willDelete"] == [LEGACY_RAMP_ARTIFACT, LEVELS_ARTIFACT]
    r = client.delete(f"{base}/stages/SMOOTH")
    assert r.status_code == 200 and r.json()["deleted"] == [LEGACY_RAMP_ARTIFACT, LEVELS_ARTIFACT]
    # the switch file itself is never touched by a stage reset
    assert RAMP_SOURCE_FILE in _files(store, sid)


def test_reset_from_targets_on_a_real_artifact(client: TestClient) -> None:
    sid = _create(client)
    client.post(f"/api/v1/scenarios/{sid}/world/generate")
    base = f"/api/v1/scenarios/{sid}/design"
    # nothing generated yet: the plan is empty and the delete is a typed 404
    r = client.get(f"{base}/reset-plan", params={"from": "TARGETS"})
    assert r.status_code == 200 and r.json()["present"] is False
    assert client.delete(f"{base}/stages/TARGETS").status_code == 404
    assert client.post(f"{base}/targets").status_code == 200
    r = client.get(f"{base}/reset-plan", params={"from": "TARGETS"})
    assert r.json()["present"] is True and r.json()["willDelete"] == [TARGETS_ARTIFACT]
    r = client.delete(f"{base}/stages/TARGETS")
    assert r.status_code == 200 and r.json()["deleted"] == [TARGETS_ARTIFACT]
    r = client.get(f"{base}/targets")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "TARGETS_NOT_GENERATED"
    assert client.get(f"/api/v1/scenarios/{sid}/scene").json()["accessTargets"] is None
    # regenerating after the reset works from scratch (the targets cache was dropped)
    assert client.post(f"{base}/targets").status_code == 200


# -- PR #53 review B2: a reset never races a running job / a stale preview ---- #


def test_a_running_job_refuses_the_preview_and_the_delete_until_it_finishes(
    client: TestClient, store: ScenarioStore, job_service: JobService
) -> None:
    """A job's stale-input guard watches its UPSTREAM inputs only (rule 60);
    a reset that deleted the artifact a running job is about to publish
    would be undone by the publication. Both the preview and the delete are
    typed 409 RESET_JOB_RUNNING (naming the job) while the scenario has a
    non-terminal job, nothing is deleted, and both answer again once the job
    is terminal — whatever its outcome."""
    sid = _create(client)
    client.post(f"/api/v1/scenarios/{sid}/world/generate")
    base = f"/api/v1/scenarios/{sid}/design"
    _fabricate(store, sid, LEVELS_ARTIFACT, NETWORK_ARTIFACT)
    (store.derived_dir(sid) / RAMP_SOURCE_FILE).write_text(
        json.dumps({"activeSource": "LAYOUT_V2"})
    )
    release = threading.Event()
    started = threading.Event()

    def work(_on_progress: Any) -> dict[str, Any]:
        started.set()
        release.wait(30.0)
        return {}

    job = job_service.submit(sid, "test", work)
    assert started.wait(10.0)
    try:
        for attempt in (
            lambda: client.get(f"{base}/reset-plan", params={"from": "LEVELS"}),
            lambda: client.delete(f"{base}/stages/LEVELS"),
            lambda: client.request(
                "DELETE",
                f"{base}/stages/LEVELS",
                json={"expectedWillDelete": [LEVELS_ARTIFACT, NETWORK_ARTIFACT]},
            ),
        ):
            r = attempt()
            assert r.status_code == 409, r.text
            detail = r.json()["detail"]
            assert detail["code"] == "RESET_JOB_RUNNING" and detail["jobId"] == job.id
            assert "nothing was deleted" in detail["message"]
        # another scenario's job never gates this scenario
        other = _create(client)
        client.post(f"/api/v1/scenarios/{other}/world/generate")
        _fabricate(store, other, LEVELS_ARTIFACT)
        other_plan = client.get(f"/api/v1/scenarios/{other}/design/reset-plan?from=LEVELS")
        assert other_plan.status_code == 200
        assert {LEVELS_ARTIFACT, NETWORK_ARTIFACT} <= _files(store, sid)
    finally:
        release.set()
    job_service.wait(job.id, timeout=30.0)
    # terminal → the preview and the delete answer again
    r = client.get(f"{base}/reset-plan", params={"from": "LEVELS"})
    assert r.status_code == 200 and r.json()["willDelete"] == [LEVELS_ARTIFACT, NETWORK_ARTIFACT]
    r = client.delete(f"{base}/stages/LEVELS")
    assert r.status_code == 200 and r.json()["deleted"] == [LEVELS_ARTIFACT, NETWORK_ARTIFACT]


def test_a_delete_against_a_stale_preview_is_refused_with_the_fresh_plan(
    client: TestClient, store: ScenarioStore
) -> None:
    """The optional DELETE body carries the ``willDelete`` the user confirmed;
    the plan recomputed under the lock must list exactly it (same files,
    same order). A mine that changed in between is 409 RESET_PLAN_CHANGED
    with the fresh plan in the refusal and NOTHING deleted; a matching body
    (or none) deletes."""
    sid = _create(client)
    client.post(f"/api/v1/scenarios/{sid}/world/generate")
    base = f"/api/v1/scenarios/{sid}/design"
    (store.derived_dir(sid) / RAMP_SOURCE_FILE).write_text(
        json.dumps({"activeSource": "LAYOUT_V2"})
    )
    _fabricate(store, sid, LEVELS_ARTIFACT)
    previewed = client.get(f"{base}/reset-plan", params={"from": "LEVELS"}).json()["willDelete"]
    assert previewed == [LEVELS_ARTIFACT]
    # …the mine grows a network after the preview was read
    _fabricate(store, sid, NETWORK_ARTIFACT)
    r = client.request("DELETE", f"{base}/stages/LEVELS", json={"expectedWillDelete": previewed})
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "RESET_PLAN_CHANGED"
    assert detail["plan"]["from"] == "LEVELS"
    assert detail["plan"]["willDelete"] == [LEVELS_ARTIFACT, NETWORK_ARTIFACT]
    assert "nothing was deleted" in detail["message"]
    assert {LEVELS_ARTIFACT, NETWORK_ARTIFACT} <= _files(store, sid)
    # order matters: the same files in another order are not the confirmed plan
    r = client.request(
        "DELETE",
        f"{base}/stages/LEVELS",
        json={"expectedWillDelete": [NETWORK_ARTIFACT, LEVELS_ARTIFACT]},
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "RESET_PLAN_CHANGED"
    assert {LEVELS_ARTIFACT, NETWORK_ARTIFACT} <= _files(store, sid)
    # the fresh plan, confirmed, deletes exactly it
    r = client.request(
        "DELETE", f"{base}/stages/LEVELS", json={"expectedWillDelete": detail["plan"]["willDelete"]}
    )
    assert r.status_code == 200 and r.json()["deleted"] == [LEVELS_ARTIFACT, NETWORK_ARTIFACT]
    assert not ({LEVELS_ARTIFACT, NETWORK_ARTIFACT} & _files(store, sid))
    # a body with no expectation and an explicit null stay the unguarded delete
    _fabricate(store, sid, LEVELS_ARTIFACT)
    r = client.request("DELETE", f"{base}/stages/LEVELS", json={"expectedWillDelete": None})
    assert r.status_code == 200 and r.json()["deleted"] == [LEVELS_ARTIFACT]
    _fabricate(store, sid, LEVELS_ARTIFACT)
    r = client.request("DELETE", f"{base}/stages/LEVELS", json={})
    assert r.status_code == 200 and r.json()["deleted"] == [LEVELS_ARTIFACT]
    # malformed expectation → 422, never a delete
    _fabricate(store, sid, LEVELS_ARTIFACT)
    malformed = {"expectedWillDelete": "levels.json"}
    r = client.request("DELETE", f"{base}/stages/LEVELS", json=malformed)
    assert r.status_code == 422 and LEVELS_ARTIFACT in _files(store, sid)
