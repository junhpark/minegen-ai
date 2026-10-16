"""PR #54 review B1 — automatic demo materialization: the missing demos are
baked in place (background at startup, synchronously by dev-setup), the
index is published per recipe, a failed recipe is reported and never stops
the others, the catalogue carries the state, and the baker's own in-process
application / the test suite never autobake."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from minegen.config import Settings
from minegen.core.enums import MiningMethodType, ScenarioPreset
from minegen.demos.bake import DemoBaker, DemoRecipe
from minegen.main import create_app
from minegen.services.demo_materializer import DemoMaterializer
from minegen.services.demo_service import DEMO_INDEX_FILE, DemoService, read_demo_index
from minegen.services.scenario_service import ScenarioStore
from tests.test_demos_api import QUICK, Stack, _small_document

SECOND = DemoRecipe(
    id="demo-quick-levels",
    title="Quick demo (world only)",
    description="second small recipe for the materializer tests",
    preset=ScenarioPreset.BASELINE,
    # the catalogue checks the index seed against the baked document, and the
    # small test document is seed 42 whatever the recipe says
    seed=42,
    fault_count=1,
    method=MiningMethodType.LONGHOLE_OPEN_STOPING,
    stages=("WORLD",),
    name="quick-2",
)


def _materializer(root: Path, recipes: tuple[DemoRecipe, ...], **kw: Any) -> DemoMaterializer:
    return DemoMaterializer(
        root / "demos",
        root / "scenarios",
        recipes=recipes,
        document=_small_document,
        commit="materializer-test",
        **kw,
    )


def test_the_suite_never_autobakes() -> None:
    """``tests/__init__.py`` turns the startup bake off before the settings
    cache is built: no test can bake into the real ``data/demos``."""
    assert os.environ.get("MINEGEN_DEMOS_AUTOBAKE") == "0"
    assert Settings().demos_autobake is False


def test_start_bakes_the_missing_recipes_and_publishes_each(tmp_path: Path) -> None:
    m = _materializer(tmp_path, (SECOND, QUICK))
    assert m.state().status == "IDLE"
    assert [r.id for r in m.missing()] == [SECOND.id, QUICK.id]
    assert m.start() is True
    assert m.state().status == "BAKING"
    m.join(900)
    state = m.state()
    assert state.status == "DONE", state
    assert state.completed_recipes == [SECOND.id, QUICK.id]
    assert state.failed_recipes == {} and state.pending_recipes == []
    assert state.recipe_id is None and state.stage is None
    index = read_demo_index(tmp_path / "demos")
    assert index is not None and [d.id for d in index.demos] == [SECOND.id, QUICK.id]
    assert index.baked_from_commit == "materializer-test"
    # the catalogue lists both as available — baked in place, stat identity intact
    store = ScenarioStore(tmp_path / "scenarios", demo_root=tmp_path / "demos")
    catalog = DemoService(store, tmp_path / "demos").catalog()
    assert catalog.status == "AVAILABLE"
    assert [(d.id, d.available) for d in catalog.demos] == [(SECOND.id, True), (QUICK.id, True)]
    # a second process finds nothing missing: no thread, DONE at once
    again = _materializer(tmp_path, (SECOND, QUICK))
    assert again.missing() == []
    assert again.start() is False
    assert again.state().status == "DONE"
    # the synchronous form (dev-setup) agrees and bakes nothing
    assert again.bake_missing().status == "DONE"


def test_a_failed_recipe_is_reported_and_the_others_still_bake(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = DemoBaker.bake

    def bake(self: DemoBaker, recipe: DemoRecipe, **kw: Any) -> Any:
        if recipe.id == SECOND.id:
            raise RuntimeError("synthetic bake failure")
        return original(self, recipe, **kw)

    monkeypatch.setattr(DemoBaker, "bake", bake)
    m = _materializer(tmp_path, (SECOND, QUICK))
    logged: list[str] = []
    state = m.bake_missing(log=logged.append)
    assert state.status == "FAILED"
    assert state.completed_recipes == [QUICK.id]
    assert state.failed_recipes == {SECOND.id: "RuntimeError: synthetic bake failure"}
    assert any(line.startswith(f"{SECOND.id}: FAILED") for line in logged)
    index = read_demo_index(tmp_path / "demos")
    assert index is not None and [d.id for d in index.demos] == [QUICK.id]
    # the next materializer re-attempts ONLY the failed one
    assert [r.id for r in _materializer(tmp_path, (SECOND, QUICK)).missing()] == [SECOND.id]


def test_a_malformed_index_is_rebuilt_from_the_demos_baked(tmp_path: Path) -> None:
    demos = tmp_path / "demos"
    demos.mkdir(parents=True)
    (demos / DEMO_INDEX_FILE).write_text("{not json", encoding="utf-8")
    m = _materializer(tmp_path, (QUICK,))
    assert [r.id for r in m.missing()] == [QUICK.id]
    assert m.bake_missing().status == "DONE"
    index = read_demo_index(demos)
    assert index is not None and [d.id for d in index.demos] == [QUICK.id]


def test_disabled_materializer_never_starts(tmp_path: Path) -> None:
    m = _materializer(tmp_path, (QUICK,), enabled=False)
    assert m.state().status == "DISABLED"
    assert m.start() is False
    assert m.state().status == "DISABLED"
    assert not (tmp_path / "demos" / DEMO_INDEX_FILE).exists()


class _Recorder(DemoMaterializer):
    """A materializer that records ``start`` calls instead of baking."""

    def __init__(self) -> None:
        super().__init__(Path("/nonexistent/demos"), Path("/nonexistent/scenarios"), recipes=())
        self.starts = 0
        self.thread_names: list[str] = []

    def start(self) -> bool:
        self.starts += 1
        self.thread_names.append(threading.current_thread().name)
        return False


def test_the_application_lifespan_starts_the_materializer_only_when_enabled() -> None:
    enabled = _Recorder()
    with TestClient(create_app(autobake=True, materializer=enabled)):
        pass
    assert enabled.starts == 1
    disabled = _Recorder()
    with TestClient(create_app(autobake=False, materializer=disabled)):
        pass
    assert disabled.starts == 0
    # the settings default decides when nothing explicit is passed: off in
    # the suite (tests/__init__.py), so the real data directory is never touched
    default = _Recorder()
    with TestClient(create_app(materializer=default)):
        pass
    assert default.starts == 0


def test_the_catalogue_reports_the_materialization_state(tmp_path: Path) -> None:
    stack = Stack(tmp_path)
    try:
        m = _materializer(tmp_path, (QUICK,))
        stack.client.app.dependency_overrides[  # type: ignore[attr-defined]
            __import__("minegen.api.deps", fromlist=["get_demo_service"]).get_demo_service
        ] = lambda: DemoService(stack.store, stack.demos_dir, state_provider=m.state)
        r = stack.client.get("/api/v1/demos")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "NOT_BAKED"
        assert body["materialization"] == {
            "status": "IDLE",
            "recipeId": None,
            "stage": None,
            "pendingRecipes": [],
            "completedRecipes": [],
            "failedRecipes": {},
        }
        assert m.start() is True
        r = stack.client.get("/api/v1/demos")
        assert r.json()["materialization"]["status"] in ("BAKING", "DONE")
        m.join(900)
        r = stack.client.get("/api/v1/demos")
        assert r.json()["status"] == "AVAILABLE"
        assert r.json()["materialization"]["status"] == "DONE"
        assert r.json()["materialization"]["completedRecipes"] == [QUICK.id]
        assert [d["available"] for d in r.json()["demos"]] == [True]
    finally:
        stack.close()
