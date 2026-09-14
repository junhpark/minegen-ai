"""World generation + persistence.

    data/scenarios/{id}/arrays.npz         spatial field arrays + lattice + terrain
                                           (``field_artifact_version`` stamped)
    data/scenarios/{id}/derived/world.json stats snapshot

Generated worlds are cached in memory per scenario id so slice requests do
not reload the NPZ every time. An ``arrays.npz`` that is not a current field
artifact (e.g. a Phase-17 BlockModel NPZ) is never loaded: it raises the
typed :class:`WorldArtifactIncompatibleError` (409 WORLD_ARTIFACT_INCOMPATIBLE)
until the world is regenerated.

AC-01F commit 3 — the scenario / world snapshot protocol (A2). A world object
alone says nothing about WHICH document it was built from, so every read binds
the two by their rule-60 stat identity (:func:`minegen.core.revision.file_revision`)
and every write re-checks that identity before it publishes:

* :meth:`WorldService._bound_scenario` is the ONE bound document read (stat →
  ``ScenarioStore.get`` → re-stat, repeated while the revision moves): the
  Phase 18 migration-on-read (A10) is ABSORBED by the re-read instead of being
  reported as a race, and exhaustion is ``READ_SNAPSHOT_CHANGED``;
* :meth:`WorldService.load_bound` returns ``(scenario, world,
  scenario_revision, arrays_revision)``; the in-memory cache entry carries the
  two revisions and is served ONLY while both still match, so a warm world can
  never answer for a replaced document or a deleted ``arrays.npz``, and an
  ``arrays.npz`` that vanishes or moves under the cold load is a TYPED
  outcome (``WORLD_NOT_GENERATED`` / ``READ_SNAPSHOT_CHANGED``), never a 500;
* :meth:`WorldService.scene` binds its ONE lock-held artifact observation to
  that pair (``expect_scenario_revision`` / ``expect_arrays_revision``) and
  retries a bounded number of times, then answers ``READ_SNAPSHOT_CHANGED``
  (A9) — never ``JOB_INPUTS_CHANGED``, which is a GENERATION whose inputs moved;
* :meth:`WorldService.generate` binds the scenario revision the same way, runs
  ``generate_world`` OUTSIDE the lock and refuses to publish a world for a
  document that moved underneath it (``JOB_INPUTS_CHANGED`` — a GENERATION
  whose inputs really did move);
* :meth:`WorldService.replace_scenario` makes the document write and the
  derived-state invalidation ONE locked section (rule 40).

``generate_world``, ``np.load``, ``build_orebody`` and ``world.stats`` NEVER
run inside the store lock: the protocol is optimistic (stat → expensive work
outside the lock → ``with lock:`` re-stat and publish), and the lock holds the
two writes and the cache publish only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

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
from minegen.core.models import Scenario, ScenarioCreate
from minegen.core.publication import publish_npz, publish_text
from minegen.core.revision import file_revision
from minegen.export.scene_manifest import (
    SliceAxis,
    SliceField,
    build_scene,
    slice_payload,
)
from minegen.services.artifact_errors import (
    ReadSnapshotChangedError,
    SceneArtifactInvalidError,
    StaleInputsError,
    WorldNotGeneratedError,
    read_state_code,
)
from minegen.services.artifact_reader import READ_SPECS, ArtifactReader, ArtifactSnapshot
from minegen.services.effective_ramp import resolve_effective_ramp
from minegen.services.scenario_service import ScenarioNotFoundError, ScenarioStore
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

#: how many times a bound read re-acquires its snapshot before it gives up.
#: A mutation storm on ONE scenario then answers 409 ``READ_SNAPSHOT_CHANGED``
#: (A9) — nothing was generated and nothing was discarded, so it is never
#: ``JOB_INPUTS_CHANGED``.
SNAPSHOT_ATTEMPTS: Final[int] = 3


@dataclass(frozen=True)
class _BoundWorld:
    """A cached world AND the two file revisions it was built from. The entry
    is served only while BOTH still match on disk, so the cache can never
    outlive the document or the ``arrays.npz`` it describes (Stage A R3d, and
    probe 2 §4.9's warm-cache-without-arrays 200)."""

    world: SyntheticWorld
    scenario_revision: str
    arrays_revision: str

    def bound_to(self, scenario_revision: str, arrays_revision: str) -> bool:
        return (self.scenario_revision, self.arrays_revision) == (
            scenario_revision,
            arrays_revision,
        )


class WorldService:
    def __init__(self, store: ScenarioStore) -> None:
        self.store = store
        self._cache: dict[str, _BoundWorld] = {}
        #: AC-01F: the ONE validated read authority over ``derived/``; the
        #: scene never parses an artifact file itself (rule 40 — routers
        #: obtain the SERVICE through a dependency, the reader is internal)
        self._reader = ArtifactReader(store)

    # -- generation -------------------------------------------------------- #

    def generate(self, scenario_id: str) -> dict[str, Any]:
        """Generate and publish the world, with the rule-60 capture / re-check
        protocol applied to the world writer (AC-01F A2).

        The document is read through :meth:`_bound_scenario` (C4), so the
        captured revision is the one the returned ``Scenario`` was parsed from
        even when the A10 migration-on-read rewrote it; the expensive
        ``generate_world`` runs OUTSIDE the store lock; and the publish
        (``_save`` + cache) happens under the lock only if ``scenario.json``
        has not moved since. A scenario PUT landing during generation used to
        leave ``arrays.npz``, ``derived/world.json`` and the cache holding a
        world built for the REPLACED document, with ``GET …/world`` answering
        200 (Stage A §7.5 case A); it now fails the generation closed with
        ``StaleInputsError`` → 409 ``JOB_INPUTS_CHANGED`` and persists nothing.

        That re-check stays ``StaleInputsError`` and is now only ever TRUE: a
        document that moved after the binding really is a mutation a third
        party made while this generation ran, never this process's own
        migration."""
        scenario_path = self.store.scenario_path(scenario_id)
        scenario, scenario_revision = self._bound_scenario(scenario_id)
        self.invalidate(scenario_id)  # rule 46: downstream derived products are stale
        world = generate_world(scenario)  # OUTSIDE the lock (rule: no build under it)
        # ``world.stats`` walks the whole lattice (measured: 0.099 s on
        # WARPED-301) and needs nothing but the two objects in hand, so it is
        # computed BEFORE the lock and handed to ``_save`` — the lock holds
        # the two writes and the cache publish and nothing else
        stats = world.stats(scenario)
        with self.store.lock(scenario_id):
            if file_revision(scenario_path) != scenario_revision:
                raise StaleInputsError(scenario_id)
            self._save(scenario, world, stats)
            arrays_revision = file_revision(self.store.arrays_path(scenario_id))
            if arrays_revision is None:  # pragma: no cover - ``_save`` just wrote it
                # never an ``assert``: ``python -O`` strips one, and a cache
                # entry with no arrays revision is exactly the unbound world
                # this commit exists to make impossible
                raise RuntimeError(
                    f"arrays.npz of scenario '{scenario_id}' vanished between its write "
                    "and its stat; nothing was published"
                )
            self._cache[scenario_id] = _BoundWorld(world, scenario_revision, arrays_revision)
        return stats

    def _save(self, scenario: Scenario, world: SyntheticWorld, stats: dict[str, Any]) -> None:
        """Publish ``arrays.npz`` and ``derived/world.json``. Called under the
        store lock, so it does the two WRITES and nothing else: ``stats`` is
        computed by the caller beforehand (measured on WARPED-301: the whole
        ``_save`` is 0.747 s wall for a 10,245,989-byte ``arrays.npz``, of
        which ``world.stats`` was 0.099 s — now outside the lock).

        AC-01F.2 D1/D3: both files are published atomically
        (``minegen.core.publication``), ``arrays.npz`` FIRST — it is the file
        the world guard stats, while ``derived/world.json`` is read by no
        consumer — so a crash between the two atomic replacements leaves a
        world whose arrays are whole and whose stats snapshot is one
        generation behind, never a half-written NPZ."""
        path = self.store.arrays_path(scenario.id)
        fields: dict[str, Any] = dict(world.fields.to_npz_fields())
        fields["terrain_z"] = world.terrain.z
        fields["terrain_meta"] = np.array(
            [world.terrain.x0, world.terrain.y0, world.terrain.spacing], dtype=np.float64
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        publish_npz(path, **fields)
        derived = self.store.derived_dir(scenario.id)
        derived.mkdir(parents=True, exist_ok=True)
        publish_text(derived / "world.json", json.dumps(stats, indent=2))

    # -- access ------------------------------------------------------------ #

    def _bound_scenario(self, scenario_id: str) -> tuple[Scenario, str]:
        """The scenario document AND the ``scenario.json`` revision it was
        parsed from — the ONE bound document read of this service (C4).

        ``stat`` → ``ScenarioStore.get`` → ``stat`` again, repeated while the
        revision moves, at most :data:`SNAPSHOT_ATTEMPTS` times::

            revision = file_revision(scenario.json)
            scenario = store.get(sid)          # 404 / 422 / the A10 migration
            file_revision(scenario.json) == revision ?  →  bound
                                                        else repeat

        Both halves matter. Capturing only BEFORE the read makes the A10
        migration-on-read (``ScenarioStore.get`` rewrites a schemaVersion-1
        document from inside the read — the ONE documented read that writes)
        look like a concurrent mutation, which is how the intermediate
        commit-3 draft turned the FIRST ``POST …/world/generate`` on a legacy
        document into a 409 ``JOB_INPUTS_CHANGED`` when nothing had raced.
        Capturing only AFTER would leave the document read itself outside the
        guarded window: a PUT between ``get`` and the stat would bind an OLD
        document to the NEW revision (the Stage A R3d class of defect).
        Re-reading absorbs the migration — the second attempt parses the
        migrated document and its revision holds — without the read ever
        performing a repair of its own (A10 is unchanged).

        Exhaustion is ``ReadSnapshotChangedError`` (409
        ``READ_SNAPSHOT_CHANGED``, A9): this is a READ that could not be
        bound, never ``StaleInputsError`` / ``JOB_INPUTS_CHANGED``, which is a
        GENERATION whose inputs moved.

        A ``None`` first stat (the document did not exist when it was stat'ed
        but ``get`` found one) is handled by the same repetition: only
        ``ScenarioStore.create`` writes a fresh id and a client cannot name
        one before it is created, so no API route can reach that branch — it
        is closed by construction rather than by a special case."""
        path = self.store.scenario_path(scenario_id)
        for _attempt in range(SNAPSHOT_ATTEMPTS):
            revision = file_revision(path)
            scenario = self.store.get(scenario_id)
            if revision is not None and file_revision(path) == revision:
                return scenario, revision
        raise ReadSnapshotChangedError(scenario_id, "scenario.json kept changing during the read")

    def load_bound(self, scenario_id: str) -> tuple[Scenario, SyntheticWorld, str, str]:
        """The scenario document, its world, and the two file revisions BOTH
        were taken at — the binding every AC-01F read carries.

        Optimistic protocol, with no expensive work under the store lock::

            _bound_scenario      →  (scenario, srev)   stat / get / re-stat,
                                                       so the A10 migration is
                                                       absorbed, not reported
                                                       as a race (C4)
            stat arrays.npz      →  np.load + build_orebody   OUTSIDE the lock
            with lock:              cache probe, then re-stat BOTH inputs;
                                    the triple (world, srev, arev) is returned
                                    AND cached only if neither moved — a moved
                                    input is ``ReadSnapshotChangedError``, and
                                    the two halves are symmetric (Stage D B1:
                                    the scenario re-stat used to gate the CACHE
                                    only while the ``return`` was
                                    unconditional, so ``GET …/world`` and
                                    ``GET …/world/slice`` still served an OLD
                                    document beside a NEW world — the R3d class
                                    this protocol claims to close)

        The cache entry carries its two revisions, so a warm world is served
        only while the document and the arrays it was built from are still the
        ones on disk. That is what makes ``GET …/world`` and ``GET …/scene``
        DISK-authoritative: Stage A measured a warm cache answering 200 for a
        world whose ``arrays.npz`` had been deleted (probe 2 §4.9) and a scene
        mixing an OLD document's bounding box with a NEW world's terrain
        (R3d); both are now a cache MISS, not a repair.

        The cold-load window (arrays stat → lock/cache probe → ``np.load``) is
        where ``arrays.npz`` can go away under the reader, and BOTH outcomes
        are typed rather than an exception escaping as a 500:

        ABSENT
            ``np.load`` raises ``FileNotFoundError`` → ``WorldNotGeneratedError``
            (409 ``WORLD_NOT_GENERATED``). MEASURED before this change, with
            the load paused and a real scenario PUT landing in the pause:
            ``GET …/world`` answered **500 Internal Server Error**.
        MOVED
            the file was regenerated, so the world in hand cannot be attested
            to the captured revision → ``ReadSnapshotChangedError`` (409
            ``READ_SNAPSHOT_CHANGED``). ``GET …/scene`` retries the whole bound
            load and normally answers a consistent 200; ``GET …/world`` and
            ``GET …/world/slice`` take no artifact snapshot and answer the 409.

        The SCENARIO document has exactly the same MOVED outcome (Stage D B1).
        A scenario PUT + world regeneration that lands between the bound
        document read and the cold ``np.load`` leaves this call holding a world
        built from the NEW ``arrays.npz`` beside the OLD document, and the
        orebody of the returned triple comes from that document — MEASURED at
        commit 3 before the fix, with the pause after ``_bound_scenario``:
        ``GET …/world`` answered **200** with ``orebody.center [40, 20, -50]``
        (OLD document) beside ``terrain.zMax 116.367159085105`` and
        ``rockQuality.mean 64.97196970309594`` (NEW world) — a body equal to
        neither the before nor the after state. It is the 409 now.
        """
        scenario_path = self.store.scenario_path(scenario_id)
        arrays_path = self.store.arrays_path(scenario_id)
        scenario, scenario_revision = self._bound_scenario(scenario_id)
        arrays_revision = file_revision(arrays_path)
        if arrays_revision is None:
            raise WorldNotGeneratedError(scenario_id)
        with self.store.lock(scenario_id):
            cached = self._cache.get(scenario_id)
            if cached is not None and cached.bound_to(scenario_revision, arrays_revision):
                return scenario, cached.world, scenario_revision, arrays_revision
        try:
            world = self._read_arrays(scenario, arrays_path)  # OUTSIDE the lock
        except FileNotFoundError as exc:
            # deleted between the stat and the open (a scenario PUT, a world
            # regeneration): "there is no world" is the honest answer
            raise WorldNotGeneratedError(scenario_id) from exc
        with self.store.lock(scenario_id):
            if file_revision(arrays_path) != arrays_revision:
                raise ReadSnapshotChangedError(scenario_id, "arrays.npz changed during the read")
            if file_revision(scenario_path) != scenario_revision:
                raise ReadSnapshotChangedError(scenario_id, "scenario.json changed during the read")
            self._cache[scenario_id] = _BoundWorld(world, scenario_revision, arrays_revision)
        return scenario, world, scenario_revision, arrays_revision

    def load(self, scenario_id: str) -> tuple[Scenario, SyntheticWorld]:
        """:meth:`load_bound` without the binding — the unchanged signature
        every engineering consumer (stats, slice, every ``DesignService``
        builder) still calls."""
        scenario, world, _scenario_revision, _arrays_revision = self.load_bound(scenario_id)
        return scenario, world

    def _read_arrays(self, scenario: Scenario, path: Path) -> SyntheticWorld:
        """Rebuild the world from ``arrays.npz``. NEVER called under the store
        lock: ``np.load`` plus ``build_orebody`` (a WARPED_VEIN derived lattice
        is seconds) is exactly the expensive reconstruction the protocol keeps
        outside it."""
        with np.load(path) as npz:
            try:
                fields = SpatialFieldSet.from_npz(npz)
            except IncompatibleFieldArtifactError as exc:
                raise WorldArtifactIncompatibleError(str(exc)) from exc
            tz = np.asarray(npz["terrain_z"])
            tm = npz["terrain_meta"]
        terrain = Terrain(x0=float(tm[0]), y0=float(tm[1]), spacing=float(tm[2]), z=tz)
        return SyntheticWorld(
            terrain=terrain,
            orebody=build_orebody(scenario.orebody),
            faults=[FaultPlane.from_config(f) for f in scenario.geology.faults],
            fields=fields,
        )

    def stats(self, scenario_id: str) -> dict[str, Any]:
        scenario, world = self.load(scenario_id)
        return world.stats(scenario)

    def _bound_snapshot(
        self, scenario_id: str
    ) -> tuple[Scenario, SyntheticWorld, ArtifactSnapshot]:
        """``load_bound`` + the ONE lock-held observation of every registered
        derived file, BOUND to the scenario / arrays revisions of that load.

        The observation is the read's linearization point: inside the lock the
        reader re-stats ``scenario.json`` and ``arrays.npz`` and captures every
        derived file's stat + bytes; if either input moved between the load and
        that instant there is no single moment at which the whole response was
        true, so the snapshot is discarded and the load is repeated. After
        :data:`SNAPSHOT_ATTEMPTS` attempts the read gives up with
        ``ReadSnapshotChangedError`` (409 ``READ_SNAPSHOT_CHANGED``, A9) —
        never ``StaleInputsError`` / ``JOB_INPUTS_CHANGED``, which mean a
        GENERATION whose inputs moved.

        The world guard is ``load_bound``'s: ``arrays.npz`` absent → 409
        ``WORLD_NOT_GENERATED``, from the disk and not from the cache. Parsing,
        validation and assembly all run outside the lock.

        The retry covers ``load_bound`` as well as the observation, because
        ``load_bound`` raises the same ``ReadSnapshotChangedError`` when either
        of its inputs MOVES under the cold load — ``arrays.npz`` replaced
        between its stat and ``np.load``, or (Stage D B1, the symmetric half)
        ``scenario.json`` replaced between the bound document read and the
        publish re-check: a world regenerated while the scene was loading is a
        retryable miss, not a refusal."""
        attempt = 0
        while True:
            attempt += 1
            try:
                scenario, world, scenario_revision, arrays_revision = self.load_bound(scenario_id)
                snapshot = self._reader.snapshot(
                    scenario_id,
                    expect_scenario_revision=scenario_revision,
                    expect_arrays_revision=arrays_revision,
                )
            except ReadSnapshotChangedError:
                if attempt >= SNAPSHOT_ATTEMPTS:
                    raise
                continue
            return scenario, world, snapshot

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
        observation — never a third probe (Stage A R4).

        Commit 3 adds the scenario / world half of the same guarantee: the
        snapshot is BOUND to the revisions ``load_bound`` observed, so the
        response can never describe a world the scenario document has moved
        away from (R3d) or one a PUT has already deleted (R3b)."""
        scenario, world, snapshot = self._bound_snapshot(scenario_id)
        scene = build_scene(scenario, world)
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

    def replace_scenario(self, scenario_id: str, payload: ScenarioCreate) -> Scenario:
        """Replace the scenario document AND discard every derived product in
        ONE locked section (AC-01F A2; rule 40's single choke point).

        ``api/scenarios.py`` used to run ``store.replace`` and
        ``world.invalidate`` as two separate critical sections, so between
        them the persisted document was the NEW one while ``arrays.npz``,
        ``derived/`` and the world cache were still the OLD one — the window
        Stage A R3b/R3d read through. The two halves are one mutation here.

        ``ScenarioStore.lock`` is an ``RLock`` and BOTH re-entry paths inside
        this section are real, not theoretical:

        * ``self.invalidate`` takes the same lock, and ``clear_derived`` takes
          it again inside that (three nested acquisitions of one lock);
        * ``self.store.replace`` calls ``ScenarioStore.get`` for the existing
          id, and a schemaVersion-1 document sends that read down the A10
          migration branch, which takes the lock for its rewrite +
          ``clear_derived``.

        A plain ``Lock`` here would therefore self-deadlock on an ordinary
        PUT over a legacy document. This lives on the service, not in the
        router: the router keeps taking its collaborators from FastAPI
        dependencies (rule 40) and acquires no lock of its own, and
        ``ScenarioStore.replace`` stays the plain document write it has always
        been."""
        if not self.store.scenario_path(scenario_id).is_file():
            # 404 BEFORE the lock: ``ScenarioStore.lock`` creates a permanent
            # per-id RLock, so an unknown client-supplied id must not grow
            # ``_locks`` (a benign TOCTOU only for the 404 branch of a fresh
            # id no client can name yet).
            raise ScenarioNotFoundError(scenario_id)
        with self.store.lock(scenario_id):
            updated = self.store.replace(scenario_id, payload)
            self.invalidate(scenario_id)
        return updated
