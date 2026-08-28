"""Phase 07 network API + persistence tests: reserved /network namespace,
synchronous generation, sibling invalidation with the tunnel mesh
(rules 46, 60, 68–70)."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from minegen.services.design_service import DesignService
from minegen.services.scenario_service import ScenarioStore
from tests.test_smoothing_api import _decline, _prepare
from tests.test_tunnel_api import _smooth, _tunnel


def _levels(client: TestClient, sid: str) -> dict:  # type: ignore[type-arg]
    r = client.post(f"/api/v1/scenarios/{sid}/design/levels")
    assert r.status_code == 200, r.text
    body: dict = r.json()  # type: ignore[type-arg]
    return body


def _network(client: TestClient, sid: str) -> dict:  # type: ignore[type-arg]
    r = client.post(f"/api/v1/scenarios/{sid}/network/generate")
    assert r.status_code == 200, r.text
    body: dict = r.json()  # type: ignore[type-arg]
    return body


def test_network_requires_smoothed_and_levels(client: TestClient) -> None:
    sid = _prepare(client)
    _decline(client, sid)
    r = client.post(f"/api/v1/scenarios/{sid}/network/generate")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SMOOTHED_NOT_GENERATED"
    _smooth(client, sid)
    r = client.post(f"/api/v1/scenarios/{sid}/network/generate")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "LEVELS_NOT_GENERATED"
    r = client.get(f"/api/v1/scenarios/{sid}/network")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "NETWORK_NOT_GENERATED"
    assert client.get("/api/v1/scenarios/nope/network").status_code == 404


def test_network_lifecycle_and_payload_contract(
    client: TestClient, design_service: DesignService
) -> None:
    sid = _prepare(client)
    _decline(client, sid)
    _smooth(client, sid)
    lv = _levels(client, sid)
    assert lv["status"] == "SUCCESS", lv["failureReason"]
    body = _network(client, sid)
    assert body["status"] == "SUCCESS", body["failureReason"]

    smoothed = design_service.smoothed(sid)
    n_levels = len(smoothed["segments"])
    n_dev = len(lv["developments"])
    n_sa = lv["metrics"]["crosscutCount"]
    n_j = sum(1 for n in body["nodes"] if n["type"] == "JUNCTION")
    assert body["metrics"]["nodeCount"] == 1 + n_levels + n_j + n_sa
    assert body["metrics"]["edgeCount"] == n_levels + n_dev
    assert body["metrics"]["levelCount"] == n_levels
    assert body["metrics"]["driftEdgeCount"] == lv["metrics"]["driftPieceCount"]
    assert body["metrics"]["crosscutEdgeCount"] == n_sa
    # RAMP physical edges unchanged from Phase 07: same ids, refs, lengths
    ramp = [e for e in body["edges"] if e["type"] == "RAMP"]
    assert len(ramp) == n_levels
    for i, e in enumerate(ramp):
        assert e["geometryRef"] == {"artifact": "decline_smoothed.json", "segmentIndex": i}

    # rule 68: node coordinates ARE the effective centerline endpoints
    pts0 = smoothed["segments"][0]["effectiveCenterline"]["points"]
    assert body["nodes"][0]["position"] == pts0[:3]
    for i, seg in enumerate(smoothed["segments"]):
        pts = seg["effectiveCenterline"]["points"]
        assert body["nodes"][i + 1]["position"] == pts[-3:]
        assert body["edges"][i]["geometryRef"] == {
            "artifact": "decline_smoothed.json",
            "segmentIndex": i,
        }
    assert body["validation"]["synchronized"] is True
    assert body["validation"]["connected"] is True

    # advisory now spans ALL underground nodes (rule 73), all with one path
    (adv,) = body["surfacePathAdvisory"]
    assert len(adv["perNode"]) == body["metrics"]["nodeCount"] - 1
    assert all(e["independentSurfacePaths"] == 1 for e in adv["perNode"])

    # GET returns the persisted payload byte-identically
    got = client.get(f"/api/v1/scenarios/{sid}/network")
    assert got.status_code == 200 and got.json() == body

    # deterministic regeneration (same inputs → identical payload)
    again = _network(client, sid)
    assert json.dumps(again, sort_keys=True) == json.dumps(body, sort_keys=True)


def test_network_and_tunnel_are_siblings(
    client: TestClient, store: ScenarioStore, design_service: DesignService
) -> None:
    """smoothed → {tunnel, levels → network}: a new smoothed artifact deletes
    all three; regenerating a sibling never touches the other branch
    (rules 68/74)."""
    sid = _prepare(client)
    _decline(client, sid)
    _smooth(client, sid)
    _tunnel(client, sid)
    _levels(client, sid)
    _network(client, sid)
    tunnel_path = design_service.tunnel_report_path(sid)
    network_path = design_service.network_path(sid)
    levels_path = design_service.levels_path(sid)
    assert tunnel_path.is_file() and network_path.is_file() and levels_path.is_file()

    # network regeneration leaves the tunnel untouched
    tunnel_bytes = tunnel_path.read_bytes()
    _network(client, sid)
    assert tunnel_path.read_bytes() == tunnel_bytes

    # tunnel regeneration leaves the network untouched
    network_bytes = network_path.read_bytes()
    _tunnel(client, sid)
    assert network_path.read_bytes() == network_bytes

    # rule 74: regenerating LEVELS deletes the network only — never the tunnel
    tunnel_bytes = tunnel_path.read_bytes()
    _levels(client, sid)
    assert not network_path.exists()
    assert tunnel_path.read_bytes() == tunnel_bytes
    _network(client, sid)

    # a new smoothed artifact invalidates tunnel + levels + network
    _smooth(client, sid)
    assert not tunnel_path.exists() and not network_path.exists() and not levels_path.exists()
    r = client.get(f"/api/v1/scenarios/{sid}/network")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "NETWORK_NOT_GENERATED"
    r = client.get(f"/api/v1/scenarios/{sid}/design/levels")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "LEVELS_NOT_GENERATED"


def test_upstream_regeneration_invalidates_network(
    client: TestClient, design_service: DesignService
) -> None:
    sid = _prepare(client)
    _decline(client, sid)
    _smooth(client, sid)
    _levels(client, sid)
    _network(client, sid)
    path = design_service.network_path(sid)
    lpath = design_service.levels_path(sid)
    assert path.is_file() and lpath.is_file()
    _decline(client, sid)  # rule 46/68/74 chain: decline regen clears downstream
    assert not path.exists() and not lpath.exists()
