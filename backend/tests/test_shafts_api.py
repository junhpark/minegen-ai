"""Phase 20C.2B shaft + capability-graph API lifecycle (directive §42, §51,
§52; rules 182–185): synchronous endpoints, typed prerequisites, the
levels → shafts → network → capability graph invalidation chain and the
fail-closed revision synchronization."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from minegen.services.design_service import DesignService
from tests.conftest import small_scenario
from tests.test_network_api import _levels, _network
from tests.test_smoothing_api import _decline
from tests.test_tunnel_api import _smooth


def _prepare_with_shaft(client: TestClient) -> str:
    sc = small_scenario(with_fault=True)
    payload = sc.model_dump(by_alias=True, exclude={"id", "schema_version"})
    r = client.post("/api/v1/scenarios", json=payload)
    assert r.status_code == 201, r.text
    sid = str(r.json()["id"])
    doc = client.get(f"/api/v1/scenarios/{sid}").json()
    doc.pop("id"), doc.pop("schemaVersion")
    doc["design"]["candidateCount"] = 1
    doc["design"]["search"]["maxExpansionsPerCandidate"] = 20000
    doc["shafts"] = {"specs": [{"shaftId": "SHAFT-01", "role": "PRODUCTION"}]}
    assert client.put(f"/api/v1/scenarios/{sid}", json=doc).status_code == 200
    assert client.post(f"/api/v1/scenarios/{sid}/world/generate").status_code == 200
    assert client.post(f"/api/v1/scenarios/{sid}/design/targets").status_code == 200
    return sid


def _shafts(client: TestClient, sid: str) -> dict:  # type: ignore[type-arg]
    r = client.post(f"/api/v1/scenarios/{sid}/design/shafts")
    assert r.status_code == 200, r.text
    body: dict = r.json()  # type: ignore[type-arg]
    return body


def _capability(client: TestClient, sid: str) -> dict:  # type: ignore[type-arg]
    r = client.post(f"/api/v1/scenarios/{sid}/design/capability-graph")
    assert r.status_code == 200, r.text
    body: dict = r.json()  # type: ignore[type-arg]
    return body


def test_shaft_and_capability_api_lifecycle(
    client: TestClient, design_service: DesignService
) -> None:
    sid = _prepare_with_shaft(client)
    base = f"/api/v1/scenarios/{sid}"
    # prerequisites are typed
    r = client.post(f"{base}/design/shafts")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "LEVELS_NOT_GENERATED"
    r = client.get(f"{base}/design/shafts")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "SHAFTS_NOT_GENERATED"
    r = client.post(f"{base}/design/capability-graph")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "NETWORK_NOT_GENERATED"
    r = client.get(f"{base}/design/capability-graph")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "CAPABILITY_GRAPH_NOT_GENERATED"

    _decline(client, sid)
    _smooth(client, sid)
    lv = _levels(client, sid)
    assert lv["status"] == "SUCCESS", lv["failureReason"]

    # shafts are OPTIONAL: the network builds without them, unchanged
    plain = _network(client, sid)
    assert plain["status"] == "SUCCESS", plain["failureReason"]
    assert plain["metrics"]["shaftCount"] == 0
    assert not any(n["type"].startswith("SHAFT") for n in plain["nodes"])

    shafts = _shafts(client, sid)
    assert shafts["status"] == "SUCCESS", shafts["failureReason"]
    assert shafts["shafts"][0]["status"] == "OK"
    assert [s["levelId"] for s in shafts["shafts"][0]["stations"]] == [
        lvl["levelId"] for lvl in lv["levels"]
    ]
    assert client.get(f"{base}/design/shafts").json() == shafts
    # generating shafts invalidated the network (rule 184)
    assert client.get(f"{base}/network").status_code == 404

    net = _network(client, sid)
    assert net["status"] == "SUCCESS", net["failureReason"]
    assert net["metrics"]["shaftCount"] == 1
    shaft_edges = [e for e in net["edges"] if e["type"] == "SHAFT"]
    assert shaft_edges and all(e["geometryRef"]["artifact"] == "shafts.json" for e in shaft_edges)
    assert all(
        e["orientation"] == "VERTICAL" and e["meanGradientSigned"] is None for e in shaft_edges
    )

    cap = _capability(client, sid)
    assert cap["status"] == "SUCCESS", cap["failureReason"]
    assert cap["networkSourceRevision"] == net["sourceRevision"]
    assert "SHAFT_COLLAR:SHAFT-01" in cap["surfaceNodeIds"]
    assert client.get(f"{base}/design/capability-graph").json() == cap
    # path query: physical and capability answers are distinct fields
    station = shafts["shafts"][0]["stations"][0]["stationId"]
    r = client.get(
        f"{base}/design/capability-graph/path",
        params={"source": "PORTAL", "target": station, "capability": "PERSONNEL_ACCESS"},
    )
    assert r.status_code == 200, r.text
    q = r.json()
    assert q["physicalReachable"] and q["capabilityReachable"]
    assert q["pathNodeIds"][0] == "PORTAL" and q["pathNodeIds"][-1] == station
    r = client.get(
        f"{base}/design/capability-graph/path",
        params={"source": "PORTAL", "target": "NOPE", "capability": "PERSONNEL_ACCESS"},
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "UNKNOWN_NETWORK_NODE"

    # scene carries both artifacts
    scene = client.get(f"{base}/scene").json()
    assert scene["shafts"]["status"] == "SUCCESS"
    assert scene["capabilityGraph"]["status"] == "SUCCESS"

    # timeline / infrastructure consume the shaft (amendment A3)
    assert client.post(f"{base}/design/stopes").status_code == 200
    tl = client.post(f"{base}/design/timeline")
    assert tl.status_code == 200 and tl.json()["status"] == "SUCCESS", tl.text
    assert any(t["taskType"] == "DEVELOP_SHAFT" for t in tl.json()["tasks"])
    comm = client.post(f"{base}/infrastructure/communication")
    assert comm.status_code == 200 and comm.json()["status"] == "SUCCESS", comm.text

    # -- invalidation chain ------------------------------------------------ #
    # network regeneration deletes the capability graph, nothing else
    _network(client, sid)
    assert client.get(f"{base}/design/capability-graph").status_code == 404
    assert client.get(f"{base}/design/shafts").status_code == 200
    _capability(client, sid)
    # shaft regeneration deletes network + capability graph
    _shafts(client, sid)
    assert client.get(f"{base}/network").status_code == 404
    assert client.get(f"{base}/design/capability-graph").status_code == 404
    _network(client, sid)
    _capability(client, sid)
    # levels regeneration deletes shafts, network and the capability graph
    _levels(client, sid)
    assert client.get(f"{base}/design/shafts").status_code == 404
    assert client.get(f"{base}/network").status_code == 404
    assert client.get(f"{base}/design/capability-graph").status_code == 404
    # a stale shaft artifact (levels moved on) is refused by the network
    _shafts(client, sid)
    _levels(client, sid)  # deletes shafts.json …
    shafts_path = design_service.shafts_path(sid)
    shafts_path.write_text(json.dumps(shafts), encoding="utf-8")  # … put an old one back
    r = client.post(f"{base}/network/generate")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SHAFTS_STALE"
    # a capability graph whose network moved on is refused, never reused
    _shafts(client, sid)
    _network(client, sid)
    cap = _capability(client, sid)
    net_path = design_service.network_path(sid)
    net_path.write_text(net_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    r = client.get(f"{base}/design/capability-graph")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "CAPABILITY_GRAPH_STALE"
