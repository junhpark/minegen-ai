"""MineExchange export service (Phase 23A): ONE coherent validated snapshot
→ pure projection → deterministic ZIP; nothing persisted, no derived
artifact registered. A source that moves during the export is refused
(``READ_SNAPSHOT_CHANGED``), never mixed into the bundle."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from minegen.core.artifacts import (
    CAPABILITY_GRAPH_ARTIFACT,
    DEVELOPMENT_MESH_ARTIFACT,
    DEVELOPMENT_MESH_GLB,
    LEVEL_ACCESSES_ARTIFACT,
    LEVELS_ARTIFACT,
    NETWORK_ARTIFACT,
    SHAFTS_ARTIFACT,
    TUNNEL_MESH_ARTIFACT,
    TUNNEL_MESH_GLB,
)
from minegen.exchange.builder import ArtifactInput, ExchangeInputs, build_exchange
from minegen.exchange.bundle import write_bundle
from minegen.exchange.models import ExchangeManifest
from minegen.services.artifact_errors import ReadSnapshotChangedError
from minegen.services.artifact_reader import (
    STATE_ABSENT,
    ArtifactRead,
    ArtifactReader,
    ArtifactSnapshot,
)
from minegen.services.effective_ramp import RAMP_FILES, resolve_effective_ramp
from minegen.services.scenario_service import ScenarioStore
from minegen.services.world_service import WorldService

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
        ]
    )
)


@dataclass(frozen=True)
class ExportResult:
    zip_bytes: bytes
    manifest: ExchangeManifest
    filename: str


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
    def _revisions(snapshot: ArtifactSnapshot) -> dict[str, str]:
        return {
            name: obs.revision or ""
            for name, obs in sorted(snapshot.files.items())
            if obs.present and obs.revision is not None
        }

    # -- export --------------------------------------------------------------- #

    def export(self, scenario_id: str) -> ExportResult:
        self.store.get(scenario_id)  # 404 / schema 422 / migration-on-read
        snapshot = self._reader.snapshot(scenario_id, EXPORT_ARTIFACTS, glb_bytes=True)
        self._reader.require_world(snapshot)
        scenario, world, scenario_rev, arrays_rev = self.worlds.load_bound(scenario_id)
        if (scenario_rev, arrays_rev) != (snapshot.scenario_revision, snapshot.arrays_revision):
            raise ReadSnapshotChangedError(
                scenario_id, "world moved while the export snapshot was taken"
            )

        ramp_res = resolve_effective_ramp(snapshot, self._reader)
        active = ramp_res.active_source
        ramp_payload: dict[str, Any] | None = ramp_res.payload
        ramp_input = (
            ArtifactInput(ramp_payload, snapshot.revision_of(ramp_res.owning_artifact))
            if ramp_payload is not None
            else None
        )
        # the level accesses belong to the layout-v2 selection (rule 157);
        # LEGACY has none — the same contract as DesignService.active_level_accesses
        accesses = (
            self._optional(snapshot, LEVEL_ACCESSES_ARTIFACT) if active == "LAYOUT_V2" else None
        )
        levels = self._optional(snapshot, LEVELS_ARTIFACT)
        shafts = self._optional(snapshot, SHAFTS_ARTIFACT)
        network = self._optional(snapshot, NETWORK_ARTIFACT)
        capability = self._optional(snapshot, CAPABILITY_GRAPH_ARTIFACT)
        tunnel = self._optional(snapshot, TUNNEL_MESH_ARTIFACT)
        development = self._optional(snapshot, DEVELOPMENT_MESH_ARTIFACT)
        tunnel_glb = snapshot.observation(TUNNEL_MESH_GLB)
        development_glb = snapshot.observation(DEVELOPMENT_MESH_GLB)

        inputs = ExchangeInputs(
            scenario=scenario,
            world=world,
            scenario_revision=snapshot.scenario_revision or "",
            arrays_revision=snapshot.arrays_revision or "",
            active_source=active,
            ramp=ramp_input,
            ramp_artifact=ramp_res.owning_artifact if ramp_payload is not None else None,
            accesses=self._input(accesses),
            levels=self._input(levels),
            shafts=self._input(shafts),
            network=self._input(network),
            capability=self._input(capability),
            tunnel_report=self._input(tunnel),
            tunnel_glb=tunnel_glb.data if tunnel is not None and tunnel_glb is not None else None,
            development_report=self._input(development),
            development_glb=(
                development_glb.data
                if development is not None and development_glb is not None
                else None
            ),
            artifact_revisions=self._revisions(snapshot),
        )
        spec = build_exchange(inputs)
        zip_bytes, manifest = write_bundle(spec)

        # long-running export consistency: the sources must not have moved
        after = self._reader.snapshot(scenario_id, EXPORT_ARTIFACTS)
        if (
            (after.scenario_revision, after.arrays_revision)
            != (
                snapshot.scenario_revision,
                snapshot.arrays_revision,
            )
            or self._revisions(after) != self._revisions(snapshot)
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
