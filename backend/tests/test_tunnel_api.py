"""Phase 06 API + persistence tests: tunnel-mesh job lifecycle, artifact
contract (rule 67), dependency invalidation and stale-input protection
(rule 60)."""

from __future__ import annotations

import hashlib
import json
import math
import time

import pytest
from fastapi.testclient import TestClient

from minegen.design.glb_writer import read_glb
from minegen.services.design_service import DesignService
from minegen.services.scenario_service import ScenarioStore
from tests.test_smoothing_api import _decline, _prepare


def _smooth(client: TestClient, sid: str) -> None:
    r = client.post(f"/api/v1/scenarios/{sid}/design/decline/smooth", params={"sync": "true"})
    assert r.status_code == 200, r.text


def _tunnel(client: TestClient, sid: str) -> dict:  # type: ignore[type-arg]
    r = client.post(f"/api/v1/scenarios/{sid}/design/tunnel", params={"sync": "true"})
    assert r.status_code == 200, r.text
    body: dict = r.json()  # type: ignore[type-arg]
    return body


def test_tunnel_requires_smoothed(client: TestClient) -> None:
    sid = _prepare(client)
    _decline(client, sid)
    r = client.post(f"/api/v1/scenarios/{sid}/design/tunnel", params={"sync": "true"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SMOOTHED_NOT_GENERATED"
    r = client.get(f"/api/v1/scenarios/{sid}/design/tunnel")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "TUNNEL_NOT_GENERATED"
    r = client.get(f"/api/v1/scenarios/{sid}/design/tunnel/mesh.glb")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "TUNNEL_NOT_GENERATED"


def test_tunnel_sync_lifecycle_scene_and_glb(
    client: TestClient, store: ScenarioStore, design_service: DesignService
) -> None:
    sid = _prepare(client)
    _decline(client, sid)
    _smooth(client, sid)
    body = _tunnel(client, sid)
    assert body["status"] == "SUCCESS", body.get("failureReason")
    # engineering quantities are backend-computed and finite (rules 17/67)
    for key in (
        "length3d",
        "analyticProfileArea",
        "meshProfileArea",
        "tessellationBiasPct",
        "crownRadius",
        "nominalExcavationVolume",
        "meshEnclosedVolume",
        "volumeDifferencePct",
        "excavationSurfaceArea",
        "closedMeshSurfaceArea",
        "junctionGapMax",
        "maxLocalTurnDeg",
    ):
        assert math.isfinite(float(body[key])), key
    assert body["volumeDifferencePct"] <= 1.0
    assert body["watertight"] and body["manifold"] and body["geometricallyClosed"]
    assert body["degenerateTriangles"] == 0 and body["outwardOrientation"]
    assert body["envelopeViolations"] == 0
    assert body["maxLocalTurnDeg"] <= 7.0
    assert body["selfIntersectionCheck"] == "NOT_IMPLEMENTED"
    assert body["renderVertexCount"] >= body["logicalVertexCount"]
    # persisted report == GET report
    assert design_service.tunnel_report_path(sid).is_file()
    got = client.get(f"/api/v1/scenarios/{sid}/design/tunnel")
    assert got.status_code == 200 and got.json() == body
    # scene inclusion
    scene = client.get(f"/api/v1/scenarios/{sid}/scene").json()
    assert scene["tunnelMesh"]["artifactRevision"] == body["artifactRevision"]
    # GLB endpoint: content type, cache-busted URL, revision == sha256(GLB)
    assert body["meshUrl"].endswith(f"?v={body['artifactRevision'][:16]}")
    r = client.get(f"/api/v1/scenarios/{sid}/design/tunnel/mesh.glb")
    assert r.status_code == 200
    assert r.headers["content-type"] == "model/gltf-binary"
    assert "immutable" in r.headers["cache-control"]
    glb = r.content
    assert hashlib.sha256(glb).hexdigest() == body["artifactRevision"]
    doc, binary = read_glb(glb)
    prims = doc["meshes"][0]["primitives"]  # type: ignore[index]
    roles = [p["extras"].get("role") for p in prims]
    assert roles.count("SEGMENT") == len(body["segments"])
    assert "PORTAL_CAP" in roles and "TERMINAL_CAP" in roles
    assert doc["buffers"][0]["byteLength"] == len(binary)  # type: ignore[index]


def test_tunnel_async_job_kind_mesh(client: TestClient) -> None:
    sid = _prepare(client)
    _decline(client, sid)
    _smooth(client, sid)
    r = client.post(f"/api/v1/scenarios/{sid}/design/tunnel")
    assert r.status_code == 202
    sub = r.json()
    assert sub["kind"] == "MESH" and sub["status"] == "QUEUED"
    job_id = sub["jobId"]
    deadline = time.time() + 60.0
    snap = {}
    while time.time() < deadline:
        snap = client.get(f"/api/v1/jobs/{job_id}").json()
        if snap["status"] in ("SUCCEEDED", "FAILED"):
            break
        time.sleep(0.05)
    assert snap["status"] == "SUCCEEDED", snap
    assert snap["result"]["status"] == "SUCCESS"
    assert snap["progress"]["stage"] == "MESH_COMPLETED"
    assert snap["progress"]["phase"] == "TUNNEL_MESH"


def test_invalidation_chain_smoothed_decline_targets(
    client: TestClient, design_service: DesignService
) -> None:
    """Rule 67 chain: any upstream regeneration deletes the tunnel artifacts."""
    sid = _prepare(client)
    _decline(client, sid)
    _smooth(client, sid)
    _tunnel(client, sid)
    report = design_service.tunnel_report_path(sid)
    glb = design_service.tunnel_glb_path(sid)
    assert report.is_file() and glb.is_file()
    # smoothed regeneration → tunnel gone
    _smooth(client, sid)
    assert not report.exists() and not glb.exists()
    assert client.get(f"/api/v1/scenarios/{sid}/design/tunnel").status_code == 409
    # rebuild, then decline regeneration → smoothed + tunnel gone
    _tunnel(client, sid)
    _decline(client, sid)
    assert not report.exists() and not glb.exists()
    assert client.get(f"/api/v1/scenarios/{sid}/design/decline/smooth").status_code == 409
    # rebuild the whole chain, then targets regeneration → everything gone
    _smooth(client, sid)
    _tunnel(client, sid)
    assert client.post(f"/api/v1/scenarios/{sid}/design/targets").status_code == 200
    assert not report.exists() and not glb.exists()
    assert client.get(f"/api/v1/scenarios/{sid}/design/decline").status_code == 409


def test_stale_mesh_job_never_persists(
    client: TestClient, design_service: DesignService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rule 60 for Phase 06: the smoothed artifact is replaced while the MESH
    job runs → JOB_INPUTS_CHANGED, nothing persisted."""
    import threading

    from minegen.design.tunnel_mesh import TunnelMeshBuilder

    sid = _prepare(client)
    _decline(client, sid)
    _smooth(client, sid)
    started, proceed = threading.Event(), threading.Event()
    real_build = TunnelMeshBuilder.build

    def slow_build(self, payload, on_progress=None):  # type: ignore[no-untyped-def]
        started.set()
        assert proceed.wait(timeout=30), "test did not release the paused job"
        return real_build(self, payload, on_progress=on_progress)

    monkeypatch.setattr(TunnelMeshBuilder, "build", slow_build)
    r = client.post(f"/api/v1/scenarios/{sid}/design/tunnel")
    assert r.status_code == 202
    job_id = r.json()["jobId"]
    assert started.wait(timeout=30)
    _smooth(client, sid)  # rewrites decline_smoothed.json while the job is paused
    proceed.set()
    deadline = time.time() + 60.0
    snap = {}
    while time.time() < deadline:
        snap = client.get(f"/api/v1/jobs/{job_id}").json()
        if snap["status"] in ("SUCCEEDED", "FAILED"):
            break
        time.sleep(0.05)
    assert snap["status"] == "FAILED"
    assert snap["error"]["code"] == "JOB_INPUTS_CHANGED"
    assert not design_service.tunnel_report_path(sid).exists()
    assert not design_service.tunnel_glb_path(sid).exists()


def test_legacy_tunnel_profile_migration(store: ScenarioStore) -> None:
    """Pre-Phase-06 scenarios persisted ``tunnelProfile.width/crownRadius``;
    they must still load (deprecated fields are dropped, rule 65/67)."""
    from tests.conftest import small_scenario

    sc = small_scenario(with_fault=False)
    created = store.create(sc)
    path = store.scenario_path(created.id)
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["tunnelProfile"]["width"] = 5.0
    doc["tunnelProfile"]["crownRadius"] = 2.5
    path.write_text(json.dumps(doc), encoding="utf-8")
    loaded = store.get(created.id)
    dumped = loaded.tunnel_profile.model_dump(by_alias=True)
    assert "width" not in dumped and "crownRadius" not in dumped
    assert loaded.tunnel_profile.wall_height == 2.5
