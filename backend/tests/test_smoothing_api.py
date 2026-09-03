"""Phase 05 API + persistence tests: smoothing job lifecycle, dependency
invalidation (rule 64) and stale-input protection (rule 60)."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from minegen.services.design_service import DesignService
from minegen.services.scenario_service import ScenarioStore
from tests.conftest import small_scenario


def _prepare(client: TestClient) -> str:
    sc = small_scenario(with_fault=True)
    payload = sc.model_dump(by_alias=True, exclude={"id", "schema_version"})
    r = client.post("/api/v1/scenarios", json=payload)
    assert r.status_code == 201, r.text
    sid = str(r.json()["id"])
    doc = client.get(f"/api/v1/scenarios/{sid}").json()
    doc.pop("id"), doc.pop("schemaVersion")
    doc["design"]["candidateCount"] = 1
    doc["design"]["search"]["maxExpansionsPerCandidate"] = 20000
    assert client.put(f"/api/v1/scenarios/{sid}", json=doc).status_code == 200
    assert client.post(f"/api/v1/scenarios/{sid}/world/generate").status_code == 200
    assert client.post(f"/api/v1/scenarios/{sid}/design/targets").status_code == 200
    return sid


def _decline(client: TestClient, sid: str, max_levels: int = 2) -> None:
    r = client.post(
        f"/api/v1/scenarios/{sid}/design/decline",
        params={"maxLevels": max_levels, "sync": "true"},
    )
    assert r.status_code == 200, r.text


def test_smooth_requires_decline(client: TestClient) -> None:
    sid = _prepare(client)
    r = client.post(f"/api/v1/scenarios/{sid}/design/decline/smooth", params={"sync": "true"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "DECLINE_NOT_GENERATED"
    r = client.get(f"/api/v1/scenarios/{sid}/design/decline/smooth")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SMOOTHED_NOT_GENERATED"


def test_smooth_sync_lifecycle_and_scene(
    client: TestClient, store: ScenarioStore, design_service: DesignService
) -> None:
    sid = _prepare(client)
    _decline(client, sid)
    r = client.post(f"/api/v1/scenarios/{sid}/design/decline/smooth", params={"sync": "true"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] in ("SUCCESS", "SUCCESS_WITH_FALLBACK")
    totals = body["totals"]
    assert totals["segments"] == len(body["segments"]) > 0
    assert totals["smoothedSegments"] + totals["fallbackSegments"] == totals["segments"]
    for seg in body["segments"]:
        assert seg["effectiveSource"] in ("SMOOTHED", "RAW_FALLBACK")
        assert seg["effectiveCenterline"]["pointCount"] >= 2
        assert seg["report"]["valid"] is True
        if seg["effectiveSource"] == "SMOOTHED":
            assert seg["smoothed"] is not None
        else:
            assert seg["smoothed"] is None and seg["report"]["fallbackReason"]
    # persisted + served + finite JSON
    assert design_service.smoothed_path(sid).is_file()
    got = client.get(f"/api/v1/scenarios/{sid}/design/decline/smooth")
    assert got.status_code == 200 and got.json() == body
    assert "NaN" not in got.text and "Infinity" not in got.text
    scene = client.get(f"/api/v1/scenarios/{sid}/scene").json()
    # Phase 20A: the scene ships the ACTIVE Effective Ramp — with LEGACY active
    # that is this artifact plus provenance fields (geometry untouched)
    assert scene["legacySmoothedDecline"] == body
    eff = scene["smoothedDecline"]
    assert eff["activeSource"] == "LEGACY" and eff["owningArtifact"] == "decline_smoothed.json"
    assert eff["sourceKind"] in ("LEGACY_SMOOTHED", "LEGACY_RAW_FALLBACK")
    assert {k: v for k, v in eff.items() if k in body} == body
    assert scene["rampSource"]["activeSource"] == "LEGACY"


def test_new_decline_invalidates_old_smoothed(
    client: TestClient, design_service: DesignService
) -> None:
    """Rule 64: persisting a new decline deletes the stale smoothed artifact."""
    sid = _prepare(client)
    _decline(client, sid)
    assert (
        client.post(
            f"/api/v1/scenarios/{sid}/design/decline/smooth", params={"sync": "true"}
        ).status_code
        == 200
    )
    assert design_service.smoothed_path(sid).is_file()
    _decline(client, sid)  # regenerate the decline
    assert not design_service.smoothed_path(sid).exists()
    r = client.get(f"/api/v1/scenarios/{sid}/design/decline/smooth")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SMOOTHED_NOT_GENERATED"
    assert client.get(f"/api/v1/scenarios/{sid}/scene").json()["smoothedDecline"] is None


def test_targets_regeneration_invalidates_decline_and_smoothed(
    client: TestClient, design_service: DesignService
) -> None:
    """Rule 64: regenerating targets deletes decline.json AND
    decline_smoothed.json."""
    sid = _prepare(client)
    _decline(client, sid)
    assert (
        client.post(
            f"/api/v1/scenarios/{sid}/design/decline/smooth", params={"sync": "true"}
        ).status_code
        == 200
    )
    assert client.post(f"/api/v1/scenarios/{sid}/design/targets").status_code == 200
    assert not design_service.decline_path(sid).exists()
    assert not design_service.smoothed_path(sid).exists()
    for endpoint, code in (
        ("decline", "DECLINE_NOT_GENERATED"),
        ("decline/smooth", "SMOOTHED_NOT_GENERATED"),
    ):
        r = client.get(f"/api/v1/scenarios/{sid}/design/{endpoint}")
        assert r.status_code == 409 and r.json()["detail"]["code"] == code


def test_world_regeneration_clears_smoothed(
    client: TestClient, design_service: DesignService
) -> None:
    sid = _prepare(client)
    _decline(client, sid)
    client.post(f"/api/v1/scenarios/{sid}/design/decline/smooth", params={"sync": "true"})
    assert design_service.smoothed_path(sid).is_file()
    doc = client.get(f"/api/v1/scenarios/{sid}").json()
    doc.pop("id"), doc.pop("schemaVersion")
    doc["seed"] = 777
    assert client.put(f"/api/v1/scenarios/{sid}", json=doc).status_code == 200
    assert not design_service.smoothed_path(sid).exists()


def test_smooth_async_job_flow(client: TestClient) -> None:
    sid = _prepare(client)
    _decline(client, sid)
    r = client.post(f"/api/v1/scenarios/{sid}/design/decline/smooth")
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["kind"] == "SMOOTH" and job["status"] == "QUEUED"
    jid = job["jobId"]
    deadline = time.time() + 120
    snap = None
    while time.time() < deadline:
        snap = client.get(f"/api/v1/jobs/{jid}").json()
        if snap["status"] in ("SUCCEEDED", "FAILED"):
            break
        time.sleep(0.05)
    assert snap is not None and snap["status"] == "SUCCEEDED", snap
    assert snap["result"]["status"] in ("SUCCESS", "SUCCESS_WITH_FALLBACK")
    assert snap["progress"]["stage"] == "SMOOTHING_COMPLETED"
    assert snap["progress"]["progress"] == 1.0
    assert snap["result"] == client.get(f"/api/v1/scenarios/{sid}/design/decline/smooth").json()


def test_stale_smoothing_job_never_persists(
    client: TestClient, design_service: DesignService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rule 60 applied to SMOOTH jobs: inputs (incl. decline.json) mutate while
    the job runs → JOB_INPUTS_CHANGED, nothing persisted."""
    import threading

    from minegen.design.smoothing import DeclineSmoother

    started, proceed = threading.Event(), threading.Event()
    original = DeclineSmoother.smooth

    def slow_smooth(self, payload, on_progress=None):  # type: ignore[no-untyped-def]
        started.set()
        assert proceed.wait(timeout=30), "test did not release the paused job"
        return original(self, payload, on_progress)

    monkeypatch.setattr(DeclineSmoother, "smooth", slow_smooth)

    sid = _prepare(client)
    _decline(client, sid, max_levels=1)
    jid = client.post(f"/api/v1/scenarios/{sid}/design/decline/smooth").json()["jobId"]
    assert started.wait(timeout=30)

    # regenerate targets while the smoothing job is paused: decline.json is
    # deleted, so the smoothing fingerprint changes
    assert client.post(f"/api/v1/scenarios/{sid}/design/targets").status_code == 200

    proceed.set()
    deadline = time.time() + 60
    snap = None
    while time.time() < deadline:
        snap = client.get(f"/api/v1/jobs/{jid}").json()
        if snap["status"] in ("SUCCEEDED", "FAILED"):
            break
        time.sleep(0.05)
    assert snap is not None and snap["status"] == "FAILED", snap
    assert snap["error"]["code"] == "JOB_INPUTS_CHANGED"
    assert not design_service.smoothed_path(sid).exists()
    r = client.get(f"/api/v1/scenarios/{sid}/design/decline/smooth")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SMOOTHED_NOT_GENERATED"
