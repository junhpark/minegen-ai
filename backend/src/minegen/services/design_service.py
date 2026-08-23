"""Phase 03 design services: cost evaluator construction, access-target
generation and persistence (``derived/targets.json``).

Evaluators are cached per scenario and dropped whenever the world is
invalidated (the world service owns that lifecycle)."""

from __future__ import annotations

import json
from typing import Any

import numpy as np

from minegen.core.models import Scenario
from minegen.design.cost_field import DesignCostEvaluator
from minegen.design.mine_designer import ChainedDeclineGenerator
from minegen.design.progress import ProgressCallback, no_progress
from minegen.design.targets import AccessTargetSet, generate_access_targets, resolve_portal
from minegen.services.scenario_service import ScenarioStore
from minegen.services.world_service import WorldService
from minegen.world.synthetic_world import SyntheticWorld


class TargetsNotGeneratedError(LookupError):
    pass


class DeclineNotGeneratedError(LookupError):
    pass


class DesignService:
    def __init__(self, store: ScenarioStore, worlds: WorldService) -> None:
        self.store = store
        self.worlds = worlds
        self._evaluators: dict[str, tuple[SyntheticWorld, DesignCostEvaluator]] = {}
        self._targets: dict[str, AccessTargetSet] = {}

    # -- evaluator --------------------------------------------------------- #

    def evaluator(self, scenario_id: str) -> tuple[Scenario, SyntheticWorld, DesignCostEvaluator]:
        scenario, world = self.worlds.load(scenario_id)
        cached = self._evaluators.get(scenario_id)
        if cached is not None and cached[0] is world:
            return scenario, world, cached[1]
        ev = DesignCostEvaluator(world, scenario.design)
        self._evaluators[scenario_id] = (world, ev)
        return scenario, world, ev

    def evaluate(self, scenario_id: str, points: list[list[float]]) -> dict[str, Any]:
        _, _, ev = self.evaluator(scenario_id)
        res = ev.evaluate_points(np.asarray(points, dtype=np.float64))
        return {"count": len(res), "results": res.to_payload()}

    # -- targets ----------------------------------------------------------- #

    def targets_path(self, scenario_id: str) -> Any:
        return self.store.derived_dir(scenario_id) / "targets.json"

    def generate_targets(self, scenario_id: str) -> dict[str, Any]:
        scenario, world, ev = self.evaluator(scenario_id)
        portal, generated = resolve_portal(scenario, world)
        targets: AccessTargetSet = generate_access_targets(
            world,
            scenario.design,
            scenario.ramp,
            scenario.mining.sublevel_interval,
            ev,
            portal,
            generated,
        )
        payload = targets.to_dict()
        path = self.targets_path(scenario_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._targets[scenario_id] = targets
        decline = self.decline_path(scenario_id)
        if decline.exists():
            decline.unlink()  # rule 46: a decline built on old targets is stale
        return payload

    # -- decline (Phase 04) ------------------------------------------------ #

    def decline_path(self, scenario_id: str) -> Any:
        return self.store.derived_dir(scenario_id) / "decline.json"

    def _targets_object(self, scenario_id: str) -> AccessTargetSet:
        cached = self._targets.get(scenario_id)
        if cached is not None and self.targets_path(scenario_id).is_file():
            return cached
        if not self.targets_path(scenario_id).is_file():
            raise TargetsNotGeneratedError(scenario_id)
        # targets.json exists from an earlier process: rebuild deterministically
        scenario, world, ev = self.evaluator(scenario_id)
        portal, generated = resolve_portal(scenario, world)
        targets = generate_access_targets(
            world,
            scenario.design,
            scenario.ramp,
            scenario.mining.sublevel_interval,
            ev,
            portal,
            generated,
        )
        self._targets[scenario_id] = targets
        return targets

    def generate_decline(
        self,
        scenario_id: str,
        max_levels: int | None = None,
        on_progress: ProgressCallback = no_progress,
    ) -> dict[str, Any]:
        scenario, _, ev = self.evaluator(scenario_id)
        targets = self._targets_object(scenario_id)
        gen = ChainedDeclineGenerator(ev, scenario.ramp, scenario.design.search)
        result = gen.generate(targets, max_levels=max_levels, on_progress=on_progress)
        payload = result.to_dict()
        path = self.decline_path(scenario_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return payload

    def decline(self, scenario_id: str) -> dict[str, Any]:
        self.store.get(scenario_id)
        if not self.worlds.is_generated(scenario_id):
            from minegen.services.world_service import WorldNotGeneratedError

            raise WorldNotGeneratedError(scenario_id)
        path = self.decline_path(scenario_id)
        if not path.is_file():
            raise DeclineNotGeneratedError(scenario_id)
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data

    def targets(self, scenario_id: str) -> dict[str, Any]:
        self.store.get(scenario_id)  # raises ScenarioNotFoundError
        if not self.worlds.is_generated(scenario_id):
            from minegen.services.world_service import WorldNotGeneratedError

            raise WorldNotGeneratedError(scenario_id)
        path = self.targets_path(scenario_id)
        if not path.is_file():
            raise TargetsNotGeneratedError(scenario_id)
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data

    def targets_if_present(self, scenario_id: str) -> dict[str, Any] | None:
        path = self.targets_path(scenario_id)
        if not path.is_file():
            return None
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data
