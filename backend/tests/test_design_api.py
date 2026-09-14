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

    r = client.post(
        f"/api/v1/scenarios/{sid}/design/decline", params={"maxLevels": 2, "sync": "true"}
    )
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


def test_the_targets_cache_is_bound_to_the_world_object(client: TestClient) -> None:
    """Stage D S16. ``DesignService._targets`` was the ONE process cache with
    no world binding: ``_evaluators`` and ``_layouts`` both re-validate with
    ``cached[0] is world``, while the targets were served on PRESENCE alone.
    Its consumer is ``generate_decline``, which PERSISTS what it returns, so a
    divergence would have been written out (measured out of band: a warm
    decline of 599 centerline points against a cold one of 737 over
    bit-identical ``scenario.json`` / ``arrays.npz`` / ``targets.json``).

    Nothing on disk moves here: the second read is over the SAME bytes and the
    SAME ``file_revision`` of both inputs, and only the in-memory world object
    is different — which is exactly the binding under test."""
    from minegen.api.deps import get_design_service, get_scenario_store, get_world_service
    from minegen.core.revision import file_revision

    app = client.app
    store = app.dependency_overrides[get_scenario_store]()
    worlds = app.dependency_overrides[get_world_service]()
    design = app.dependency_overrides[get_design_service]()

    sid = _create(client)
    assert client.post(f"/api/v1/scenarios/{sid}/world/generate").status_code == 200
    assert client.post(f"/api/v1/scenarios/{sid}/design/targets").status_code == 200

    revisions = (
        file_revision(store.scenario_path(sid)),
        file_revision(store.arrays_path(sid)),
    )
    first = design._targets_object(sid)
    assert design._targets[sid][0] is worlds._cache[sid].world
    assert design._targets_object(sid) is first  # the warm hit is still a hit

    # a RESTARTED world (same bytes, new object) must miss
    worlds._cache.pop(sid, None)
    second = design._targets_object(sid)
    assert second is not first
    assert design._targets[sid][1] is second
    assert (
        file_revision(store.scenario_path(sid)),
        file_revision(store.arrays_path(sid)),
    ) == revisions
