"""MineExchange export service (Phase 23A): ONE coherent validated snapshot
→ pure projection → deterministic ZIP; nothing persisted, no derived
artifact registered. A source that moves during the export is refused
(``READ_SNAPSHOT_CHANGED``), never mixed into the bundle."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import numpy as np

from minegen.core.artifacts import (
    CAPABILITY_GRAPH_ARTIFACT,
    DEVELOPMENT_MESH_ARTIFACT,
    DEVELOPMENT_MESH_GLB,
    LEVEL_ACCESSES_ARTIFACT,
    LEVELS_ARTIFACT,
    NETWORK_ARTIFACT,
    SHAFTS_ARTIFACT,
    STOPES_ARTIFACT,
    TIMELINE_ARTIFACT,
    TUNNEL_MESH_ARTIFACT,
    TUNNEL_MESH_GLB,
)
from minegen.core.models import Scenario
from minegen.exchange.builder import (
    ArtifactInput,
    ExchangeInputs,
    assemble_centerlines,
    build_exchange,
    project_network,
)
from minegen.exchange.bundle import write_bundle
from minegen.exchange.models import ExchangeManifest, ExchangeOmission, SourceSnapshot
from minegen.results.geometry import EdgeGeometry
from minegen.services.artifact_errors import ReadSnapshotChangedError
from minegen.services.artifact_reader import (
    STATE_ABSENT,
    ArtifactRead,
    ArtifactReader,
    ArtifactSnapshot,
)
from minegen.services.effective_ramp import (
    RAMP_FILES,
    EffectiveRampResolution,
    resolve_effective_ramp,
)
from minegen.services.scenario_service import ScenarioStore
from minegen.services.world_service import WorldService
from minegen.world.synthetic_world import SyntheticWorld

#: every artifact the bundle may project from (RAMP_FILES = ramp source,
#: both ramp owners, the catalogue and the level accesses)
EXPORT_ARTIFACTS: tuple[str, ...] = tuple(
    dict.fromkeys(
        [
            *RAMP_FILES,
            LEVEL_ACCESSES_ARTIFACT,
            LEVELS_ARTIFACT,
            SHAFTS_ARTIFACT,
            NETWORK_ARTIFACT,
            CAPABILITY_GRAPH_ARTIFACT,
            TUNNEL_MESH_ARTIFACT,
            DEVELOPMENT_MESH_ARTIFACT,
            # 1.1.0 (Phase 21A): stopes are part of the coherent snapshot — a
            # stopes.json that moves during the export is READ_SNAPSHOT_CHANGED
            STOPES_ARTIFACT,
            # 1.3.0 (Phase 23B): the MineTimeline is part of the coherent snapshot
            TIMELINE_ARTIFACT,
        ]
    )
)


@dataclass(frozen=True)
class ExportResult:
    zip_bytes: bytes
    manifest: ExchangeManifest
    filename: str


@dataclass(frozen=True)
class SourceObservation:
    """ONE coherent observation of every artifact a bundle projects from —
    the snapshot, the resolved Effective Ramp and the optional reads — and
    the ``SourceSnapshot`` identity a bundle (and a Phase 23C result)
    binds to. The world is loaded only when a caller needs it."""

    snapshot: ArtifactSnapshot
    ramp: EffectiveRampResolution
    accesses: ArtifactRead | None
    levels: ArtifactRead | None
    shafts: ArtifactRead | None
    network: ArtifactRead | None
    capability: ArtifactRead | None
    stopes: ArtifactRead | None
    timeline: ArtifactRead | None
    tunnel: ArtifactRead | None
    development: ArtifactRead | None

    @property
    def source_snapshot(self) -> SourceSnapshot:
        return SourceSnapshot(
            scenario_revision=self.snapshot.scenario_revision or "",
            arrays_revision=self.snapshot.arrays_revision or "",
            active_ramp_source=self.ramp.active_source,
            artifact_revisions=dict(sorted(ExchangeService.revisions(self.snapshot).items())),
        )


def safe_scenario_id(scenario_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", scenario_id) or "scenario"


class ExchangeService:
    def __init__(self, store: ScenarioStore, worlds: WorldService) -> None:
        self.store = store
        self.worlds = worlds
        self._reader = ArtifactReader(store)

    # -- read helpers -------------------------------------------------------- #

    def _optional(self, snapshot: ArtifactSnapshot, name: str) -> ArtifactRead | None:
        read = self._reader.read(snapshot, name)
        if read.state == STATE_ABSENT:
            return None
        if read.error is not None:
            raise read.error
        return read

    @staticmethod
    def _input(read: ArtifactRead | None) -> ArtifactInput | None:
        if read is None:
            return None
        assert read.raw is not None
        return ArtifactInput(document=read.raw, revision=read.revision or "")

    @staticmethod
    def revisions(snapshot: ArtifactSnapshot) -> dict[str, str]:
        """The ``artifactRevisions`` grammar of the bundle manifest: file
        revision of every PRESENT artifact of the snapshot, sorted by name."""
        return {
            name: obs.revision or ""
            for name, obs in sorted(snapshot.files.items())
            if obs.present and obs.revision is not None
        }

    # -- observation (shared by the export and the Phase 23C result binding) -- #

    def observe(self, scenario_id: str, *, glb_bytes: bool = False) -> SourceObservation:
        """Observe the scenario's current authoritative state ONCE: the
        scenario document (404 / schema 422 / migration-on-read), the world
        guard, every export artifact under one lock hold and the resolved
        Effective Ramp. Pure read; nothing is generated or persisted."""
        self.store.get(scenario_id)
        snapshot = self._reader.snapshot(scenario_id, EXPORT_ARTIFACTS, glb_bytes=glb_bytes)
        self._reader.require_world(snapshot)
        ramp = resolve_effective_ramp(snapshot, self._reader)
        # the level accesses belong to the layout-v2 selection (rule 157);
        # LEGACY has none — the same contract as DesignService.active_level_accesses
        accesses = (
            self._optional(snapshot, LEVEL_ACCESSES_ARTIFACT)
            if ramp.active_source == "LAYOUT_V2"
            else None
        )
        return SourceObservation(
            snapshot=snapshot,
            ramp=ramp,
            accesses=accesses,
            levels=self._optional(snapshot, LEVELS_ARTIFACT),
            shafts=self._optional(snapshot, SHAFTS_ARTIFACT),
            network=self._optional(snapshot, NETWORK_ARTIFACT),
            capability=self._optional(snapshot, CAPABILITY_GRAPH_ARTIFACT),
            stopes=self._optional(snapshot, STOPES_ARTIFACT),
            timeline=self._optional(snapshot, TIMELINE_ARTIFACT),
            tunnel=self._optional(snapshot, TUNNEL_MESH_ARTIFACT),
            development=self._optional(snapshot, DEVELOPMENT_MESH_ARTIFACT),
        )

    def observe_source_snapshot(self, scenario_id: str) -> SourceSnapshot:
        """The ``sourceSnapshot`` identity a bundle exported NOW would carry
        (Phase 23C, rule 214): the binding a MineResult is compared against.
        Lightweight — no world load, no GLB bytes, nothing projected."""
        return self.observe(scenario_id).source_snapshot

    def _load_world(
        self, scenario_id: str, observed: SourceObservation
    ) -> tuple[Scenario, SyntheticWorld]:
        scenario, world, scenario_rev, arrays_rev = self.worlds.load_bound(scenario_id)
        snapshot = observed.snapshot
        if (scenario_rev, arrays_rev) != (snapshot.scenario_revision, snapshot.arrays_revision):
            raise ReadSnapshotChangedError(
                scenario_id, "world moved while the export snapshot was taken"
            )
        return scenario, world

    def _inputs(
        self, observed: SourceObservation, scenario: Scenario, world: SyntheticWorld
    ) -> ExchangeInputs:
        snapshot = observed.snapshot
        ramp_res = observed.ramp
        ramp_payload: dict[str, Any] | None = ramp_res.payload
        ramp_input = (
            ArtifactInput(ramp_payload, snapshot.revision_of(ramp_res.owning_artifact))
            if ramp_payload is not None
            else None
        )
        tunnel_glb = snapshot.observation(TUNNEL_MESH_GLB)
        development_glb = snapshot.observation(DEVELOPMENT_MESH_GLB)
        return ExchangeInputs(
            scenario=scenario,
            world=world,
            scenario_revision=snapshot.scenario_revision or "",
            arrays_revision=snapshot.arrays_revision or "",
            active_source=ramp_res.active_source,
            ramp=ramp_input,
            ramp_artifact=ramp_res.owning_artifact if ramp_payload is not None else None,
            accesses=self._input(observed.accesses),
            levels=self._input(observed.levels),
            shafts=self._input(observed.shafts),
            network=self._input(observed.network),
            capability=self._input(observed.capability),
            stopes=self._input(observed.stopes),
            timeline=self._input(observed.timeline),
            tunnel_report=self._input(observed.tunnel),
            tunnel_glb=(
                tunnel_glb.data if observed.tunnel is not None and tunnel_glb is not None else None
            ),
            development_report=self._input(observed.development),
            development_glb=(
                development_glb.data
                if observed.development is not None and development_glb is not None
                else None
            ),
            artifact_revisions=self.revisions(snapshot),
        )

    def observe_edge_centerlines(
        self, scenario_id: str
    ) -> tuple[SourceSnapshot, list[EdgeGeometry]]:
        """The identity space a MineResult binds to (Phase 23C, rule 216):
        the ``sourceSnapshot`` of the current state and every MineNetwork
        edge that carries an owning centerline, projected through the SAME
        ``assemble_centerlines`` / ``project_network`` the bundle uses — so
        the edge ids, the entity ids, the polylines and the
        ``sourceNodeId → targetNodeId`` chainage axis are exactly those an
        exported bundle carried. Nothing is generated or persisted."""
        observed = self.observe(scenario_id)
        scenario, world = self._load_world(scenario_id, observed)
        inputs = self._inputs(observed, scenario, world)
        omissions: list[ExchangeOmission] = []
        assembled = assemble_centerlines(inputs, omissions)
        network = observed.network
        if assembled is None or network is None or inputs.network is None:
            return observed.source_snapshot, []
        centerlines, _aggregates = assembled
        net = inputs.network.document
        if net.get("status") != "SUCCESS":
            return observed.source_snapshot, []
        doc = project_network(
            net,
            inputs.network.revision,
            centerlines,
            ramp_doc=inputs.ramp.document if inputs.ramp is not None else None,
            ramp_artifact=inputs.ramp_artifact,
            accesses_doc=inputs.accesses.document if inputs.accesses is not None else None,
            levels_doc=inputs.levels.document if inputs.levels is not None else None,
            shafts_doc=inputs.shafts.document if inputs.shafts is not None else None,
        )
        by_entity = {c.entity_id: c for c in centerlines}
        edges: list[EdgeGeometry] = []
        for edge in doc.edges:
            if edge.geometry_entity_id is None:
                continue  # RAISE: no owning-centerline contract, no polyline
            entity = by_entity[edge.geometry_entity_id]
            edges.append(
                EdgeGeometry(
                    edge_id=edge.id,
                    edge_type=edge.type,
                    source_node_id=edge.source_node_id,
                    target_node_id=edge.target_node_id,
                    geometry_entity_id=edge.geometry_entity_id,
                    points=np.asarray(entity.points, dtype=np.float64),
                )
            )
        return observed.source_snapshot, edges

    # -- export --------------------------------------------------------------- #

    def export(self, scenario_id: str) -> ExportResult:
        observed = self.observe(scenario_id, glb_bytes=True)
        scenario, world = self._load_world(scenario_id, observed)
        snapshot = observed.snapshot
        spec = build_exchange(self._inputs(observed, scenario, world))
        zip_bytes, manifest = write_bundle(spec)

        # long-running export consistency: the sources must not have moved
        after = self._reader.snapshot(scenario_id, EXPORT_ARTIFACTS)
        if (
            (after.scenario_revision, after.arrays_revision)
            != (
                snapshot.scenario_revision,
                snapshot.arrays_revision,
            )
            or self.revisions(after) != self.revisions(snapshot)
            or {n for n, o in after.files.items() if o.present}
            != {n for n, o in snapshot.files.items() if o.present}
        ):
            raise ReadSnapshotChangedError(
                scenario_id, "derived artifacts changed during the export"
            )
        return ExportResult(
            zip_bytes=zip_bytes,
            manifest=manifest,
            filename=f"minegen_{safe_scenario_id(scenario_id)}_mineexchange_v1.zip",
        )
