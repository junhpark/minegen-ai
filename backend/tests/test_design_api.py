from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_world_api import _create


def test_targets_lifecycle(client: TestClient) -> None:
    sid = _create(client)
    r = client.post(f"/api/v1/scenarios/{sid}/design/targets")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "WORLD_NOT_GENERATED"

    client.post(f"/api/v1/scenarios/{sid}/world/generate")
    r = client.get(f"/api/v1/scenarios/{sid}/design/targets")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "TARGETS_NOT_GENERATED"

    r = client.post(f"/api/v1/scenarios/{sid}/design/targets")
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["nLevels"] > 0 and t["nCandidates"] == t["nLevels"] * 5
    assert client.get(f"/api/v1/scenarios/{sid}/design/targets").json() == t
    assert client.get(f"/api/v1/scenarios/{sid}/scene").json()["accessTargets"] == t

    # regenerating the world discards targets (rule 46)
    client.post(f"/api/v1/scenarios/{sid}/world/generate")
    assert client.get(f"/api/v1/scenarios/{sid}/design/targets").status_code == 409
    assert client.get(f"/api/v1/scenarios/{sid}/scene").json()["accessTargets"] is None


def test_cost_evaluate_endpoint(client: TestClient) -> None:
    sid = _create(client)
    client.post(f"/api/v1/scenarios/{sid}/world/generate")
    r = client.post(
        f"/api/v1/scenarios/{sid}/design/cost/evaluate",
        json={"points": [[-150, 120, -60], [40, 20, -50], [9999, 0, 0]]},
    )
    assert r.status_code == 200, r.text
    res = r.json()["results"]
    assert res[0]["valid"] and res[0]["totalCostPerM"] >= 1.0
    assert not res[1]["valid"] and res[1]["totalCostPerM"] is None
    assert "INSIDE_OREBODY" in res[1]["rejectionReasons"]
    assert "OUTSIDE_WORLD" in res[2]["rejectionReasons"]

    r = client.post(f"/api/v1/scenarios/{sid}/design/cost/evaluate", json={"points": [[1, 2]]})
    assert r.status_code == 422
    r = client.post(f"/api/v1/scenarios/{sid}/design/cost/evaluate", json={"points": []})
    assert r.status_code == 422


def test_decline_lifecycle(client: TestClient) -> None:
    sid = _create(client)
    client.post(f"/api/v1/scenarios/{sid}/world/generate")
    r = client.post(f"/api/v1/scenarios/{sid}/design/decline")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "TARGETS_NOT_GENERATED"
    # one candidate per level keeps this fast
    doc = client.get(f"/api/v1/scenarios/{sid}").json()
    doc.pop("id"), doc.pop("schemaVersion")
    doc["design"]["candidateCount"] = 1
    doc["design"]["search"]["maxExpansionsPerCandidate"] = 20000
    client.put(f"/api/v1/scenarios/{sid}", json=doc)
    client.post(f"/api/v1/scenarios/{sid}/world/generate")
    client.post(f"/api/v1/scenarios/{sid}/design/targets")
    assert client.get(f"/api/v1/scenarios/{sid}/design/decline").status_code == 409

    r = client.post(f"/api/v1/scenarios/{sid}/design/decline", params={"maxLevels": 2})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "SUCCESS" and d["completedLevels"] == 2
    assert d["centerline"]["pointCount"] == len(d["centerline"]["points"]) // 3
    assert d["levels"][0]["selectedCandidateId"] is not None
    diag = d["levels"][0]["candidateResults"][0]["diagnostics"]
    assert diag["expandedStates"] > 0 and diag["heuristicWeight"] == 2.0
    assert client.get(f"/api/v1/scenarios/{sid}/design/decline").json() == d
    assert client.get(f"/api/v1/scenarios/{sid}/scene").json()["decline"]["status"] == "SUCCESS"
    # regenerating targets discards the decline (rule 46)
    client.post(f"/api/v1/scenarios/{sid}/design/targets")
    assert client.get(f"/api/v1/scenarios/{sid}/design/decline").status_code == 409
