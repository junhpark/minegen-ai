"""Baked demo catalogue (hardening PR-2 H4).

``data/demos/index.json`` is written ONLY by ``scripts/bake_demos.py`` (through
``minegen.demos.bake``) and lists the demo mines baked into
``data/demos/{id}/`` — complete scenario directories (document, world arrays,
derived artifacts, planning-economics assumptions) that the scenario store
resolves in place and never writes (``ScenarioStore.demo_root``).

READ ≠ TRUST: the index is validated on every read (a malformed index is the
typed 409 ``DEMO_INDEX_MALFORMED``, never a bare 500), and every entry is
checked against the directory it names — a missing or disagreeing demo is
reported ``available = false`` with its reason, never silently dropped and
never served. Every demo is labelled DEMO / SYNTHETIC: a synthetic sandbox
mine, never a measured, estimated or imported one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

from minegen.core.models import ApiModel
from minegen.services.scenario_service import ScenarioStore

DEMO_INDEX_FILE = "index.json"
DEMO_INDEX_VERSION = 1
DEMO_LABELS: tuple[str, ...] = ("DEMO", "SYNTHETIC")


class DemoIndexMalformedError(Exception):
    code = "DEMO_INDEX_MALFORMED"
    http_status = 409

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"{DEMO_INDEX_FILE} is malformed: {reason}")


class DemoEntry(ApiModel):
    """One baked demo as the index declares it."""

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9\-]{0,63}$")
    title: str
    description: str
    orebody_type: str
    mining_method: str
    preset: str
    seed: int
    fault_count: int | None = None
    #: the workflow stages the bake completed, in order (presentation only)
    stages: list[str]
    labels: list[str] = Field(default_factory=lambda: list(DEMO_LABELS))


class DemoIndex(ApiModel):
    version: Literal[1]
    baked_from_commit: str
    demos: list[DemoEntry]


class DemoCatalogEntry(DemoEntry):
    available: bool
    reason: str | None = None


class DemoCatalog(ApiModel):
    status: Literal["AVAILABLE", "NOT_BAKED"]
    reason: str | None
    baked_from_commit: str | None
    demos: list[DemoCatalogEntry]
    notice: str


DEMO_NOTICE = (
    "Demo mines are baked synthetic examples (DEMO / SYNTHETIC). They open "
    "read-only; clone a demo to a saved scenario to edit or regenerate it."
)


def read_demo_index(demos_dir: Path) -> DemoIndex | None:
    """The validated index, or ``None`` when no demos were baked."""
    path = demos_dir / DEMO_INDEX_FILE
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DemoIndexMalformedError(f"invalid JSON ({type(exc).__name__})") from exc
    try:
        index = DemoIndex.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first.get("loc", ())) or "<root>"
        raise DemoIndexMalformedError(f"{loc}: {first.get('msg', 'invalid')}") from exc
    ids = [d.id for d in index.demos]
    if len(set(ids)) != len(ids):
        raise DemoIndexMalformedError("duplicate demo id")
    return index


class DemoService:
    def __init__(self, store: ScenarioStore, demos_dir: Path) -> None:
        self.store = store
        self.demos_dir = demos_dir

    def catalog(self) -> DemoCatalog:
        index = read_demo_index(self.demos_dir)
        if index is None:
            return DemoCatalog(
                status="NOT_BAKED",
                reason=(
                    f"no baked demos: {self.demos_dir.name}/{DEMO_INDEX_FILE} does not exist "
                    "(run scripts/bake_demos.py)"
                ),
                baked_from_commit=None,
                demos=[],
                notice=DEMO_NOTICE,
            )
        entries = [self._check(entry) for entry in index.demos]
        return DemoCatalog(
            status="AVAILABLE",
            reason=None,
            baked_from_commit=index.baked_from_commit,
            demos=entries,
            notice=DEMO_NOTICE,
        )

    def _check(self, entry: DemoEntry) -> DemoCatalogEntry:
        """READ ≠ TRUST: the directory the entry names must hold a readable
        scenario that agrees with the entry (id, seed, orebody type, method)."""
        base = entry.model_dump(by_alias=False)
        if not self.store.is_demo(entry.id):
            saved = (self.store.root / entry.id).exists()
            reason = (
                f"a saved scenario shadows demo '{entry.id}'"
                if saved
                else f"demo directory '{entry.id}' has no scenario.json"
            )
            return DemoCatalogEntry(**base, available=False, reason=reason)
        try:
            scenario = self.store.get(entry.id)
        except Exception as exc:  # malformed document: reported, never raised
            return DemoCatalogEntry(
                **base, available=False, reason=f"scenario.json unreadable ({type(exc).__name__})"
            )
        problems: list[str] = []
        if scenario.seed != entry.seed:
            problems.append(f"seed {scenario.seed} != index {entry.seed}")
        if scenario.orebody.orebody_type.value != entry.orebody_type:
            problems.append(f"orebodyType {scenario.orebody.orebody_type.value} != index")
        if scenario.mining.method.value != entry.mining_method:
            problems.append(f"miningMethod {scenario.mining.method.value} != index")
        if not self.store.arrays_path(entry.id).is_file():
            problems.append("arrays.npz missing (world not baked)")
        if problems:
            return DemoCatalogEntry(**base, available=False, reason="; ".join(problems))
        return DemoCatalogEntry(**base, available=True, reason=None)
