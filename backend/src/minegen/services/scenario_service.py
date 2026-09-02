"""On-disk scenario store (CLAUDE.md "Persistence").

data/scenarios/{scenario_id}/
    scenario.json
    arrays.npz      (written by later phases)
    derived/        (written by later phases)

Documents are migrated to the current schema version on first read
(``services/scenario_migration.py``); a migrated scenario loses ALL derived
state, because artifacts written under the old semantics must never be
consumed under the new ones (rules 40/46, Phase 18).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from minegen.core.models import SCENARIO_SCHEMA_VERSION, Scenario, ScenarioCreate, ScenarioSummary
from minegen.services.scenario_migration import migrate_scenario_document


class ScenarioNotFoundError(KeyError):
    pass


class ScenarioStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()

    # -- paths ------------------------------------------------------------- #

    def scenario_dir(self, scenario_id: str) -> Path:
        return self.root / scenario_id

    def lock(self, scenario_id: str) -> threading.RLock:
        """Per-scenario re-entrant lock. Derived-state invalidation (deleting
        arrays.npz / derived/*) and derived-artifact persistence (fingerprint
        check + write) must be mutually exclusive, or a finishing background
        job could resurrect a file the mutation just deleted (rules 40/46/60)."""
        with self._locks_guard:
            return self._locks.setdefault(scenario_id, threading.RLock())

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
        raw = json.loads(path.read_text(encoding="utf-8"))
        version = int(raw.get("schemaVersion", raw.get("schema_version", 1)))
        if version == SCENARIO_SCHEMA_VERSION:
            return Scenario.model_validate(raw)
        # legacy (or newer) document: migrate explicitly, persist the migrated
        # document and drop every derived artifact written under old semantics
        with self.lock(scenario_id):
            scenario, _notes = migrate_scenario_document(raw)
            self._write(scenario)
            self.clear_derived(scenario_id)
        return scenario

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
            if (d / "scenario.json").is_file():
                s = self.get(d.name)
                summaries.append(ScenarioSummary(id=s.id, name=s.name, seed=s.seed))
        return summaries

    def delete(self, scenario_id: str) -> None:
        d = self.scenario_dir(scenario_id)
        if not d.is_dir():
            raise ScenarioNotFoundError(scenario_id)
        for p in sorted(d.rglob("*"), reverse=True):
            p.unlink() if p.is_file() else p.rmdir()
        d.rmdir()

    # -- derived state ----------------------------------------------------- #

    def clear_derived(self, scenario_id: str) -> None:
        """Delete ``arrays.npz`` and every file under ``derived/`` (the
        directory itself is kept). Callers that hold in-memory caches drop
        them separately (``WorldService.invalidate``)."""
        with self.lock(scenario_id):
            arrays = self.arrays_path(scenario_id)
            if arrays.exists():
                arrays.unlink()
            derived = self.derived_dir(scenario_id)
            if derived.is_dir():
                for p in sorted(derived.rglob("*"), reverse=True):
                    if p.is_file():
                        p.unlink()
                    else:
                        p.rmdir()
            derived.mkdir(parents=True, exist_ok=True)

    # -- internals --------------------------------------------------------- #

    def _write(self, scenario: Scenario) -> None:
        d = self.scenario_dir(scenario.id)
        d.mkdir(parents=True, exist_ok=True)
        self.derived_dir(scenario.id).mkdir(exist_ok=True)
        data = scenario.model_dump(mode="json", by_alias=True)
        self.scenario_path(scenario.id).write_text(
            json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
        )
