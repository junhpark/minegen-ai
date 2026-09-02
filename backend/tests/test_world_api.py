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
    assert stats["fields"]["cellCount"] > 0
    assert "blockModel" not in stats and "tonnes" not in stats["orebody"]
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
    # Phase 18: the lattice is described, never shipped as blocks
    assert "oreBlocks" not in s and "blockGrid" not in s
    assert len(s["fieldGrid"]["shape"]) == 3 and s["fieldGrid"]["spacing"] == [10.0, 10.0, 10.0]
    assert "tonnes" not in s["orebody"] and s["orebody"]["volumeM3"] > 0
    sl = s["rockQuality"]["defaultSlice"]
    assert sl["axis"] == "z" and len(sl["values"]) == sl["rows"]["n"] * sl["cols"]["n"]
    assert len(sl["mask"]) == len(sl["values"]) and sl["maskSemantics"] == "BELOW_TERRAIN"
    assert s["world"]["bottomElevation"] == -150.0  # 100 − 250 (rule 35)
    # nothing non-finite on the wire
    for arr in (t["z"], sl["values"]):
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
    # Phase 18: oreFraction is gone — the lattice never describes ore blocks
    r = client.get(f"/api/v1/scenarios/{sid}/world/slice", params={"field": "oreFraction"})
    assert r.status_code == 422


def test_grade_slice_is_masked_by_analytic_orebody_membership(client: TestClient) -> None:
    sid = _create(client)
    client.post(f"/api/v1/scenarios/{sid}/world/generate")
    scene = client.get(f"/api/v1/scenarios/{sid}/scene").json()
    k = scene["rockQuality"]["defaultSlice"]["index"]  # through the orebody centre
    r = client.get(
        f"/api/v1/scenarios/{sid}/world/slice", params={"field": "grade", "axis": "z", "index": k}
    )
    assert r.status_code == 200
    s = r.json()
    mask = np.asarray(s["mask"])
    assert s["maskSemantics"] == "OREBODY_MEMBERSHIP_BELOW_TERRAIN"
    assert 0 < mask.sum() < 0.5 * mask.size  # the slab is a thin band, not the whole grid
    values = np.asarray(s["values"])
    assert (values > 0).all()  # the field is defined everywhere …
    assert s["min"] >= values[mask == 1].min() and s["max"] <= values[mask == 1].max()
    # … but the display range is computed over the shown cells only
    rq = client.get(
        f"/api/v1/scenarios/{sid}/world/slice",
        params={"field": "rockQuality", "axis": "z", "index": k},
    ).json()
    assert rq["maskSemantics"] == "BELOW_TERRAIN" and np.asarray(rq["mask"]).sum() > mask.sum()


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
    assert after["fields"]["rockQuality"]["mean"] != before["fields"]["rockQuality"]["mean"]
    # geometry-only quantities are unchanged by the seed
    assert after["orebody"] == before["orebody"]
    assert after["fields"]["grid"] == before["fields"]["grid"]
