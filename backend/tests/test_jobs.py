"""Phase 04.5: async jobs, progress callback, WebSocket stream (rule 60)."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from minegen.design.cost_field import DesignCostEvaluator
from minegen.design.mine_designer import ChainedDeclineGenerator
from minegen.design.progress import ProgressEvent, ProgressStage
from minegen.design.targets import generate_access_targets, resolve_portal
from minegen.services.job_service import JobAlreadyRunningError, JobService
from minegen.world.synthetic_world import generate_world
from tests.conftest import small_scenario
from tests.test_world_api import _create

# -- progress callback does not change results ---------------------------------


def test_progress_events_are_ordered_and_results_unchanged() -> None:
    sc = small_scenario(with_fault=True)
    sc.design.candidate_count = 1
    sc.design.search.max_expansions_per_candidate = 20000
    w = generate_world(sc)
    ev = DesignCostEvaluator(w, sc.design)
    portal, gen = resolve_portal(sc, w)
    ts = generate_access_targets(
        w, sc.design, sc.ramp, sc.mining.sublevel_interval, ev, portal, gen
    )
    g = ChainedDeclineGenerator(ev, sc.ramp, sc.design.search)
    events: list[ProgressEvent] = []
    with_cb = g.generate(ts, max_levels=2, on_progress=events.append)
    without = g.generate(ts, max_levels=2)
    a, b = with_cb.to_dict(), without.to_dict()
    a.pop("elapsedMs"), b.pop("elapsedMs")
    for lv_a, lv_b in zip(a["levels"], b["levels"], strict=True):
        for ca, cb in zip(lv_a["candidateResults"], lv_b["candidateResults"], strict=True):
            ca["diagnostics"].pop("elapsedMs"), cb["diagnostics"].pop("elapsedMs")
    assert a == b

    stages = [e.stage for e in events]
    assert (
        stages[0] is ProgressStage.LEVEL_STARTED and stages[-1] is ProgressStage.DECLINE_COMPLETED
    )
    assert stages.count(ProgressStage.LEVEL_COMPLETED) == 2
    assert stages.count(ProgressStage.CANDIDATE_COMPLETED) == 2
    progress = [e.progress for e in events]
    assert all(0.0 <= p <= 1.0 for p in progress) and progress == sorted(progress)
    assert events[-1].progress == 1.0 and events[-1].total_levels == 2
    expanded = [e.expanded_states for e in events]
    assert expanded == sorted(expanded) and expanded[-1] > 0
    done = [e for e in events if e.stage is ProgressStage.CANDIDATE_COMPLETED]
    assert all(e.candidate_status == "SUCCESS" and e.candidate_id for e in done)
    d = events[0].to_dict()
    assert d["stage"] == "LEVEL_STARTED" and d["phase"] == "DECLINE_SEARCH"


# -- registry -----------------------------------------------------------------


def test_job_registry_lifecycle_and_duplicate_protection() -> None:
    svc = JobService(max_workers=1)
    try:

        def slow(on_progress):  # type: ignore[no-untyped-def]
            for i in range(3):
                on_progress(
                    ProgressEvent(ProgressStage.LEVEL_STARTED, "X", i + 1, 3, 0, 0, i / 3, i)
                )
                time.sleep(0.05)
            return {"ok": True}

        job = svc.submit("s1", "DECLINE", slow)
        assert job.status.value in ("QUEUED", "RUNNING")  # the pool may start it immediately
        with pytest.raises(JobAlreadyRunningError):
            svc.submit("s1", "DECLINE", slow)
        assert svc.submit("s2", "DECLINE", lambda _: {"ok": 2}).scenario_id == "s2"
        done = svc.wait(job.id, timeout=5)
        assert done.status.value == "SUCCEEDED" and done.result == {"ok": True}
        assert done.progress["progress"] == 1.0 and done.finished_at is not None
        # after completion a new job for the same scenario is allowed
        again = svc.submit("s1", "DECLINE", lambda _: {"ok": 3})
        assert svc.wait(again.id, timeout=5).result == {"ok": 3}

        failing = svc.submit("s3", "DECLINE", lambda _: (_ for _ in ()).throw(ValueError("boom")))
        f = svc.wait(failing.id, timeout=5)
        assert f.status.value == "FAILED" and f.error is not None
        assert "ValueError: boom" in f.error["message"]
        assert [j["jobId"] for j in svc.list("s1")] == [again.id, job.id]
    finally:
        svc.shutdown()


# -- API + WebSocket ---------------------------------------------------------------


def _prepare(client: TestClient) -> str:
    sid = _create(client)
    doc = client.get(f"/api/v1/scenarios/{sid}").json()
    doc.pop("id"), doc.pop("schemaVersion")
    doc["design"]["candidateCount"] = 1
    doc["design"]["search"]["maxExpansionsPerCandidate"] = 20000
    client.put(f"/api/v1/scenarios/{sid}", json=doc)
    client.post(f"/api/v1/scenarios/{sid}/world/generate")
    client.post(f"/api/v1/scenarios/{sid}/design/targets")
    return sid


def test_decline_async_job_flow(client: TestClient) -> None:
    sid = _prepare(client)
    r = client.post(f"/api/v1/scenarios/{sid}/design/decline", params={"maxLevels": 2})
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["status"] == "QUEUED" and job["kind"] == "DECLINE"  # snapshot at submission
    jid = job["jobId"]

    # a second submission while running is refused
    r2 = client.post(f"/api/v1/scenarios/{sid}/design/decline", params={"maxLevels": 2})
    assert r2.status_code in (409, 202)
    if r2.status_code == 409:
        assert r2.json()["detail"]["code"] == "JOB_ALREADY_RUNNING"
        assert r2.json()["detail"]["jobId"] == jid

    deadline = time.time() + 60
    snap = None
    while time.time() < deadline:
        snap = client.get(f"/api/v1/jobs/{jid}").json()
        if snap["status"] in ("SUCCEEDED", "FAILED"):
            break
        time.sleep(0.1)
    assert snap is not None and snap["status"] == "SUCCEEDED", snap
    assert snap["result"]["status"] == "SUCCESS" and snap["result"]["completedLevels"] == 2
    assert snap["progress"]["progress"] == 1.0
    # persisted and served like the sync path
    assert client.get(f"/api/v1/scenarios/{sid}/design/decline").json() == snap["result"]
    assert (
        "result" not in client.get(f"/api/v1/jobs/{jid}", params={"includeResult": "false"}).json()
    )
    assert client.get("/api/v1/jobs", params={"scenario_id": sid}).json()[0]["jobId"] == jid
    assert client.get("/api/v1/jobs/nope").status_code == 404


def test_decline_job_preconditions(client: TestClient) -> None:
    sid = _create(client)
    r = client.post(f"/api/v1/scenarios/{sid}/design/decline")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "WORLD_NOT_GENERATED"
    assert client.get("/api/v1/jobs").json() == []


def test_job_websocket_streams_until_done(client: TestClient) -> None:
    sid = _prepare(client)
    jid = client.post(f"/api/v1/scenarios/{sid}/design/decline", params={"maxLevels": 1}).json()[
        "jobId"
    ]
    messages = []
    with client.websocket_connect(f"/ws/jobs/{jid}") as ws:
        while True:
            msg = ws.receive_json()
            messages.append(msg)
            if msg["type"] == "done":
                break
    assert messages[-1]["status"] == "SUCCEEDED"
    progress = [m for m in messages if m["type"] == "progress"]
    assert progress and progress[-1]["status"] == "SUCCEEDED"
    versions = [m["version"] for m in progress]
    assert versions == sorted(versions) and len(set(versions)) == len(versions)
    assert any(m["progress"].get("stage") == "CANDIDATE_STARTED" for m in progress)
    with client.websocket_connect("/ws/jobs/missing") as ws:
        assert ws.receive_json()["code"] == "JOB_NOT_FOUND"
