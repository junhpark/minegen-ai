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

from minegen.core.artifacts import (
    CAPABILITY_GRAPH_ARTIFACT,
    COMMUNICATION_ARTIFACT,
    DECLINE_ARTIFACT,
    DEVELOPMENT_MESH_ARTIFACT,
    LAYOUT_V2_ARTIFACT,
    LAYOUT_V2_SELECTED_ARTIFACT,
    LEGACY_RAMP_ARTIFACT,
    LEVEL_ACCESSES_ARTIFACT,
    LEVELS_ARTIFACT,
    NETWORK_ARTIFACT,
    SENSORS_ARTIFACT,
    SHAFTS_ARTIFACT,
    STOPES_ARTIFACT,
    TARGETS_ARTIFACT,
    TIMELINE_ARTIFACT,
    TUNNEL_MESH_ARTIFACT,
)
from minegen.core.models import Scenario
from minegen.export.scene_manifest import (
    SliceAxis,
    SliceField,
    build_scene,
    slice_payload,
)
from minegen.services.artifact_errors import (
    SceneArtifactInvalidError,
    WorldNotGeneratedError,
    read_state_code,
)
from minegen.services.artifact_reader import READ_SPECS, ArtifactReader
from minegen.services.effective_ramp import resolve_effective_ramp
from minegen.services.scenario_service import ScenarioStore
from minegen.world.geology import FaultPlane
from minegen.world.orebody import build_orebody
from minegen.world.spatial_fields import IncompatibleFieldArtifactError, SpatialFieldSet
from minegen.world.synthetic_world import SyntheticWorld, generate_world
from minegen.world.terrain import Terrain

#: AC-01F: ``WorldNotGeneratedError`` moved to
#: ``services/artifact_errors.py`` so the validated read authority can raise
#: the world guard without importing a service (no cycle); re-exported here,
#: so every existing import and every ``isinstance`` check — including
#: ``WorldArtifactIncompatibleError``'s subclassing — names this class object.
__all__ = ["WorldArtifactIncompatibleError", "WorldNotGeneratedError", "WorldService"]


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


#: the 13 scene slots the manifest projects straight from their artifact, in
#: the ORDER ``WorldService.scene`` has always written them
SCENE_SLOTS: tuple[tuple[str, str], ...] = (
    ("accessTargets", TARGETS_ARTIFACT),
    ("decline", DECLINE_ARTIFACT),
    ("smoothedDecline", LEGACY_RAMP_ARTIFACT),
    ("tunnelMesh", TUNNEL_MESH_ARTIFACT),
    ("developmentMesh", DEVELOPMENT_MESH_ARTIFACT),
    ("levels", LEVELS_ARTIFACT),
    ("shafts", SHAFTS_ARTIFACT),
    ("network", NETWORK_ARTIFACT),
    ("capabilityGraph", CAPABILITY_GRAPH_ARTIFACT),
    ("stopes", STOPES_ARTIFACT),
    ("timeline", TIMELINE_ARTIFACT),
    ("communication", COMMUNICATION_ARTIFACT),
    ("sensors", SENSORS_ARTIFACT),
)


class WorldService:
    def __init__(self, store: ScenarioStore) -> None:
        self.store = store
        self._cache: dict[str, SyntheticWorld] = {}
        #: AC-01F: the ONE validated read authority over ``derived/``; the
        #: scene never parses an artifact file itself (rule 40 — routers
        #: obtain the SERVICE through a dependency, the reader is internal)
        self._reader = ArtifactReader(store)

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
        """The scene manifest: a projection of the VALID derived artifacts of
        ONE lock-held read snapshot (AC-01F).

        ``null`` means ABSENT and nothing else. A present artifact that is
        STALE or MALFORMED is never projected, never nulled and never
        silently repaired: EVERY invalid artifact of the snapshot is collected
        and the whole scene is refused with ``SCENE_ARTIFACT_INVALID`` (A14),
        because a scene that mixes what a builder refuses with what it accepts
        is a claim the next POST contradicts.

        One observation per file per snapshot: ``legacySmoothedDecline`` and
        ``smoothedDecline`` come from the SAME parsed document, and the ramp
        summary's ``layoutV2Selected`` flag is that snapshot's presence
        observation — never a third probe (Stage A R4)."""
        scenario, world = self.load(scenario_id)
        scene = build_scene(scenario, world)
        # ONE lock hold for every registered derived file (stats + bytes);
        # parsing, validation and assembly run outside the lock
        snapshot = self._reader.snapshot(scenario_id)
        if snapshot.arrays_revision is None:
            # AC-01F C3: the same DISK-authoritative world guard every
            # ``ArtifactReader.require`` applies — a derived artifact is never
            # trusted without a world (A1). ``load`` above can still answer
            # from the in-memory cache after ``arrays.npz`` was deleted (Stage
            # A probe 2 §4.9 measured that as a literal 200); the snapshot's
            # own stat is what decides here. Commit 3 adds the revision
            # BINDING (scenario / arrays stats re-checked against the load).
            raise WorldNotGeneratedError(scenario_id)
        reads = {name: self._reader.read(snapshot, name) for name in READ_SPECS}
        failures = [
            {
                "artifact": name,
                "state": read.state,
                "code": read_state_code(read.error),
                "message": str(read.error),
            }
            for name, read in reads.items()
            if read.error is not None
        ]
        if failures:
            raise SceneArtifactInvalidError(scenario_id, failures)
        for key, name in SCENE_SLOTS:
            scene[key] = reads[name].raw
        # Phase 20A (rules 149–150): ``smoothedDecline`` is the ACTIVE Effective
        # Ramp — for the LEGACY source the Phase 05 artifact itself (adapter
        # view, geometry untouched); the raw legacy artifact stays available
        # as ``legacySmoothedDecline`` for the legacy pipeline status.
        ramp = resolve_effective_ramp(snapshot, self._reader)
        scene["legacySmoothedDecline"] = scene["smoothedDecline"]
        scene["smoothedDecline"] = ramp.payload
        scene["rampSource"] = ramp.summary()
        catalogue = reads[LAYOUT_V2_ARTIFACT].raw
        scene["layoutV2"] = _layout_summary(catalogue) if catalogue is not None else None
        scene["layoutV2Selected"] = reads[LAYOUT_V2_SELECTED_ARTIFACT].raw
        # Phase 20B: ramp junctions + level accesses of the selection (rule 157)
        scene["levelAccesses"] = reads[LEVEL_ACCESSES_ARTIFACT].raw
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
