from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from minegen.services.scenario_service import ScenarioStore
from tests.conftest import small_scenario


def _create(client: TestClient) -> str:
    sc = small_scenario()
    payload = sc.model_dump(by_alias=True, exclude={"id", "schema_version"})
    r = client.post("/api/v1/scenarios", json=payload)
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def test_world_generate_and_persist(client: TestClient, store: ScenarioStore) -> None:
    sid = _create(client)
    r = client.get(f"/api/v1/scenarios/{sid}/world")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "WORLD_NOT_GENERATED"

    r = client.post(f"/api/v1/scenarios/{sid}/world/generate")
    assert r.status_code == 200, r.text
    stats = r.json()
    assert stats["blockModel"]["nOreBlocks"] > 0
    assert stats["faults"] == 1
    assert store.arrays_path(sid).is_file()
    assert (store.derived_dir(sid) / "world.json").is_file()

    r = client.get(f"/api/v1/scenarios/{sid}/world")
    assert r.status_code == 200 and r.json() == stats


def test_scene_manifest_shape(client: TestClient) -> None:
    sid = _create(client)
    client.post(f"/api/v1/scenarios/{sid}/world/generate")
    r = client.get(f"/api/v1/scenarios/{sid}/scene")
    assert r.status_code == 200
    s = r.json()
    assert s["coordinateSystem"] == "ENU_Z_UP"
    t = s["terrain"]
    assert len(t["z"]) == t["nx"] * t["ny"]
    assert len(s["orebody"]["positions"]) == 8 * 3 and len(s["orebody"]["indices"]) == 12 * 3
    assert len(s["faults"]) == 1 and s["faults"][0]["vertexCount"] >= 3
    ob = s["oreBlocks"]
    assert ob["count"] == len(ob["grade"]) == len(ob["centers"]) // 3
    sl = s["rockQuality"]["defaultSlice"]
    assert sl["axis"] == "z" and len(sl["values"]) == sl["rows"]["n"] * sl["cols"]["n"]
    assert s["world"]["bottomElevation"] == -150.0  # 100 − 250 (rule 35)
    # nothing non-finite on the wire
    for arr in (t["z"], ob["grade"], ob["centers"], sl["values"]):
        assert np.isfinite(arr).all()


def test_slice_endpoint(client: TestClient) -> None:
    sid = _create(client)
    client.post(f"/api/v1/scenarios/{sid}/world/generate")
    r = client.get(f"/api/v1/scenarios/{sid}/world/slice", params={"axis": "x", "index": 3})
    assert r.status_code == 200
    s = r.json()
    assert s["axis"] == "x" and s["rows"]["axis"] == "y" and s["cols"]["axis"] == "z"
    assert len(s["values"]) == s["rows"]["n"] * s["cols"]["n"]

    r = client.get(
        f"/api/v1/scenarios/{sid}/world/slice",
        params={"field": "faultInfluence", "axis": "z", "index": 5},
    )
    assert r.status_code == 200 and r.json()["max"] <= 1.0

    r = client.get(f"/api/v1/scenarios/{sid}/world/slice", params={"axis": "z", "index": 9999})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "SLICE_OUT_OF_RANGE"

    r = client.get(f"/api/v1/scenarios/{sid}/world/slice", params={"field": "bogus"})
    assert r.status_code == 422


def test_world_reload_from_disk_matches_memory(client: TestClient, store: ScenarioStore) -> None:
    sid = _create(client)
    stats = client.post(f"/api/v1/scenarios/{sid}/world/generate").json()
    # fresh service instance must reconstruct the same stats from arrays.npz
    from minegen.services.world_service import WorldService

    fresh = WorldService(store)
    assert fresh.stats(sid) == stats


def test_regenerate_is_idempotent(client: TestClient) -> None:
    sid = _create(client)
    a = client.post(f"/api/v1/scenarios/{sid}/world/generate").json()
    b = client.post(f"/api/v1/scenarios/{sid}/world/generate").json()
    assert a == b


def test_scenario_replace_invalidates_all_derived_state(
    client: TestClient, store: ScenarioStore
) -> None:
    """generate → PUT → 409 everywhere (also from a fresh service) → regenerate → new seed."""
    from minegen.services.world_service import WorldNotGeneratedError, WorldService

    sid = _create(client)
    before = client.post(f"/api/v1/scenarios/{sid}/world/generate").json()
    assert store.arrays_path(sid).is_file()
    assert (store.derived_dir(sid) / "world.json").is_file()

    doc = client.get(f"/api/v1/scenarios/{sid}").json()
    doc.pop("id"), doc.pop("schemaVersion")
    doc["seed"] = 999
    r = client.put(f"/api/v1/scenarios/{sid}", json=doc)
    assert r.status_code == 200 and r.json()["seed"] == 999

    # derived state is gone from disk, not just from memory
    assert not store.arrays_path(sid).exists()
    assert store.derived_dir(sid).is_dir()
    assert list(store.derived_dir(sid).iterdir()) == []

    for path, params in (
        (f"/api/v1/scenarios/{sid}/world", {}),
        (f"/api/v1/scenarios/{sid}/scene", {}),
        (f"/api/v1/scenarios/{sid}/world/slice", {"axis": "z", "index": 0}),
    ):
        r = client.get(path, params=params)
        assert r.status_code == 409, path
        assert r.json()["detail"]["code"] == "WORLD_NOT_GENERATED"

    # a brand-new service instance must not find anything stale on disk either
    fresh = WorldService(store)
    assert not fresh.is_generated(sid)
    with pytest.raises(WorldNotGeneratedError):
        fresh.stats(sid)

    after = client.post(f"/api/v1/scenarios/{sid}/world/generate").json()
    assert after["terrain"]["zMin"] != before["terrain"]["zMin"]
    assert after["blockModel"]["rockQualityMean"] != before["blockModel"]["rockQualityMean"]
    # geometry-only quantities are unchanged by the seed
    assert after["orebody"] == before["orebody"]
    assert after["blockModel"]["nOreBlocks"] == before["blockModel"]["nOreBlocks"]
