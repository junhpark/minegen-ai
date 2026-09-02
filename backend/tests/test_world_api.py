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
    assert s["maskSemantics"] == "OREBODY_INTERSECTION_BELOW_TERRAIN"
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


def test_grade_slice_mask_is_cell_intersection_never_named_membership() -> None:
    """Phase 18 acceptance hotfix (rule 129): the grade display mask marks
    display CELLS that intersect the analytic solid. It is a different
    predicate from the old `sdf(centre) <= half_cell` proximity rule, it is
    never called membership, and a point it shows is NOT thereby a member."""
    from minegen.export.scene_manifest import (
        MASK_OREBODY_INTERSECTION_BELOW_TERRAIN,
        cells_intersect_orebody,
        slice_mask,
    )
    from minegen.world.synthetic_world import generate_world

    sc = small_scenario(with_fault=False)
    w = generate_world(sc)
    ob, grid = w.orebody, w.fields.grid
    half_cell = 0.5 * max(grid.spacing)

    # the name never claims membership, and a shown cell does not make its
    # sample point a member: this is the distinction the hotfix is about
    assert "MEMBERSHIP" not in MASK_OREBODY_INTERSECTION_BELOW_TERRAIN
    near = ob.center + (ob.half_thickness + half_cell * 0.9) * ob.w
    assert bool(cells_intersect_orebody(grid, near[None, :], ob)[0])  # cell overlaps
    assert not bool(ob.contains(near[None, :])[0])  # the POINT is not a member

    # centre inside is always shown; beyond the cell half-diagonal never is
    assert bool(cells_intersect_orebody(grid, ob.center[None, :], ob)[0])
    beyond = ob.center + (ob.half_thickness + grid.cell_half_diagonal + 1.0) * ob.w
    assert ob.signed_distance(beyond[None, :])[0] > grid.cell_half_diagonal
    assert not bool(cells_intersect_orebody(grid, beyond[None, :], ob)[0])
    assert not bool(cells_intersect_orebody(grid, (ob.center + 500.0 * ob.w)[None, :], ob)[0])

    k = int(np.argmin(np.abs(grid.axis_centers(2) - ob.center[2])))
    mask, semantics = slice_mask(w, "grade", "z", k)
    assert semantics == MASK_OREBODY_INTERSECTION_BELOW_TERRAIN
    pts = grid.plane_centers(2, k)
    supported = w.fields.supported[:, :, k].ravel()
    assert 0 < mask.sum() < 0.5 * mask.size  # a band, not the whole lattice
    assert np.all(supported[mask])  # never shows an above-ground cell

    # the predicate really changed: it is not the old proximity rule
    proximity = (ob.signed_distance(pts) <= half_cell) & supported
    assert not np.array_equal(mask, proximity)

    # every shown cell genuinely reaches the solid, verified independently
    # with a much denser sub-sample than the production 3³ pattern
    dense = grid.cell_subsample_offsets(7)
    probes = (pts[mask][:, None, :] + dense[None, :, :]).reshape(-1, 3)
    hits = ob.contains(probes).reshape(int(mask.sum()), dense.shape[0])
    assert np.all(hits.any(axis=1))
    # and nothing outside the necessary bound is ever shown
    assert np.all(ob.signed_distance(pts[mask]) <= grid.cell_half_diagonal)
