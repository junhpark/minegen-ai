"""World generation + persistence.

    data/scenarios/{id}/arrays.npz         spatial field arrays + lattice + terrain
                                           (``field_artifact_version`` stamped)
    data/scenarios/{id}/derived/world.json stats snapshot

Generated worlds are cached in memory per scenario id so slice requests do
not reload the NPZ every time. An ``arrays.npz`` that is not a current field
artifact (e.g. a Phase-17 BlockModel NPZ) is never loaded: it raises the
typed :class:`WorldArtifactIncompatibleError` (409 WORLD_ARTIFACT_INCOMPATIBLE)
until the world is regenerated.
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
from minegen.services.effective_ramp import resolve_effective_ramp
from minegen.services.scenario_service import ScenarioStore
from minegen.world.geology import FaultPlane
from minegen.world.orebody import build_orebody
from minegen.world.spatial_fields import IncompatibleFieldArtifactError, SpatialFieldSet
from minegen.world.synthetic_world import SyntheticWorld, generate_world
from minegen.world.terrain import Terrain


class WorldNotGeneratedError(LookupError):
    pass


def _layout_summary(catalogue: dict[str, Any]) -> dict[str, Any]:
    """Scene view of the layout-v2 catalogue: every candidate summary
    without its centerline / piece geometry (the selected ramp is shipped
    separately; the full catalogue is served by GET …/design/layout-v2)."""
    slim = dict(catalogue)
    slim["candidates"] = [
        {
            k: (
                [{ak: av for ak, av in a.items() if ak != "centerline"} for a in v]
                if k == "levelAccesses" and isinstance(v, list)
                else v
            )
            for k, v in c.items()
            if k not in ("centerline", "pieces")
        }
        for c in catalogue.get("candidates", [])
    ]
    return slim


class WorldArtifactIncompatibleError(WorldNotGeneratedError):
    """``arrays.npz`` exists but is not a current-version field artifact.
    Subclass of WorldNotGeneratedError so every 409 guard already applies;
    routers report the more specific code."""


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
        path = self.store.arrays_path(scenario.id)
        fields: dict[str, Any] = dict(world.fields.to_npz_fields())
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
            try:
                fields = SpatialFieldSet.from_npz(npz)
            except IncompatibleFieldArtifactError as exc:
                raise WorldArtifactIncompatibleError(str(exc)) from exc
            tz = np.asarray(npz["terrain_z"])
            tm = npz["terrain_meta"]
        terrain = Terrain(x0=float(tm[0]), y0=float(tm[1]), spacing=float(tm[2]), z=tz)
        world = SyntheticWorld(
            terrain=terrain,
            orebody=build_orebody(scenario.orebody),
            faults=[FaultPlane.from_config(f) for f in scenario.geology.faults],
            fields=fields,
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
        for key, name in (
            ("accessTargets", "targets.json"),
            ("decline", "decline.json"),
            ("smoothedDecline", "decline_smoothed.json"),
            ("tunnelMesh", "tunnel_mesh.json"),
            ("developmentMesh", "development_mesh.json"),
            ("levels", "levels.json"),
            ("network", "network.json"),
            ("stopes", "stopes.json"),
            ("timeline", "timeline.json"),
            ("communication", "communication.json"),
            ("sensors", "sensors.json"),
        ):
            path = derived / name
            scene[key] = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        # Phase 20A (rules 149–150): ``smoothedDecline`` is the ACTIVE Effective
        # Ramp — for the LEGACY source the Phase 05 artifact itself (adapter
        # view, geometry untouched); the raw legacy artifact stays available
        # as ``legacySmoothedDecline`` for the legacy pipeline status.
        ramp = resolve_effective_ramp(derived)
        scene["legacySmoothedDecline"] = scene["smoothedDecline"]
        scene["smoothedDecline"] = ramp.payload
        scene["rampSource"] = ramp.summary()
        layout_path = derived / "layout_v2.json"
        scene["layoutV2"] = (
            _layout_summary(json.loads(layout_path.read_text(encoding="utf-8")))
            if layout_path.is_file()
            else None
        )
        selected_path = derived / "layout_v2_selected.json"
        scene["layoutV2Selected"] = (
            json.loads(selected_path.read_text(encoding="utf-8"))
            if selected_path.is_file()
            else None
        )
        # Phase 20B: ramp junctions + level accesses of the selection (rule 157)
        accesses_path = derived / "level_accesses.json"
        scene["levelAccesses"] = (
            json.loads(accesses_path.read_text(encoding="utf-8"))
            if accesses_path.is_file()
            else None
        )
        return scene

    def slice(
        self, scenario_id: str, field: SliceField, axis: SliceAxis, index: int
    ) -> dict[str, Any]:
        _, world = self.load(scenario_id)
        return slice_payload(world, field, axis, index)

    def invalidate(self, scenario_id: str) -> None:
        """Discard ALL derived world state for a scenario: memory cache,
        ``arrays.npz`` and every file under ``derived/``. Called whenever the
        scenario document changes; after this, world endpoints answer
        409 WORLD_NOT_GENERATED until the world is regenerated."""
        with self.store.lock(scenario_id):
            self._cache.pop(scenario_id, None)
            self.store.clear_derived(scenario_id)

    def is_generated(self, scenario_id: str) -> bool:
        return scenario_id in self._cache or self.store.arrays_path(scenario_id).is_file()
