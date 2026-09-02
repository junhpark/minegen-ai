"""Phase 18 persisted-schema migration: v1 ``blockModel`` documents become
v2 ``fieldSampling`` documents deterministically, every derived artifact of
a migrated scenario is discarded, newer documents fail typed."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from minegen.core.models import SCENARIO_SCHEMA_VERSION, Scenario, ScenarioCreate
from minegen.services.scenario_migration import (
    UnsupportedSchemaVersionError,
    migrate_scenario_document,
)
from minegen.services.scenario_service import ScenarioStore
from minegen.services.world_service import WorldArtifactIncompatibleError, WorldService
from minegen.world.synthetic_world import generate_world
from tests.conftest import small_scenario


def _legacy_document(spacing: float = 5.0) -> dict:  # type: ignore[type-arg]
    """A Phase-17 scenario.json as it exists on disk today."""
    doc = small_scenario().model_dump(mode="json", by_alias=True)
    doc.pop("fieldSampling")
    doc["blockModel"] = {"dx": spacing, "dy": spacing, "dz": spacing}
    doc["schemaVersion"] = 1
    return doc


def _write_legacy(store: ScenarioStore, sid: str, doc: dict) -> Path:  # type: ignore[type-arg]
    d = store.scenario_dir(sid)
    (d / "derived").mkdir(parents=True, exist_ok=True)
    (d / "scenario.json").write_text(json.dumps(doc), encoding="utf-8")
    return d


def test_document_migration_maps_block_model_to_field_sampling() -> None:
    doc = _legacy_document(spacing=5.0)
    scenario, notes = migrate_scenario_document(doc)
    assert scenario.schema_version == 2 == SCENARIO_SCHEMA_VERSION
    assert scenario.field_sampling.as_tuple() == (5.0, 5.0, 5.0)
    assert any("blockModel" in n for n in notes)
    dumped = scenario.model_dump(mode="json", by_alias=True)
    assert "blockModel" not in dumped and dumped["fieldSampling"]["spacingX"] == 5.0
    # already-current documents pass through untouched
    again, notes2 = migrate_scenario_document(dumped)
    assert again == scenario and notes2 == []


def test_store_migrates_on_read_and_discards_derived_artifacts(store: ScenarioStore) -> None:
    sid = "legacy01"
    doc = _legacy_document(spacing=5.0)
    doc["id"] = sid
    d = _write_legacy(store, sid, doc)
    (d / "arrays.npz").write_bytes(b"not a field artifact")
    (d / "derived" / "targets.json").write_text("{}", encoding="utf-8")
    (d / "derived" / "decline.json").write_text("{}", encoding="utf-8")

    scenario = store.get(sid)
    assert scenario.id == sid and scenario.schema_version == 2
    assert scenario.field_sampling.as_tuple() == (5.0, 5.0, 5.0)
    persisted = json.loads(store.scenario_path(sid).read_text(encoding="utf-8"))
    assert persisted["schemaVersion"] == 2
    assert "blockModel" not in persisted and persisted["fieldSampling"]["spacingZ"] == 5.0
    # old-semantics artifacts are gone; regeneration is required
    assert not store.arrays_path(sid).exists()
    assert list(store.derived_dir(sid).iterdir()) == []
    # the migrated document generates a world at the migrated spacing
    world = generate_world(scenario)
    assert world.fields.grid.spacing == (5.0, 5.0, 5.0)
    # a second read is a plain load (no re-migration)
    assert store.get(sid) == scenario
    assert [s.id for s in store.list()] == [sid]


def test_replace_keeps_the_migrated_schema_version(store: ScenarioStore) -> None:
    sid = "legacy02"
    doc = _legacy_document()
    doc["id"] = sid
    _write_legacy(store, sid, doc)
    store.get(sid)
    replaced = store.replace(sid, ScenarioCreate(name="renamed"))
    assert replaced.schema_version == 2 and replaced.name == "renamed"


def test_api_boundary_accepts_legacy_block_model_and_persists_field_sampling(
    client: TestClient, store: ScenarioStore
) -> None:
    body = small_scenario().model_dump(mode="json", by_alias=True, exclude={"id", "schema_version"})
    body.pop("fieldSampling")
    body["blockModel"] = {"dx": 20.0, "dy": 20.0, "dz": 10.0}
    r = client.post("/api/v1/scenarios", json=body)
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["schemaVersion"] == 2
    assert created["fieldSampling"] == {"spacingX": 20.0, "spacingY": 20.0, "spacingZ": 10.0}
    assert "blockModel" not in created
    on_disk = json.loads(store.scenario_path(created["id"]).read_text(encoding="utf-8"))
    assert "blockModel" not in on_disk and on_disk["fieldSampling"]["spacingX"] == 20.0


def test_both_keys_present_is_rejected() -> None:
    body = small_scenario().model_dump(mode="json", by_alias=True)
    body["blockModel"] = {"dx": 10.0, "dy": 10.0, "dz": 10.0}
    with pytest.raises(ValidationError):
        Scenario.model_validate(body)


def test_newer_schema_version_fails_typed(store: ScenarioStore, client: TestClient) -> None:
    sid = "future01"
    doc = small_scenario().model_dump(mode="json", by_alias=True)
    doc["id"] = sid
    doc["schemaVersion"] = SCENARIO_SCHEMA_VERSION + 1
    _write_legacy(store, sid, doc)
    with pytest.raises(UnsupportedSchemaVersionError):
        store.get(sid)
    r = client.get(f"/api/v1/scenarios/{sid}")
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "SCENARIO_SCHEMA_UNSUPPORTED"


def test_legacy_arrays_beside_a_current_document_fail_typed_until_regenerated(
    client: TestClient, store: ScenarioStore, world_service: WorldService
) -> None:
    """Defence in depth: even a v2 document must never load a Phase-17 NPZ."""
    payload = small_scenario().model_dump(by_alias=True, exclude={"id", "schema_version"})
    sid = client.post("/api/v1/scenarios", json=payload).json()["id"]
    assert client.post(f"/api/v1/scenarios/{sid}/world/generate").status_code == 200
    shape = (4, 4, 3)
    np.savez_compressed(
        store.arrays_path(sid),
        rock_type=np.ones(shape, dtype=np.uint8),
        ore_fraction=np.zeros(shape, dtype=np.float32),
        grid_origin=np.zeros(3),
        grid_spacing=np.full(3, 10.0),
        grid_shape=np.array(shape, dtype=np.float64),
        terrain_z=np.zeros((5, 5)),
        terrain_meta=np.array([0.0, 0.0, 10.0]),
    )
    fresh = WorldService(store)
    with pytest.raises(WorldArtifactIncompatibleError):
        fresh.load(sid)
    world_service._cache.clear()  # the API instance must hit the disk too
    for path in (f"/api/v1/scenarios/{sid}/world", f"/api/v1/scenarios/{sid}/scene"):
        r = client.get(path)
        assert r.status_code == 409, path
        assert r.json()["detail"]["code"] == "WORLD_ARTIFACT_INCOMPATIBLE", path
    # every design entry point loads the world through the same typed gate
    r = client.post(f"/api/v1/scenarios/{sid}/design/targets")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "WORLD_ARTIFACT_INCOMPATIBLE"
    assert client.post(f"/api/v1/scenarios/{sid}/world/generate").status_code == 200
    assert client.get(f"/api/v1/scenarios/{sid}/world").status_code == 200
