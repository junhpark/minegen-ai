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


# -- Phase 17: scenario realization endpoint ------------------------------- #


def test_realize_endpoint_baseline_and_random(client: TestClient) -> None:
    r = client.post("/api/v1/scenarios/realize", json={"preset": "BASELINE", "seed": 42})
    assert r.status_code == 200
    body = r.json()
    assert body["seed"] == 42
    assert len(body["geology"]["faults"]) == 1
    assert body["orebody"]["orebodyType"] == "TABULAR"

    r1 = client.post(
        "/api/v1/scenarios/realize",
        json={"preset": "RANDOM_ELLIPSOID", "seed": 777, "faultCount": 3},
    )
    r2 = client.post(
        "/api/v1/scenarios/realize",
        json={"preset": "RANDOM_ELLIPSOID", "seed": 777, "faultCount": 3},
    )
    assert r1.status_code == 200 and r1.json() == r2.json()  # deterministic
    assert r1.json()["orebody"]["orebodyType"] == "ELLIPSOID"
    assert len(r1.json()["geology"]["faults"]) == 3


def test_realize_endpoint_never_persists(client: TestClient) -> None:
    before = client.get("/api/v1/scenarios").json()
    client.post("/api/v1/scenarios/realize", json={"preset": "RANDOM_TABULAR", "seed": 5})
    after = client.get("/api/v1/scenarios").json()
    assert before == after


def test_realize_invalid_options_are_typed_422(client: TestClient) -> None:
    r = client.post(
        "/api/v1/scenarios/realize",
        json={"preset": "BASELINE", "seed": 1, "faultCount": 3},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "SCENARIO_REALIZATION_INVALID"


def test_realized_scenario_roundtrip_create_load_world(client: TestClient) -> None:
    realized = client.post(
        "/api/v1/scenarios/realize",
        json={"preset": "RANDOM_ELLIPSOID", "seed": 4242, "faultCount": 1},
    ).json()
    created = client.post("/api/v1/scenarios", json=realized)
    assert created.status_code == 201, created.text
    sid = created.json()["id"]
    loaded = client.get(f"/api/v1/scenarios/{sid}").json()
    assert loaded["orebody"] == realized["orebody"]
    gen = client.post(f"/api/v1/scenarios/{sid}/world/generate")
    assert gen.status_code == 200, gen.text
    scene = client.get(f"/api/v1/scenarios/{sid}/scene").json()
    assert len(scene["orebody"]["positions"]) > 300  # backend-authored mesh


def test_non_tabular_design_is_typed_unsupported_not_500(client: TestClient) -> None:
    realized = client.post(
        "/api/v1/scenarios/realize",
        json={"preset": "RANDOM_ELLIPSOID", "seed": 9, "faultCount": 0},
    ).json()
    sid = client.post("/api/v1/scenarios", json=realized).json()["id"]
    client.post(f"/api/v1/scenarios/{sid}/world/generate")
    r = client.post(f"/api/v1/scenarios/{sid}/design/targets")
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "UNSUPPORTED_OREBODY_FOR_LEGACY_LAYOUT"
    assert "TABULAR" in detail["message"] and "Phase 18" in detail["message"]
