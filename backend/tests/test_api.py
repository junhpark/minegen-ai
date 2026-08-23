from __future__ import annotations

from fastapi.testclient import TestClient

from minegen.services.scenario_service import ScenarioStore


def test_health(client: TestClient) -> None:
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["coordinateSystem"] == "ENU_Z_UP"


def test_scenario_crud_roundtrip(client: TestClient, store: ScenarioStore) -> None:
    r = client.post("/api/v1/scenarios", json={"name": "Synthetic Gold Mine 001", "seed": 7})
    assert r.status_code == 201, r.text
    created = r.json()
    sid = created["id"]
    assert created["seed"] == 7
    assert store.scenario_path(sid).is_file()

    r = client.get(f"/api/v1/scenarios/{sid}")
    assert r.status_code == 200
    assert r.json() == created

    r = client.get("/api/v1/scenarios")
    assert [s["id"] for s in r.json()] == [sid]

    updated = {**created, "name": "renamed"}
    updated.pop("id")
    updated.pop("schemaVersion")
    r = client.put(f"/api/v1/scenarios/{sid}", json=updated)
    assert r.status_code == 200
    assert r.json()["name"] == "renamed"
    assert r.json()["id"] == sid


def test_missing_scenario_is_structured_404(client: TestClient) -> None:
    r = client.get("/api/v1/scenarios/nope")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "SCENARIO_NOT_FOUND"


def test_invalid_payload_is_422(client: TestClient) -> None:
    r = client.post("/api/v1/scenarios", json={"ramp": {"maxGradient": 0.9}})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "VALIDATION_ERROR"


def test_non_finite_json_is_rejected_with_422(client: TestClient) -> None:
    # Python's json module accepts the NaN token; the schema must still reject it.
    for token in ("NaN", "Infinity", "-Infinity"):
        r = client.post(
            "/api/v1/scenarios",
            content=f'{{"portal": {{"x": {token}, "y": 0, "z": 0}}}}',
            headers={"content-type": "application/json"},
        )
        assert r.status_code == 422, (token, r.text)
        body = r.json()
        assert body["detail"]["code"] == "VALIDATION_ERROR"
        assert body["detail"]["errors"][0]["loc"] == ["body", "portal", "x"]
