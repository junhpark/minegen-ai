"""World generation + persistence.

    data/scenarios/{id}/arrays.npz         block model arrays + grid + terrain
    data/scenarios/{id}/derived/world.json stats snapshot

Generated worlds are cached in memory per scenario id so slice requests do
not reload the NPZ every time.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np

from minegen.core.models import Scenario
from minegen.export.scene_manifest import (
    SliceAxis,
    SliceField,
    build_scene,
    slice_payload,
)
from minegen.services.scenario_service import ScenarioStore
from minegen.world.block_model import BlockModel
from minegen.world.geology import FaultPlane
from minegen.world.orebody import build_orebody
from minegen.world.synthetic_world import SyntheticWorld, generate_world
from minegen.world.terrain import Terrain


class WorldNotGeneratedError(LookupError):
    pass


class WorldService:
    def __init__(self, store: ScenarioStore) -> None:
        self.store = store
        self._cache: dict[str, SyntheticWorld] = {}

    # -- generation -------------------------------------------------------- #

    def generate(self, scenario_id: str) -> dict[str, Any]:
        scenario = self.store.get(scenario_id)
        self.invalidate(scenario_id)  # rule 46: downstream derived products are stale
        world = generate_world(scenario)
        self._save(scenario, world)
        self._cache[scenario_id] = world
        return world.stats(scenario)

    def _save(self, scenario: Scenario, world: SyntheticWorld) -> None:
        bm = world.block_model
        path = self.store.arrays_path(scenario.id)
        fields: dict[str, Any] = {name: getattr(bm, name) for name in BlockModel.ARRAY_FIELDS}
        fields.update(bm.grid.to_npz_fields())
        fields["terrain_z"] = world.terrain.z
        fields["terrain_meta"] = np.array(
            [world.terrain.x0, world.terrain.y0, world.terrain.spacing], dtype=np.float64
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, **fields)
        derived = self.store.derived_dir(scenario.id)
        derived.mkdir(parents=True, exist_ok=True)
        (derived / "world.json").write_text(
            json.dumps(world.stats(scenario), indent=2), encoding="utf-8"
        )

    # -- access ------------------------------------------------------------ #

    def load(self, scenario_id: str) -> tuple[Scenario, SyntheticWorld]:
        scenario = self.store.get(scenario_id)
        cached = self._cache.get(scenario_id)
        if cached is not None:
            return scenario, cached
        path = self.store.arrays_path(scenario_id)
        if not path.is_file():
            raise WorldNotGeneratedError(scenario_id)
        with np.load(path) as npz:
            from minegen.world.voxel_grid import VoxelGrid

            grid = VoxelGrid.from_npz_fields(npz)
            data = {name: npz[name] for name in BlockModel.ARRAY_FIELDS}
            tz = np.asarray(npz["terrain_z"])
            tm = npz["terrain_meta"]
        terrain = Terrain(x0=float(tm[0]), y0=float(tm[1]), spacing=float(tm[2]), z=tz)
        world = SyntheticWorld(
            terrain=terrain,
            orebody=build_orebody(scenario.orebody),
            faults=[FaultPlane.from_config(f) for f in scenario.geology.faults],
            block_model=BlockModel(grid=grid, **data),
        )
        self._cache[scenario_id] = world
        return scenario, world

    def stats(self, scenario_id: str) -> dict[str, Any]:
        scenario, world = self.load(scenario_id)
        return world.stats(scenario)

    def scene(self, scenario_id: str) -> dict[str, Any]:
        scenario, world = self.load(scenario_id)
        scene = build_scene(scenario, world)
        derived = self.store.derived_dir(scenario_id)
        targets = derived / "targets.json"
        scene["accessTargets"] = (
            json.loads(targets.read_text(encoding="utf-8")) if targets.is_file() else None
        )
        decline = derived / "decline.json"
        scene["decline"] = (
            json.loads(decline.read_text(encoding="utf-8")) if decline.is_file() else None
        )
        smoothed = derived / "decline_smoothed.json"
        scene["smoothedDecline"] = (
            json.loads(smoothed.read_text(encoding="utf-8")) if smoothed.is_file() else None
        )
        return scene

    def slice(
        self, scenario_id: str, field: SliceField, axis: SliceAxis, index: int
    ) -> dict[str, Any]:
        _, world = self.load(scenario_id)
        return slice_payload(world.block_model, field, axis, index)

    def invalidate(self, scenario_id: str) -> None:
        """Discard ALL derived world state for a scenario: memory cache,
        ``arrays.npz`` and every file under ``derived/``. Called whenever the
        scenario document changes; after this, world endpoints answer
        409 WORLD_NOT_GENERATED until the world is regenerated."""
        with self.store.lock(scenario_id):
            self._cache.pop(scenario_id, None)
            arrays = self.store.arrays_path(scenario_id)
            if arrays.exists():
                arrays.unlink()
            derived = self.store.derived_dir(scenario_id)
            if derived.is_dir():
                for p in sorted(derived.rglob("*"), reverse=True):
                    if p.is_file():
                        p.unlink()
                    else:
                        p.rmdir()
            derived.mkdir(parents=True, exist_ok=True)

    def is_generated(self, scenario_id: str) -> bool:
        return scenario_id in self._cache or self.store.arrays_path(scenario_id).is_file()
