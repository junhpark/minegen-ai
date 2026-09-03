"""Phase 20A layout-v2 service/API lifecycle: catalogue job, selection,
activation, explicit ramp-source resolution, invalidation chain and the
mandatory TABULAR downstream integration through the parametric Effective
Ramp (tunnel → levels → network → timeline → communication/sensors)."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from minegen.services.design_service import DesignService
from tests.test_smoothing_api import _decline, _prepare
from tests.test_tunnel_api import _smooth


def _generate_layout(client: TestClient, sid: str) -> dict:  # type: ignore[type-arg]
    r = client.post(f"/api/v1/scenarios/{sid}/design/layout-v2", params={"sync": "true"})
    assert r.status_code == 200, r.text
    body: dict = r.json()  # type: ignore[type-arg]
    return body


def _winner(catalogue: dict) -> str:  # type: ignore[type-arg]
    assert catalogue["status"] == "SUCCESS" and catalogue["winnerId"]
    return str(catalogue["winnerId"])


def _world(client: TestClient) -> str:
    sid = _prepare(client)
    return sid


def test_layout_requires_world_and_catalogue_contract(client: TestClient) -> None:
    from tests.test_world_api import _create

    sid = _create(client)
    r = client.post(f"/api/v1/scenarios/{sid}/design/layout-v2", params={"sync": "true"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "WORLD_NOT_GENERATED"
    r = client.get(f"/api/v1/scenarios/{sid}/design/layout-v2")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "WORLD_NOT_GENERATED"

    sid = _world(client)
    r = client.get(f"/api/v1/scenarios/{sid}/design/layout-v2")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "LAYOUT_V2_NOT_GENERATED"
    cat = _generate_layout(client, sid)
    assert cat["layoutVersion"] == 1 and cat["candidateCount"] == 68
    assert cat["clearanceBasis"] == "EXACT" and cat["requiredClearance"] > 0
    assert len(cat["candidates"]) == 68 and cat["feasibleCount"] >= 1
    assert cat["ranking"][0] == cat["winnerId"]
    for c in cat["candidates"]:
        assert c["status"] in ("FEASIBLE", "INFEASIBLE", "NOT_VALIDATED")
        assert c["family"] in ("SPIRAL", "LONGITUDINAL", "SWITCHBACK")
        assert (c["centerline"] is not None) == c["shortlisted"]
        if c["status"] == "INFEASIBLE":
            assert c["failureReasons"]
    assert len(cat["requiredLevels"]) >= 2
    got = client.get(f"/api/v1/scenarios/{sid}/design/layout-v2")
    assert got.status_code == 200 and got.json() == cat
    assert "NaN" not in got.text and "Infinity" not in got.text
    # the search is a job kind too
    r = client.post(f"/api/v1/scenarios/{sid}/design/layout-v2")
    assert r.status_code == 202 and r.json()["kind"] == "LAYOUT_V2"
    job = r.json()["jobId"]
    for _ in range(600):
        snap = client.get(f"/api/v1/jobs/{job}").json()
        if snap["status"] in ("SUCCEEDED", "FAILED"):
            break
        import time

        time.sleep(0.05)
    assert snap["status"] == "SUCCEEDED", snap.get("error")
    assert snap["result"]["winnerId"] == cat["winnerId"]
    assert snap["progress"]["phase"] == "LAYOUT_V2"
    # scene: slim catalogue (no geometry), no selection, LEGACY source
    scene = client.get(f"/api/v1/scenarios/{sid}/scene").json()
    assert scene["layoutV2"]["winnerId"] == cat["winnerId"]
    assert all("centerline" not in c for c in scene["layoutV2"]["candidates"])
    assert scene["layoutV2Selected"] is None
    assert scene["rampSource"]["activeSource"] == "LEGACY"
    assert scene["rampSource"]["layoutV2Available"] is True
    assert scene["smoothedDecline"] is None


def test_select_activate_and_ramp_source_resolution(
    client: TestClient, design_service: DesignService
) -> None:
    sid = _world(client)
    base = f"/api/v1/scenarios/{sid}/design"
    # nothing selected / generated yet
    r = client.post(f"{base}/layout-v2/select", json={"candidateId": "X"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "LAYOUT_V2_NOT_GENERATED"
    r = client.put(f"{base}/ramp-source", json={"activeSource": "LAYOUT_V2"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "LAYOUT_V2_NOT_SELECTED"
    r = client.get(f"{base}/ramp")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SMOOTHED_NOT_GENERATED"
    src = client.get(f"{base}/ramp-source").json()
    assert src["activeSource"] == "LEGACY" and src["available"] is False

    cat = _generate_layout(client, sid)
    winner = _winner(cat)
    infeasible = next(c["candidateId"] for c in cat["candidates"] if c["status"] == "INFEASIBLE")
    r = client.post(f"{base}/layout-v2/select", json={"candidateId": "NOPE"})
    assert r.status_code == 404 and r.json()["detail"]["code"] == "LAYOUT_V2_CANDIDATE_NOT_FOUND"
    r = client.post(f"{base}/layout-v2/select", json={"candidateId": infeasible})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "LAYOUT_V2_CANDIDATE_INFEASIBLE"
    r = client.get(f"{base}/layout-v2/selected")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "LAYOUT_V2_NOT_SELECTED"

    # select: materialized effective ramp, source still LEGACY
    r = client.post(f"{base}/layout-v2/select", json={"candidateId": winner})
    assert r.status_code == 200, r.text
    sel = r.json()
    assert sel["sourceKind"] == "PARAMETRIC_V2" and sel["candidateId"] == winner
    assert sel["owningArtifact"] == "layout_v2_selected.json"
    assert sel["status"] == "SUCCESS" and sel["layoutRevision"]
    assert len(sel["segments"]) == cat["serviceableLevelCount"]
    assert [s["levelId"] for s in sel["segments"]] == [
        lv["levelId"] for lv in cat["requiredLevels"] if lv["hasOrebodySection"]
    ]
    for s in sel["segments"]:
        assert s["effectiveSource"] == "PARAMETRIC_V2" and s["smoothed"] is None
        pts = s["effectiveCenterline"]["points"]
        assert len(pts) == 3 * s["effectiveCenterline"]["pointCount"] >= 6
        assert pts[-1] == s["levelConnection"]["position"][2] == s["levelConnection"]["elevation"]
    assert client.get(f"{base}/layout-v2/selected").json() == sel
    assert client.get(f"{base}/ramp-source").json()["activeSource"] == "LEGACY"
    assert client.get(f"{base}/ramp").status_code == 409  # LEGACY has no smoothed decline
    # re-selecting the same candidate is a no-op (same payload)
    assert client.post(f"{base}/layout-v2/select", json={"candidateId": winner}).json() == sel

    # explicit source switch
    r = client.put(f"{base}/ramp-source", json={"activeSource": "LAYOUT_V2"})
    assert r.status_code == 200, r.text
    src = r.json()
    assert src["activeSource"] == "LAYOUT_V2" and src["available"] is True
    assert src["sourceKind"] == "PARAMETRIC_V2" and src["candidateId"] == winner
    assert src["owningArtifact"] == "layout_v2_selected.json"
    ramp = client.get(f"{base}/ramp").json()
    assert ramp["activeSource"] == "LAYOUT_V2" and ramp["candidateId"] == winner
    assert ramp["segments"] == sel["segments"]
    assert json.loads(design_service.ramp_source_path(sid).read_text()) == {
        "activeSource": "LAYOUT_V2"
    }
    scene = client.get(f"/api/v1/scenarios/{sid}/scene").json()
    assert scene["smoothedDecline"]["sourceKind"] == "PARAMETRIC_V2"
    assert scene["legacySmoothedDecline"] is None
    assert scene["layoutV2Selected"]["candidateId"] == winner
    assert scene["rampSource"]["activeSource"] == "LAYOUT_V2"

    # activate = select + switch (idempotent for the same candidate)
    r = client.post(f"{base}/layout-v2/activate", json={"candidateId": winner})
    assert r.status_code == 200 and r.json()["rampSource"]["activeSource"] == "LAYOUT_V2"
    assert r.json()["selected"] == sel

    # back to LEGACY: explicit, deterministic, no legacy artifact → 409 on ramp
    r = client.put(f"{base}/ramp-source", json={"activeSource": "LEGACY"})
    assert r.status_code == 200 and r.json()["activeSource"] == "LEGACY"
    assert client.get(f"{base}/ramp").status_code == 409
    assert client.get(f"{base}/layout-v2/selected").status_code == 200  # selection kept


def test_parametric_ramp_drives_the_tabular_downstream_chain(
    client: TestClient, design_service: DesignService
) -> None:
    """Directive §33: v2 Effective Ramp → tunnel → levels → network →
    timeline → communication / sensors, with the owning artifact
    ``layout_v2_selected.json`` referenced everywhere."""
    sid = _world(client)
    base = f"/api/v1/scenarios/{sid}/design"
    cat = _generate_layout(client, sid)
    # a SPIRAL winner is not guaranteed on the small world: activate the best
    # ranked spiral when one is feasible, else the winner
    spirals = [c for c in cat["ranking"] if c.startswith("SPIRAL")]
    chosen = spirals[0] if spirals else _winner(cat)
    r = client.post(f"{base}/layout-v2/activate", json={"candidateId": chosen})
    assert r.status_code == 200, r.text
    n_seg = len(r.json()["selected"]["segments"])

    # tunnel (Phase 06) over the parametric ramp
    r = client.post(f"{base}/tunnel", params={"sync": "true"})
    assert r.status_code == 200, r.text
    tunnel = r.json()
    assert tunnel["status"] == "SUCCESS", tunnel.get("failureReason")
    assert len(tunnel["segments"]) == n_seg
    assert all(s["effectiveSource"] == "PARAMETRIC_V2" for s in tunnel["segments"])
    assert tunnel["watertight"] and tunnel["manifold"]
    assert client.get(f"{base}/tunnel/mesh.glb").status_code == 200

    # levels (Phase 08) anchored at the v2 level connection points
    r = client.post(f"{base}/levels")
    assert r.status_code == 200, r.text
    levels = r.json()
    assert levels["status"] == "SUCCESS", levels.get("failureReason")
    sel = client.get(f"{base}/layout-v2/selected").json()
    entries = {s["levelId"]: s["levelConnection"]["position"] for s in sel["segments"]}
    drifts = [d for d in levels["developments"] if d["kind"] == "DRIFT"]
    assert {d["levelId"] for d in drifts} == set(entries)
    assert {lv["levelId"]: lv["entry"] for lv in levels["levels"]} == entries

    # network (Phase 07): RAMP edges reference the layout-v2 owning artifact
    r = client.post(f"/api/v1/scenarios/{sid}/network/generate")
    assert r.status_code == 200, r.text
    net = r.json()
    assert net["status"] == "SUCCESS", net.get("failureReason")
    ramps = [e for e in net["edges"] if e["type"] == "RAMP"]
    assert len(ramps) == n_seg
    for i, e in enumerate(ramps):
        assert e["geometryRef"] == {"artifact": "layout_v2_selected.json", "segmentIndex": i}
        assert e["effectiveSource"] == "PARAMETRIC_V2"
    entry_nodes = {n["levelId"]: n["position"] for n in net["nodes"] if n["type"] == "LEVEL_ENTRY"}
    for lid, pos in entries.items():
        assert entry_nodes[lid] == pos

    # stopes + timeline (Phase 09/10) with continuous RAMP chainage
    assert client.post(f"{base}/stopes").status_code == 200
    r = client.post(f"{base}/timeline")
    assert r.status_code == 200, r.text
    tl = r.json()
    assert tl["status"] == "SUCCESS", tl.get("failureReason")
    ramp_tasks = [
        d for d in tl["developments"] if d["geometryRef"]["artifact"] == "layout_v2_selected.json"
    ]
    assert len(ramp_tasks) == n_seg
    for d in ramp_tasks:
        frac = d["pointChainageFractions"]
        assert frac[0] == 0.0 and abs(frac[-1] - 1.0) < 1e-12

    # infrastructure (Phase 11/12) through the shared network domain
    r = client.post(f"/api/v1/scenarios/{sid}/infrastructure/communication")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "SUCCESS", r.json().get("failureReason")
    r = client.post(f"/api/v1/scenarios/{sid}/infrastructure/sensors")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "SUCCESS", r.json().get("failureReason")

    # scene exposes the whole chain over the v2 ramp
    scene = client.get(f"/api/v1/scenarios/{sid}/scene").json()
    assert scene["smoothedDecline"]["sourceKind"] == "PARAMETRIC_V2"
    assert scene["tunnelMesh"]["status"] == "SUCCESS" and scene["network"]["status"] == "SUCCESS"
    assert scene["timeline"]["status"] == "SUCCESS"

    # -- invalidation (rule 151) ---------------------------------------------
    # switching the source deletes everything ramp-derived, keeps the ramps
    r = client.put(f"{base}/ramp-source", json={"activeSource": "LEGACY"})
    assert r.status_code == 200
    for path in (
        design_service.tunnel_report_path(sid),
        design_service.levels_path(sid),
        design_service.network_path(sid),
        design_service.stopes_path(sid),
        design_service.timeline_path(sid),
        design_service.store.derived_dir(sid) / "communication.json",
        design_service.store.derived_dir(sid) / "sensors.json",
    ):
        assert not path.exists(), path
    assert design_service.layout_path(sid).is_file()
    assert design_service.layout_selected_path(sid).is_file()
    assert design_service.store.arrays_path(sid).is_file()  # geology untouched
    # re-activating rebuilds nothing by itself (explicit regeneration only)
    client.post(f"{base}/layout-v2/activate", json={"candidateId": chosen})
    assert client.get(f"{base}/tunnel").status_code == 409
    client.post(f"{base}/tunnel", params={"sync": "true"})
    assert client.get(f"{base}/tunnel").status_code == 200
    # regenerating the catalogue deletes the stale selection and the chain
    _generate_layout(client, sid)
    assert not design_service.layout_selected_path(sid).exists()
    assert client.get(f"{base}/tunnel").status_code == 409
    assert client.get(f"{base}/ramp").status_code == 409  # LAYOUT_V2 without selection
    assert client.get(f"{base}/ramp").json()["detail"]["code"] == "LAYOUT_V2_NOT_SELECTED"
    # a scenario mutation clears every derived file → default LEGACY source
    doc = client.get(f"/api/v1/scenarios/{sid}").json()
    doc.pop("id"), doc.pop("schemaVersion")
    client.put(f"/api/v1/scenarios/{sid}", json=doc)
    assert not design_service.layout_path(sid).exists()
    assert not design_service.ramp_source_path(sid).exists()
    client.post(f"/api/v1/scenarios/{sid}/world/generate")
    assert client.get(f"{base}/ramp-source").json()["activeSource"] == "LEGACY"


def test_legacy_pipeline_is_unchanged_and_isolated_from_layout_v2(
    client: TestClient, design_service: DesignService
) -> None:
    sid = _world(client)
    base = f"/api/v1/scenarios/{sid}/design"
    _decline(client, sid)
    _smooth(client, sid)
    smoothed = client.get(f"{base}/decline/smooth").json()
    assert smoothed["status"] in ("SUCCESS", "SUCCESS_WITH_FALLBACK")
    ramp = client.get(f"{base}/ramp").json()
    assert ramp["activeSource"] == "LEGACY" and ramp["owningArtifact"] == "decline_smoothed.json"
    assert ramp["sourceKind"] in ("LEGACY_SMOOTHED", "LEGACY_RAW_FALLBACK")
    assert ramp["segments"] == smoothed["segments"]
    # legacy tunnel via the adapter: identical to the Phase 05 consumer path
    r = client.post(f"{base}/tunnel", params={"sync": "true"})
    assert r.status_code == 200 and r.json()["status"] == "SUCCESS"
    # generating (not activating) a layout leaves the LEGACY chain intact
    cat = _generate_layout(client, sid)
    assert client.get(f"{base}/tunnel").status_code == 200
    assert client.get(f"{base}/decline/smooth").status_code == 200
    client.post(f"{base}/layout-v2/select", json={"candidateId": _winner(cat)})
    assert client.get(f"{base}/tunnel").status_code == 200  # selection alone is inert
    # activating LAYOUT_V2 invalidates the legacy-derived chain but never the
    # legacy artifacts themselves
    client.post(f"{base}/layout-v2/activate", json={"candidateId": _winner(cat)})
    assert client.get(f"{base}/tunnel").status_code == 409
    assert client.get(f"{base}/decline/smooth").status_code == 200
    assert client.get(f"{base}/decline").status_code == 200
    # while LAYOUT_V2 is active, re-running the legacy smoother does not touch
    # the LAYOUT_V2-derived chain
    client.post(f"{base}/tunnel", params={"sync": "true"})
    assert client.get(f"{base}/tunnel").status_code == 200
    _smooth(client, sid)
    assert client.get(f"{base}/tunnel").status_code == 200
    # switching back exposes the legacy ramp again
    client.put(f"{base}/ramp-source", json={"activeSource": "LEGACY"})
    assert client.get(f"{base}/ramp").json()["sourceKind"].startswith("LEGACY")
    assert design_service.smoothed_path(sid).is_file()
