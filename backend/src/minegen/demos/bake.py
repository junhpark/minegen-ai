"""Demo baker (hardening PR-2 H4).

Three demo mines are baked end to end into ``data/demos/{id}/`` through the
SAME HTTP routes the guided workflow uses — a baked demo is an ordinary
scenario directory produced by the production code paths, never a second
generator. The baker opens the application against a scenario store whose
ROOT is the demos directory (so the writes land exactly where the API will
later resolve the demo read-only), drives every stage of the recipe
synchronously (``?sync=true`` on the asynchronous design routes), writes the
DEMO / SYNTHETIC planning-economics assumptions, and finally writes
``index.json`` — the catalogue ``GET /demos`` reads (``services/demo_service``).

Determinism: every recipe is preset + seed (+ fault count) through the rule
119 realization, so re-baking yields the same mine; the index carries the
commit it was baked from and no timestamp.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from minegen.api.deps import (
    get_adapter_service,
    get_analysis_service,
    get_design_service,
    get_exchange_service,
    get_infrastructure_service,
    get_job_service,
    get_result_service,
    get_scenario_store,
    get_world_service,
)
from minegen.core.enums import MiningMethodType, ScenarioPreset
from minegen.core.models import ScenarioCreate, ShaftSpec
from minegen.core.publication import publish_text
from minegen.services.adapter_service import AdapterService
from minegen.services.analysis_service import AnalysisService
from minegen.services.demo_service import (
    DEMO_INDEX_FILE,
    DEMO_INDEX_VERSION,
    DEMO_LABELS,
    DemoEntry,
    DemoIndex,
)
from minegen.services.design_service import DesignService
from minegen.services.exchange_service import ExchangeService
from minegen.services.infrastructure_service import InfrastructureService
from minegen.services.job_service import JobService
from minegen.services.result_service import ResultService
from minegen.services.scenario_realizer import realize_scenario
from minegen.services.scenario_service import ScenarioStore
from minegen.services.world_service import WorldService

#: the workflow stages a recipe may complete, in the only legal order
STAGE_ORDER: tuple[str, ...] = (
    "WORLD",
    "LAYOUT",
    "LEVELS",
    "EXCAVATION",
    "SHAFTS",
    "NETWORK",
    "CAPABILITY",
    "PRODUCTION",
    "SCHEDULE",
    "COMMUNICATION",
    "SENSORS",
    "ECONOMICS",
)

#: DEMO / SYNTHETIC planning-economics assumptions — the SAME illustrative
#: round numbers the frontend's "Use demo assumptions" button loads
#: (frontend/src/components/panels/economicsDraft.ts::DEMO_ASSUMPTIONS); a
#: planning sandbox, never a market, cost or feasibility estimate
DEMO_ECONOMICS: dict[str, Any] = {
    "version": 1,
    "currencyCode": "USD",
    "developmentCosts": {
        "rampPerM": 6000.0,
        "levelAccessPerM": 5000.0,
        "driftPerM": 4500.0,
        "crosscutPerM": 4500.0,
        "raisePerM": 5500.0,
        "shaftPerM": 25000.0,
        "shaftStationAccessPerM": 5000.0,
    },
    "productionCosts": {
        "longholeOpenStopingPerTonne": 35.0,
        "cutAndFillPerTonne": 60.0,
        "roomAndPillarPerTonne": 30.0,
    },
    "processingCostPerTonne": 25.0,
    "backfillCostPerM3": 40.0,
    "fixedOperatingCostPerDay": 20000.0,
    "grossRevenuePerMinedTonne": 120.0,
    "initialCapitalCost": 20000000.0,
    "annualDiscountRate": 0.08,
    "cashflowBucketDays": 30.0,
}


@dataclass(frozen=True)
class DemoRecipe:
    id: str
    title: str
    description: str
    preset: ScenarioPreset
    seed: int
    fault_count: int | None
    method: MiningMethodType
    stages: tuple[str, ...]
    #: one default production shaft is declared when true (stage SHAFTS)
    shaft: bool = False
    name: str = ""
    labels: tuple[str, ...] = field(default=DEMO_LABELS)

    def __post_init__(self) -> None:
        order = [STAGE_ORDER.index(s) for s in self.stages]
        if order != sorted(order) or len(set(order)) != len(order):
            raise ValueError(f"recipe {self.id}: stages out of order {self.stages}")
        if "SHAFTS" in self.stages and not self.shaft:
            raise ValueError(f"recipe {self.id}: SHAFTS stage needs shaft=True")


FULL_STAGES: tuple[str, ...] = tuple(s for s in STAGE_ORDER if s != "SHAFTS")

DEMO_RECIPES: tuple[DemoRecipe, ...] = (
    DemoRecipe(
        id="demo-tabular-longhole",
        title="Tabular orebody · Longhole Open Stoping",
        description=(
            "The baseline synthetic tabular mine: layout-v2 ramp, level accesses, "
            "footwall drifts and crosscuts, a production shaft, planned stopes, the "
            "precedence-only schedule, communication and sensor layouts and "
            "demo planning economics."
        ),
        preset=ScenarioPreset.BASELINE,
        seed=1,
        fault_count=1,
        method=MiningMethodType.LONGHOLE_OPEN_STOPING,
        stages=STAGE_ORDER,
        shaft=True,
        name="Demo — Tabular Longhole",
    ),
    DemoRecipe(
        id="demo-tabular-cut-fill",
        title="Tabular orebody · Cut & Fill",
        description=(
            "The same baseline tabular mine developed with the Cut & Fill sequence: "
            "blocks, panels, lifts and cuts with cemented sill mats, the panel-"
            "concurrent schedule, backfill records and demo planning economics."
        ),
        preset=ScenarioPreset.BASELINE,
        seed=1,
        fault_count=1,
        method=MiningMethodType.CUT_AND_FILL,
        stages=FULL_STAGES,
        name="Demo — Tabular Cut & Fill",
    ),
    DemoRecipe(
        id="demo-warped-vein",
        title="Warped vein · layout-v2 and curved level development",
        description=(
            "A deterministic synthetic irregular (WARPED_VEIN) orebody with its "
            "layout-v2 catalogue, the selected ramp and curved footwall level "
            "development on authoritative level sections. World, layout and levels "
            "only — production geometry for implicit bodies is a later phase."
        ),
        preset=ScenarioPreset.RANDOM_WARPED_VEIN,
        seed=301,
        fault_count=1,
        method=MiningMethodType.LONGHOLE_OPEN_STOPING,
        stages=("WORLD", "LAYOUT", "LEVELS", "EXCAVATION"),
        name="Demo — Warped Vein",
    ),
)


class DemoBakeError(RuntimeError):
    pass


def realize_recipe(recipe: DemoRecipe) -> ScenarioCreate:
    """The resolved scenario document of a recipe (rule 119: every stochastic
    draw happens here, once; the persisted document reproduces its world)."""
    base = realize_scenario(recipe.preset, recipe.seed, recipe.fault_count)
    doc = base.model_dump()
    doc["name"] = recipe.name or recipe.title
    doc["mining"]["method"] = recipe.method
    doc["mining"]["method_parameters"] = None
    if recipe.shaft:
        doc["shafts"]["specs"] = [ShaftSpec().model_dump()]
    return ScenarioCreate.model_validate(doc)


def git_commit(root: Path) -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    except Exception:  # pragma: no cover - git absent
        return "unknown"


class DemoBaker:
    """Bakes recipes into ``demos_dir`` through the application's own routes."""

    def __init__(self, demos_dir: Path) -> None:
        self.demos_dir = demos_dir
        self.demos_dir.mkdir(parents=True, exist_ok=True)
        # the demos directory IS the store root while baking, so every write
        # lands where the API resolves the demo later (read-only)
        self.store = ScenarioStore(self.demos_dir)
        self.worlds = WorldService(self.store)
        self.design = DesignService(self.store, self.worlds)
        self.jobs = JobService(max_workers=1)
        # imported here: ``minegen.main`` imports the API dependency module,
        # which constructs the materializer, which bakes through this class
        from minegen.main import create_app

        # the baker's own application never materializes demos itself
        app = create_app(autobake=False)
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
        self.client = TestClient(app)
        self.client.__enter__()

    def close(self) -> None:
        self.client.__exit__(None, None, None)
        self.jobs.shutdown()

    # -- one recipe --------------------------------------------------------- #

    def bake(
        self,
        recipe: DemoRecipe,
        *,
        document: Callable[[DemoRecipe], ScenarioCreate] = realize_recipe,
        log: Callable[[str], None] = lambda _m: None,
    ) -> DemoEntry:
        target = self.demos_dir / recipe.id
        if target.exists():
            shutil.rmtree(target)
        payload = document(recipe)
        scenario = self.store.create(payload, scenario_id=recipe.id)
        sid = scenario.id
        base = f"/api/v1/scenarios/{sid}"
        design = f"{base}/design"
        done: list[str] = []
        for stage in recipe.stages:
            log(f"{recipe.id}: {stage}")
            if stage == "WORLD":
                self._post(f"{base}/world/generate")
            elif stage == "LAYOUT":
                cat = self._post(f"{design}/layout-v2", params={"sync": "true"})
                if cat.get("status") != "SUCCESS" or not cat.get("winnerId"):
                    raise DemoBakeError(f"{recipe.id}: layout-v2 has no feasible winner")
                self._post(f"{design}/layout-v2/activate", json={"candidateId": cat["winnerId"]})
            elif stage == "LEVELS":
                self._post(f"{design}/levels")
            elif stage == "EXCAVATION":
                self._post(f"{design}/tunnel", params={"sync": "true"})
                self._post(f"{design}/development-mesh", params={"sync": "true"})
            elif stage == "SHAFTS":
                self._post(f"{design}/shafts")
                self._post(f"{design}/shaft-mesh")
            elif stage == "NETWORK":
                self._post(f"{base}/network/generate")
            elif stage == "CAPABILITY":
                self._post(f"{design}/capability-graph")
            elif stage == "PRODUCTION":
                self._post(f"{design}/production")
            elif stage == "SCHEDULE":
                self._post(f"{design}/timeline")
            elif stage == "COMMUNICATION":
                self._post(f"{base}/infrastructure/communication")
            elif stage == "SENSORS":
                self._post(f"{base}/infrastructure/sensors")
            elif stage == "ECONOMICS":
                r = self.client.put(f"{base}/analysis/economics-config", json=DEMO_ECONOMICS)
                if r.status_code != 200:
                    raise DemoBakeError(f"{recipe.id}: economics-config {r.status_code} {r.text}")
            else:  # pragma: no cover - guarded by DemoRecipe.__post_init__
                raise DemoBakeError(f"{recipe.id}: unknown stage {stage}")
            done.append(stage)
        return DemoEntry(
            id=recipe.id,
            title=recipe.title,
            description=recipe.description,
            orebody_type=scenario.orebody.orebody_type.value,
            mining_method=scenario.mining.method.value,
            preset=recipe.preset.value,
            seed=recipe.seed,
            fault_count=recipe.fault_count,
            stages=done,
            labels=list(recipe.labels),
        )

    def _post(self, url: str, **kw: Any) -> dict[str, Any]:
        r = self.client.post(url, **kw)
        if r.status_code != 200:
            raise DemoBakeError(f"POST {url} → {r.status_code}: {r.text[:400]}")
        doc: dict[str, Any] = r.json()
        status = doc.get("status")
        if status is not None and status not in ("SUCCESS", "AVAILABLE"):
            raise DemoBakeError(
                f"POST {url} → status {status}: {doc.get('failureReason') or doc.get('reason')}"
            )
        return doc


def write_index(demos_dir: Path, entries: Sequence[DemoEntry], commit: str) -> Path:
    index = DemoIndex(version=DEMO_INDEX_VERSION, baked_from_commit=commit, demos=list(entries))
    path = demos_dir / DEMO_INDEX_FILE
    # the WRITE authority (core/publication.py): atomic sibling + rename
    publish_text(
        path,
        json.dumps(index.model_dump(mode="json", by_alias=True), indent=2, sort_keys=True) + "\n",
    )
    return path
