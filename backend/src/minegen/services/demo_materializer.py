"""Automatic demo materialization (PR #54 review B1).

The three demo mines must be there on a fresh clone — dev-setup → backend →
frontend → File › Demos lists them — without the user running
``scripts/bake_demos.py``. ``data/`` stays git-ignored and a baked demo is
bound by STAT identity (rule 60 / 222), so the demos are not shipped as
files: they are BAKED IN PLACE on the serving host, by the same
``minegen.demos.bake.DemoBaker`` the script uses, whenever the catalogue
does not list them as available —

* synchronously by ``scripts/bin/dev-setup`` (``bake_demos.py --if-missing``),
  so a prepared checkout already carries them when the servers start;
* in a background thread at backend startup (``create_app`` lifespan,
  ``MINEGEN_DEMOS_AUTOBAKE``, default on; off in the test suite, the browser
  e2e and the baker's own in-process application) for a backend started
  without that step — Docker, a plain ``uvicorn``.

The materializer runs ONCE per process (no retry loop), bakes only the
recipes the catalogue reports missing or unavailable, publishes the index
after EVERY recipe (a demo appears as soon as it is complete), records a
failed recipe with its reason and continues with the next, and exposes its
state through ``GET /demos`` (``materialization``) so the frontend can show
"baking…" instead of an empty menu. It never touches a saved scenario and
never weakens the stat binding: the files are written where they are served.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from minegen.services.demo_service import (
    DemoEntry,
    DemoIndexMalformedError,
    DemoService,
    MaterializationState,
    read_demo_index,
)
from minegen.services.scenario_service import ScenarioStore

if TYPE_CHECKING:
    from minegen.core.models import ScenarioCreate
    from minegen.demos.bake import DemoRecipe

#: a bake log line per stage: "<recipe id>: <STAGE>" (``DemoBaker.bake``)
LogCallback = Callable[[str], None]


def _quiet(_message: str) -> None:
    return None


class DemoMaterializer:
    """Bakes the missing demo recipes into ``demos_dir`` (see the module doc)."""

    def __init__(
        self,
        demos_dir: Path,
        scenarios_dir: Path,
        *,
        recipes: Sequence[DemoRecipe] | None = None,
        document: Callable[[DemoRecipe], ScenarioCreate] | None = None,
        commit: str | None = None,
        enabled: bool = True,
    ) -> None:
        self.demos_dir = demos_dir
        self.scenarios_dir = scenarios_dir
        self._recipes = None if recipes is None else tuple(recipes)
        self._document = document
        self._commit = commit
        self._enabled = enabled
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state = MaterializationState(status="IDLE" if enabled else "DISABLED")

    # -- what to bake ------------------------------------------------------ #

    @property
    def recipes(self) -> tuple[DemoRecipe, ...]:
        if self._recipes is not None:
            return self._recipes
        # lazy: ``demos.bake`` imports the API dependency module, which
        # constructs this materializer — a module-level import would cycle
        from minegen.demos.bake import DEMO_RECIPES

        return DEMO_RECIPES

    def missing(self) -> list[DemoRecipe]:
        """The recipes the catalogue does NOT list as available: no index, a
        malformed index, an entry whose directory is missing / shadowed /
        disagrees / stale (``DemoService.catalog`` — READ ≠ TRUST applied to
        what is already on disk, never a guess from the directory name)."""
        store = ScenarioStore(self.scenarios_dir, demo_root=self.demos_dir)
        try:
            catalog = DemoService(store, self.demos_dir).catalog()
            available = {d.id for d in catalog.demos if d.available}
        except DemoIndexMalformedError:
            available = set()
        return [r for r in self.recipes if r.id not in available]

    # -- state -------------------------------------------------------------- #

    def state(self) -> MaterializationState:
        with self._lock:
            return self._state.model_copy(deep=True)

    def _update(self, **changes: object) -> None:
        with self._lock:
            self._state = self._state.model_copy(update=changes)

    # -- the two entry points ---------------------------------------------- #

    def start(self) -> bool:
        """Start the background bake of the missing recipes ONCE per process.
        Returns ``True`` when a thread was started; ``False`` when the
        materializer is disabled, already started, or nothing is missing
        (then the state reads DONE at once)."""
        with self._lock:
            if not self._enabled or self._thread is not None:
                return False
            missing = self.missing()
            if not missing:
                self._state = MaterializationState(status="DONE")
                return False
            self._state = MaterializationState(
                status="BAKING", pending_recipes=[r.id for r in missing]
            )
            self._thread = threading.Thread(
                target=self._run,
                args=(missing, _quiet),
                name="minegen-demo-materializer",
                daemon=True,
            )
            self._thread.start()
            return True

    def bake_missing(self, log: LogCallback = _quiet) -> MaterializationState:
        """The SYNCHRONOUS form (``scripts/bake_demos.py --if-missing``, run
        by ``scripts/bin/dev-setup``): bake what is missing now and return
        the final state."""
        missing = self.missing()
        if not missing:
            self._update(status="DONE")
            return self.state()
        with self._lock:
            self._state = MaterializationState(
                status="BAKING", pending_recipes=[r.id for r in missing]
            )
        self._run(missing, log)
        return self.state()

    def join(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    # -- the bake loop ------------------------------------------------------ #

    def _run(self, recipes: Sequence[DemoRecipe], log: LogCallback) -> None:
        import minegen
        from minegen.demos.bake import DemoBaker, git_commit, realize_recipe

        commit = self._commit or git_commit(Path(minegen.__file__).resolve().parents[2])
        document = self._document or realize_recipe
        failed: dict[str, str] = {}
        baker = DemoBaker(self.demos_dir)
        try:
            for recipe in recipes:
                with self._lock:
                    pending = [r for r in self._state.pending_recipes if r != recipe.id]
                    self._state = self._state.model_copy(
                        update={"recipe_id": recipe.id, "stage": None, "pending_recipes": pending}
                    )

                def on_log(message: str, _rid: str = recipe.id) -> None:
                    log(message)
                    stage = message.split(": ", 1)[1] if ": " in message else message
                    self._update(stage=stage)

                try:
                    entry = baker.bake(recipe, document=document, log=on_log)
                    self._publish(entry, commit)
                    with self._lock:
                        self._state = self._state.model_copy(
                            update={
                                "completed_recipes": [*self._state.completed_recipes, recipe.id]
                            }
                        )
                    log(f"{recipe.id}: baked")
                except Exception as exc:  # one failed recipe never stops the others
                    failed[recipe.id] = f"{type(exc).__name__}: {str(exc)[:300]}"
                    log(f"{recipe.id}: FAILED {failed[recipe.id]}")
                    self._update(failed_recipes=dict(failed))
        finally:
            baker.close()
            self._update(
                status="FAILED" if failed else "DONE",
                recipe_id=None,
                stage=None,
                pending_recipes=[],
            )

    def _publish(self, entry: DemoEntry, commit: str) -> None:
        """Write the index with this entry added to (or replacing) what the
        index already lists — in recipe order, unknown ids last — so a demo
        is listed the moment it is complete and a malformed index is
        rebuilt from the demos baked in this run."""
        from minegen.demos.bake import write_index

        try:
            existing = read_demo_index(self.demos_dir)
        except DemoIndexMalformedError:
            existing = None
        kept = {e.id: e for e in (existing.demos if existing else [])}
        kept[entry.id] = entry
        order = [r.id for r in self.recipes]
        entries = [kept[i] for i in order if i in kept] + [
            e for i, e in kept.items() if i not in order
        ]
        write_index(self.demos_dir, entries, commit)
