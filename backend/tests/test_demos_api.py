"""Hardening PR-2 H4 — baked demos: the catalogue (READ ≠ TRUST), in-place
read-only resolution through the scenario store, the one write guard on every
scenario-scoped router, and "Clone to edit" as an ordinary saved scenario."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from minegen.api.demo_guard import READ_ONLY_POST_PREFIXES, is_read_only_post
from minegen.api.deps import (
    get_adapter_service,
    get_analysis_service,
    get_demo_service,
    get_design_service,
    get_exchange_service,
    get_infrastructure_service,
    get_job_service,
    get_result_service,
    get_scenario_store,
    get_world_service,
)
from minegen.core.enums import MiningMethodType, ScenarioPreset
from minegen.core.models import ScenarioCreate
from minegen.demos.bake import (
    DEMO_ECONOMICS,
    DEMO_RECIPES,
    STAGE_ORDER,
    DemoBaker,
    DemoRecipe,
    realize_recipe,
    write_index,
)
from minegen.main import create_app
from minegen.services.adapter_service import AdapterService
from minegen.services.analysis_service import AnalysisService
from minegen.services.demo_service import DEMO_INDEX_FILE, DemoService, read_demo_index
from minegen.services.design_service import DesignService
from minegen.services.exchange_service import ExchangeService
from minegen.services.infrastructure_service import InfrastructureService
from minegen.services.job_service import JobService
from minegen.services.result_service import ResultService
from minegen.services.scenario_service import DemoReadOnlyError, ScenarioStore
from minegen.services.world_service import WorldService
from tests.conftest import small_scenario

QUICK = DemoRecipe(
    id="demo-quick",
    title="Quick demo",
    description="small scenario for the test suite",
    preset=ScenarioPreset.BASELINE,
    seed=42,
    fault_count=1,
    method=MiningMethodType.LONGHOLE_OPEN_STOPING,
    stages=("WORLD", "LAYOUT", "LEVELS", "ECONOMICS"),
    name="quick",
)


def _small_document(_recipe: DemoRecipe) -> ScenarioCreate:
    sc = small_scenario(seed=42, with_fault=True)
    return ScenarioCreate.model_validate(sc.model_dump(exclude={"id", "schema_version"}))


class Stack:
    """The application over a saved-scenario root AND a demo root."""

    def __init__(self, root: Path) -> None:
        self.demos_dir = root / "demos"
        self.store = ScenarioStore(root / "scenarios", demo_root=self.demos_dir)
        self.worlds = WorldService(self.store)
        self.design = DesignService(self.store, self.worlds)
        self.jobs = JobService(max_workers=1)
        app = create_app()
        exchange = ExchangeService(self.store, self.worlds)
        app.dependency_overrides[get_scenario_store] = lambda: self.store
        app.dependency_overrides[get_world_service] = lambda: self.worlds
        app.dependency_overrides[get_design_service] = lambda: self.design
        app.dependency_overrides[get_infrastructure_service] = lambda: InfrastructureService(
            self.store, self.design
        )
        app.dependency_overrides[get_job_service] = lambda: self.jobs
        app.dependency_overrides[get_exchange_service] = lambda: exchange
        app.dependency_overrides[get_adapter_service] = lambda: AdapterService(exchange)
        app.dependency_overrides[get_analysis_service] = lambda: AnalysisService(self.store)
        app.dependency_overrides[get_result_service] = lambda: ResultService(self.store, exchange)
        app.dependency_overrides[get_demo_service] = lambda: DemoService(self.store, self.demos_dir)
        self.client = TestClient(app)
        self.client.__enter__()

    def close(self) -> None:
        self.client.__exit__(None, None, None)
        self.jobs.shutdown()


def _tree_state(root: Path) -> dict[str, tuple[int, int, str]]:
    return {
        str(p.relative_to(root)): (
            p.stat().st_size,
            p.stat().st_mtime_ns,
            hashlib.sha256(p.read_bytes()).hexdigest(),
        )
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@pytest.fixture(scope="module")
def baked(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Stack]:
    root = tmp_path_factory.mktemp("demos")
    baker = DemoBaker(root / "demos")
    try:
        entry = baker.bake(QUICK, document=_small_document)
        write_index(root / "demos", [entry], "testsha")
    finally:
        baker.close()
    stack = Stack(root)
    yield stack
    stack.close()


# --------------------------------------------------------------------------- #
# recipes and the baker
# --------------------------------------------------------------------------- #


def test_recipes_are_the_three_h4_demos_in_stage_order() -> None:
    assert [r.id for r in DEMO_RECIPES] == [
        "demo-tabular-longhole",
        "demo-tabular-cut-fill",
        "demo-warped-vein",
    ]
    by_id = {r.id: r for r in DEMO_RECIPES}
    assert by_id["demo-tabular-longhole"].method is MiningMethodType.LONGHOLE_OPEN_STOPING
    assert by_id["demo-tabular-cut-fill"].method is MiningMethodType.CUT_AND_FILL
    assert by_id["demo-warped-vein"].preset is ScenarioPreset.RANDOM_WARPED_VEIN
    assert by_id["demo-warped-vein"].stages == ("WORLD", "LAYOUT", "LEVELS", "EXCAVATION")
    for r in DEMO_RECIPES:
        assert set(r.stages) <= set(STAGE_ORDER)
        assert r.labels == ("DEMO", "SYNTHETIC")
    # out-of-order or inconsistent recipes fail at construction
    with pytest.raises(ValueError):
        DemoRecipe(
            id="x",
            title="",
            description="",
            preset=ScenarioPreset.BASELINE,
            seed=1,
            fault_count=1,
            method=MiningMethodType.LONGHOLE_OPEN_STOPING,
            stages=("LAYOUT", "WORLD"),
        )
    with pytest.raises(ValueError):
        DemoRecipe(
            id="x",
            title="",
            description="",
            preset=ScenarioPreset.BASELINE,
            seed=1,
            fault_count=1,
            method=MiningMethodType.LONGHOLE_OPEN_STOPING,
            stages=("WORLD", "SHAFTS"),
        )


def test_realize_recipe_is_the_rule_119_realization_with_the_method_and_shaft() -> None:
    doc = realize_recipe(DEMO_RECIPES[1])
    assert doc.mining.method is MiningMethodType.CUT_AND_FILL
    assert doc.name == "Demo — Tabular Cut & Fill"
    assert doc.shafts.specs == []
    again = realize_recipe(DEMO_RECIPES[1])
    assert again.model_dump() == doc.model_dump()  # deterministic
    longhole = realize_recipe(DEMO_RECIPES[0])
    assert len(longhole.shafts.specs) == 1 and longhole.seed == 1
    assert DEMO_ECONOMICS["grossRevenuePerMinedTonne"] == 120.0


def test_the_bake_writes_a_complete_demo_directory_and_a_valid_index(baked: Stack) -> None:
    demo = baked.demos_dir / QUICK.id
    assert (demo / "scenario.json").is_file() and (demo / "arrays.npz").is_file()
    assert (demo / "derived" / "layout_v2.json").is_file()
    assert (demo / "derived" / "levels.json").is_file()
    assert (demo / "economics.json").is_file()
    index = read_demo_index(baked.demos_dir)
    assert index is not None and index.baked_from_commit == "testsha"
    assert [d.id for d in index.demos] == [QUICK.id]
    assert index.demos[0].stages == ["WORLD", "LAYOUT", "LEVELS", "ECONOMICS"]
    assert index.demos[0].labels == ["DEMO", "SYNTHETIC"]
    raw = json.loads((baked.demos_dir / DEMO_INDEX_FILE).read_text())
    assert "generatedAt" not in raw and "timestamp" not in json.dumps(raw)


# --------------------------------------------------------------------------- #
# GET /demos — READ ≠ TRUST
# --------------------------------------------------------------------------- #


def test_catalogue_lists_the_baked_demo_as_available(baked: Stack) -> None:
    r = baked.client.get("/api/v1/demos")
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["status"] == "AVAILABLE" and doc["bakedFromCommit"] == "testsha"
    assert "DEMO / SYNTHETIC" in doc["notice"]
    (entry,) = doc["demos"]
    assert entry["id"] == QUICK.id and entry["available"] is True and entry["reason"] is None
    assert entry["orebodyType"] == "TABULAR" and entry["miningMethod"] == "LONGHOLE_OPEN_STOPING"
    assert entry["labels"] == ["DEMO", "SYNTHETIC"]
    # demos are not saved scenarios
    assert baked.client.get("/api/v1/scenarios").json() == []


def test_catalogue_without_an_index_is_not_baked_never_an_error(tmp_path: Path) -> None:
    stack = Stack(tmp_path)
    try:
        r = stack.client.get("/api/v1/demos")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "NOT_BAKED" and r.json()["demos"] == []
        assert "bake_demos.py" in r.json()["reason"]
    finally:
        stack.close()


def test_catalogue_reports_missing_or_disagreeing_demos_and_refuses_a_malformed_index(
    tmp_path: Path,
) -> None:
    stack = Stack(tmp_path)
    demos = stack.demos_dir
    demos.mkdir()
    try:
        # an entry whose directory is missing → available false, never dropped
        ghost = {
            "id": "demo-ghost",
            "title": "t",
            "description": "d",
            "orebodyType": "TABULAR",
            "miningMethod": "LONGHOLE_OPEN_STOPING",
            "preset": "BASELINE",
            "seed": 1,
            "faultCount": 1,
            "stages": ["WORLD"],
            "labels": ["DEMO", "SYNTHETIC"],
        }
        # an entry that disagrees with its document (seed) → available false
        demo_store = ScenarioStore(demos)
        sc = small_scenario(seed=42)
        demo_store.create(
            ScenarioCreate.model_validate(sc.model_dump(exclude={"id", "schema_version"})),
            scenario_id="demo-wrong-seed",
        )
        wrong = dict(ghost, id="demo-wrong-seed", seed=7)
        (demos / DEMO_INDEX_FILE).write_text(
            json.dumps({"version": 1, "bakedFromCommit": "x", "demos": [ghost, wrong]})
        )
        doc = stack.client.get("/api/v1/demos").json()
        assert doc["status"] == "AVAILABLE"
        by_id = {d["id"]: d for d in doc["demos"]}
        assert by_id["demo-ghost"]["available"] is False
        assert "no scenario.json" in by_id["demo-ghost"]["reason"]
        assert by_id["demo-wrong-seed"]["available"] is False
        assert "seed 42 != index 7" in by_id["demo-wrong-seed"]["reason"]
        assert "arrays.npz missing" in by_id["demo-wrong-seed"]["reason"]
        # malformed index → typed 409
        (demos / DEMO_INDEX_FILE).write_text("{not json")
        r = stack.client.get("/api/v1/demos")
        assert r.status_code == 409 and r.json()["detail"]["code"] == "DEMO_INDEX_MALFORMED"
        (demos / DEMO_INDEX_FILE).write_text(
            json.dumps({"version": 1, "bakedFromCommit": "x", "demos": [ghost, ghost]})
        )
        r = stack.client.get("/api/v1/demos")
        assert r.status_code == 409 and "duplicate" in r.json()["detail"]["message"]
        (demos / DEMO_INDEX_FILE).write_text(json.dumps({"version": 2, "demos": []}))
        r = stack.client.get("/api/v1/demos")
        assert r.status_code == 409 and r.json()["detail"]["code"] == "DEMO_INDEX_MALFORMED"
    finally:
        stack.close()


# --------------------------------------------------------------------------- #
# in-place read-only resolution + the write guard
# --------------------------------------------------------------------------- #


def test_a_copy_without_timestamps_is_reported_stale_never_served_silently(
    baked: Stack, tmp_path: Path
) -> None:
    """The world commit record binds arrays.npz to scenario.json's stat identity
    (size + mtime_ns): copying a baked demo without its timestamps makes every
    scene read 409 WORLD_PUBLICATION_STALE. The catalogue reports that up
    front (available = false with the remedy) instead of listing a demo that
    cannot open."""
    import shutil

    copied = tmp_path / "demos"
    shutil.copytree(baked.demos_dir, copied)  # copytree keeps mtimes (copy2) …
    stack = Stack(tmp_path)
    try:
        entry = stack.client.get("/api/v1/demos").json()["demos"][0]
        assert entry["available"] is True, entry
        # … a plain byte copy / git checkout does not: touch the document
        (copied / QUICK.id / "scenario.json").touch()
        entry = stack.client.get("/api/v1/demos").json()["demos"][0]
        assert entry["available"] is False
        assert "world publication stale" in entry["reason"]
        assert "cp -a" in entry["reason"]
        r = stack.client.get(f"/api/v1/scenarios/{QUICK.id}/scene")
        assert r.status_code == 409 and r.json()["detail"]["code"] == "WORLD_PUBLICATION_STALE"
    finally:
        stack.close()


def test_a_demo_is_read_in_place_through_the_ordinary_scenario_routes(baked: Stack) -> None:
    c = baked.client
    sid = QUICK.id
    assert baked.store.is_demo(sid)
    assert baked.store.scenario_dir(sid) == baked.demos_dir / sid
    r = c.get(f"/api/v1/scenarios/{sid}")
    assert r.status_code == 200 and r.json()["id"] == sid and r.json()["seed"] == 42
    scene = c.get(f"/api/v1/scenarios/{sid}/scene")
    assert scene.status_code == 200, scene.text
    assert scene.json()["levels"]["status"] == "SUCCESS"
    assert c.get(f"/api/v1/scenarios/{sid}/design/layout-v2").status_code == 200
    assert c.get(f"/api/v1/scenarios/{sid}/analysis").status_code == 200
    cfg = c.get(f"/api/v1/scenarios/{sid}/analysis/economics-config").json()
    assert cfg["configured"] is True and cfg["config"]["grossRevenuePerMinedTonne"] == 120.0
    # the read-only projections stay available on a demo
    assert c.get(f"/api/v1/scenarios/{sid}/analysis/sensitivity").status_code == 200
    assert c.get(f"/api/v1/scenarios/{sid}/design/reset-plan?from=LEVELS").status_code == 200


def test_every_write_to_a_demo_is_the_typed_409_and_touches_nothing(baked: Stack) -> None:
    c = baked.client
    sid = QUICK.id
    before = _tree_state(baked.demos_dir)
    doc = c.get(f"/api/v1/scenarios/{sid}").json()
    doc.pop("id"), doc.pop("schemaVersion")
    attempts: list[tuple[str, str, dict[str, Any]]] = [
        ("PUT", f"/api/v1/scenarios/{sid}", {"json": doc}),
        ("POST", f"/api/v1/scenarios/{sid}/world/generate", {}),
        ("POST", f"/api/v1/scenarios/{sid}/design/layout-v2", {"params": {"sync": "true"}}),
        ("POST", f"/api/v1/scenarios/{sid}/design/layout-v2", {}),
        ("POST", f"/api/v1/scenarios/{sid}/design/levels", {}),
        ("POST", f"/api/v1/scenarios/{sid}/design/tunnel", {}),
        ("POST", f"/api/v1/scenarios/{sid}/design/shafts", {}),
        ("POST", f"/api/v1/scenarios/{sid}/design/production", {}),
        ("POST", f"/api/v1/scenarios/{sid}/design/timeline", {}),
        ("POST", f"/api/v1/scenarios/{sid}/design/capability-graph", {}),
        ("PUT", f"/api/v1/scenarios/{sid}/design/ramp-source", {"json": {"source": "LEGACY"}}),
        ("DELETE", f"/api/v1/scenarios/{sid}/design/stages/LEVELS", {}),
        ("POST", f"/api/v1/scenarios/{sid}/network/generate", {}),
        ("POST", f"/api/v1/scenarios/{sid}/infrastructure/communication", {}),
        ("POST", f"/api/v1/scenarios/{sid}/infrastructure/sensors", {}),
        ("PUT", f"/api/v1/scenarios/{sid}/analysis/economics-config", {"json": DEMO_ECONOMICS}),
        ("DELETE", f"/api/v1/scenarios/{sid}/results/abc", {}),
    ]
    for method, url, kw in attempts:
        r = c.request(method, url, **kw)
        assert r.status_code == 409, (method, url, r.status_code, r.text)
        assert r.json()["detail"]["code"] == "DEMO_READ_ONLY", (method, url, r.text)
        assert "clone" in r.json()["detail"]["message"]
    assert c.get("/api/v1/jobs").json() == []  # no job was ever submitted
    assert _tree_state(baked.demos_dir) == before  # byte- and stat-identical


def test_read_only_posts_pass_the_guard(baked: Stack) -> None:
    c = baked.client
    sid = QUICK.id
    before = _tree_state(baked.demos_dir)
    assert READ_ONLY_POST_PREFIXES == (
        "/export/",
        "/analysis/what-if",
        "/design/cost/evaluate",
        "/design/shafts/suggest-collar",
    )
    assert is_read_only_post("POST", "/export/mine-exchange")
    assert not is_read_only_post("PUT", "/export/mine-exchange")
    assert not is_read_only_post("POST", "/design/levels")
    # the what-if projection answers (not a demo refusal)
    r = c.post(f"/api/v1/scenarios/{sid}/analysis/what-if", json={"grossRevenuePerMinedTonne": 1.1})
    assert r.status_code == 200, r.text
    assert r.json()["label"] == "WHAT-IF OVERRIDE — NOT SCENARIO VALUE"
    # the export is served from the demo (a world + layout + levels bundle)
    r = c.post(f"/api/v1/scenarios/{sid}/export/mine-exchange")
    assert r.status_code == 200, r.text
    assert _tree_state(baked.demos_dir) == before


def test_the_store_itself_refuses_demo_writes(baked: Stack) -> None:
    store = baked.store
    sid = QUICK.id
    with pytest.raises(DemoReadOnlyError) as e:
        store.clear_derived(sid)
    assert e.value.code == "DEMO_READ_ONLY" and e.value.http_status == 409
    with pytest.raises(DemoReadOnlyError):
        store.delete(sid)
    with pytest.raises(DemoReadOnlyError):
        store.replace(sid, ScenarioCreate(seed=1))
    assert (baked.demos_dir / sid / "derived" / "levels.json").is_file()


def test_clone_to_edit_is_an_ordinary_saved_scenario_and_shadows_nothing(baked: Stack) -> None:
    c = baked.client
    sid = QUICK.id
    doc = c.get(f"/api/v1/scenarios/{sid}").json()
    doc.pop("id"), doc.pop("schemaVersion")
    doc["name"] = f"{doc['name']} (copy)"
    r = c.post("/api/v1/scenarios", json=doc)
    assert r.status_code == 201, r.text
    clone = str(r.json()["id"])
    assert clone != sid and not baked.store.is_demo(clone)
    assert [s["id"] for s in c.get("/api/v1/scenarios").json()] == [clone]
    # the clone is writable; the demo is untouched
    before = _tree_state(baked.demos_dir)
    assert c.post(f"/api/v1/scenarios/{clone}/world/generate").status_code == 200
    assert c.get(f"/api/v1/scenarios/{clone}/scene").status_code == 200
    assert _tree_state(baked.demos_dir) == before
    # a saved scenario with the demo's id would shadow the demo: the store
    # resolves the saved one and the catalogue reports the demo unavailable
    saved_dir = baked.store.root / sid
    saved_dir.mkdir()
    try:
        assert not baked.store.is_demo(sid)
        assert baked.store.scenario_dir(sid) == saved_dir
        entry = c.get("/api/v1/demos").json()["demos"][0]
        assert entry["available"] is False and "shadows" in entry["reason"]
    finally:
        saved_dir.rmdir()
    assert baked.store.is_demo(sid)
