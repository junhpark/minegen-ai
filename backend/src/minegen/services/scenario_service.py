"""On-disk scenario store (CLAUDE.md "Persistence").

data/scenarios/{scenario_id}/
    scenario.json
    arrays.npz      (written by later phases)
    derived/        (written by later phases)
"""

from __future__ import annotations

import json
from pathlib import Path

from minegen.core.models import Scenario, ScenarioCreate, ScenarioSummary


class ScenarioNotFoundError(KeyError):
    pass


class ScenarioStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    # -- paths ------------------------------------------------------------- #

    def scenario_dir(self, scenario_id: str) -> Path:
        return self.root / scenario_id

    def scenario_path(self, scenario_id: str) -> Path:
        return self.scenario_dir(scenario_id) / "scenario.json"

    def arrays_path(self, scenario_id: str) -> Path:
        return self.scenario_dir(scenario_id) / "arrays.npz"

    def derived_dir(self, scenario_id: str) -> Path:
        return self.scenario_dir(scenario_id) / "derived"

    # -- CRUD -------------------------------------------------------------- #

    def create(self, payload: ScenarioCreate) -> Scenario:
        scenario = Scenario(**payload.model_dump())
        self._write(scenario)
        return scenario

    def get(self, scenario_id: str) -> Scenario:
        path = self.scenario_path(scenario_id)
        if not path.is_file():
            raise ScenarioNotFoundError(scenario_id)
        return Scenario.model_validate_json(path.read_text(encoding="utf-8"))

    def replace(self, scenario_id: str, payload: ScenarioCreate) -> Scenario:
        existing = self.get(scenario_id)
        scenario = Scenario(
            **payload.model_dump(), id=existing.id, schema_version=existing.schema_version
        )
        self._write(scenario)
        return scenario

    def list(self) -> list[ScenarioSummary]:
        summaries: list[ScenarioSummary] = []
        for d in sorted(self.root.iterdir()):
            p = d / "scenario.json"
            if p.is_file():
                s = Scenario.model_validate_json(p.read_text(encoding="utf-8"))
                summaries.append(ScenarioSummary(id=s.id, name=s.name, seed=s.seed))
        return summaries

    def delete(self, scenario_id: str) -> None:
        d = self.scenario_dir(scenario_id)
        if not d.is_dir():
            raise ScenarioNotFoundError(scenario_id)
        for p in sorted(d.rglob("*"), reverse=True):
            p.unlink() if p.is_file() else p.rmdir()
        d.rmdir()

    # -- internals --------------------------------------------------------- #

    def _write(self, scenario: Scenario) -> None:
        d = self.scenario_dir(scenario.id)
        d.mkdir(parents=True, exist_ok=True)
        self.derived_dir(scenario.id).mkdir(exist_ok=True)
        data = scenario.model_dump(mode="json", by_alias=True)
        self.scenario_path(scenario.id).write_text(
            json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
        )
