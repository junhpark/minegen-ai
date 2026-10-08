"""On-disk scenario store (CLAUDE.md "Persistence").

data/scenarios/{scenario_id}/
    scenario.json
    arrays.npz      (written by later phases)
    derived/        (written by later phases)

Documents are migrated to the current schema version on first read
(``services/scenario_migration.py``); a migrated scenario loses ALL derived
state, because artifacts written under the old semantics must never be
consumed under the new ones (rules 40/46, Phase 18).

Hardening PR-2 H4 — baked demos. The store may carry a second, READ-ONLY
root (``demo_root``, ``data/demos/{id}/`` written only by
``scripts/bake_demos.py``). A scenario id that no saved scenario carries is
resolved there IN PLACE — the demo's ``scenario.json``, ``arrays.npz``,
``derived/*``, ``economics.json`` are read exactly where they were baked, so
every revision-bound artifact keeps its binding (no copy, no re-stat) — and
every write to it (replace, delete, derived clearing, derived generation,
economics, results) is the typed 409 ``DEMO_READ_ONLY``. ``list`` names saved
scenarios only; demos are listed by ``GET /demos``.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from minegen.core.models import SCENARIO_SCHEMA_VERSION, Scenario, ScenarioCreate, ScenarioSummary
from minegen.core.publication import publish_text
from minegen.core.revision import file_revision
from minegen.services.artifact_errors import ReadSnapshotChangedError
from minegen.services.scenario_migration import migrate_scenario_document


class ScenarioNotFoundError(KeyError):
    pass


class DemoReadOnlyError(Exception):
    """A write aimed at a baked demo (hardening PR-2 H4). Demos are opened in
    place and never modified; "Clone to edit" creates a saved scenario from
    the demo document instead."""

    code = "DEMO_READ_ONLY"
    http_status = 409

    def __init__(self, scenario_id: str, action: str = "write") -> None:
        self.scenario_id = scenario_id
        self.action = action
        super().__init__(
            f"scenario '{scenario_id}' is a read-only demo; {action} is refused — "
            "clone the demo to a saved scenario to edit it"
        )


#: bounded retries of the stat / get / re-stat document binding
BOUND_READ_ATTEMPTS = 3


class ScenarioStore:
    def __init__(self, root: Path, demo_root: Path | None = None) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        #: the baked read-only demos (never created here; absent → no demos)
        self.demo_root = demo_root
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()

    # -- paths ------------------------------------------------------------- #

    def is_demo(self, scenario_id: str) -> bool:
        """True when ``scenario_id`` resolves to a baked demo: no saved scenario
        carries the id and ``demo_root/{id}/scenario.json`` exists. A saved
        scenario always wins, so a clone can never be shadowed by a demo."""
        if self.demo_root is None or (self.root / scenario_id).exists():
            return False
        return (self.demo_root / scenario_id / "scenario.json").is_file()

    def scenario_dir(self, scenario_id: str) -> Path:
        if self.demo_root is not None and self.is_demo(scenario_id):
            return self.demo_root / scenario_id
        return self.root / scenario_id

    def assert_writable(self, scenario_id: str, action: str = "write") -> None:
        """Every mutation of a scenario's files passes here (rule precedent:
        READ ≠ TRUST at the write boundary too)."""
        if self.is_demo(scenario_id):
            raise DemoReadOnlyError(scenario_id, action)

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

    def create(self, payload: ScenarioCreate, scenario_id: str | None = None) -> Scenario:
        """Persist a new scenario. ``scenario_id`` is for the demo baker only
        (stable, human-readable demo ids); the API always mints the id."""
        scenario = (
            Scenario(**payload.model_dump())
            if scenario_id is None
            else Scenario(**payload.model_dump(), id=scenario_id)
        )
        if scenario_id is not None and self.scenario_path(scenario.id).exists():
            raise FileExistsError(f"scenario '{scenario.id}' already exists")
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
        # a demo is never migrated in place (it would be a write): re-bake it
        self.assert_writable(scenario_id, f"schema migration from version {version}")
        # legacy (or newer) document: migrate explicitly, persist the migrated
        # document and drop every derived artifact written under old semantics
        with self.lock(scenario_id):
            scenario, _notes = migrate_scenario_document(raw)
            self._write(scenario)
            self.clear_derived(scenario_id)
        return scenario

    def get_bound(self, scenario_id: str) -> tuple[Scenario, str]:
        """The scenario document AND the ``scenario.json`` revision it was
        parsed from — the ONE bound document read (AC-01F C4, shared by
        ``WorldService`` and ``AnalysisService``; PR #48 review blocker).

        ``stat`` → :meth:`get` → ``stat`` again, repeated while the revision
        moves, at most :data:`BOUND_READ_ATTEMPTS` times::

            revision = file_revision(scenario.json)
            scenario = store.get(sid)          # 404 / 422 / the A10 migration
            file_revision(scenario.json) == revision ?  →  bound
                                                        else repeat

        Both halves matter: capturing only BEFORE the read makes the A10
        migration-on-read look like a concurrent mutation; capturing only
        AFTER leaves the read itself outside the guarded window — a PUT
        between ``get`` and the stat would bind an OLD document to the NEW
        revision. Exhaustion is ``ReadSnapshotChangedError`` (409
        ``READ_SNAPSHOT_CHANGED``): a READ that could not be bound, never a
        generation whose inputs moved. A consumer that then takes an
        ``ArtifactReader`` snapshot passes the returned revision as
        ``expect_scenario_revision`` so the document and the artifact
        observation are one revision."""
        path = self.scenario_path(scenario_id)
        for _attempt in range(BOUND_READ_ATTEMPTS):
            revision = file_revision(path)
            scenario = self.get(scenario_id)
            if revision is not None and file_revision(path) == revision:
                return scenario, revision
        raise ReadSnapshotChangedError(scenario_id, "scenario.json kept changing during the read")

    def replace(self, scenario_id: str, payload: ScenarioCreate) -> Scenario:
        self.assert_writable(scenario_id, "replacing the scenario document")
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
        self.assert_writable(scenario_id, "deletion")
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
        self.assert_writable(scenario_id, "clearing derived state")
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
        publish_text(self.scenario_path(scenario.id), json.dumps(data, indent=2, sort_keys=True))
