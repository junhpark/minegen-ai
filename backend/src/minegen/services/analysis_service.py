"""Mine analysis service (Phase 22A/B): ONE coherent validated snapshot →
pure projection → ``MineAnalysisPayload``. Read-only — nothing is generated,
persisted or invalidated; ``economics.json`` is the only file this service
ever writes, and it is a user-authored assumption document beside
``scenario.json`` (never a derived artifact, never a fingerprint input).

Snapshot consistency (directive §10; PR #48 review blocker): the scenario
document is read through the ONE bound read (``ScenarioStore.get_bound``,
stat → get → re-stat) and the artifact snapshot is taken with
``expect_scenario_revision`` = that revision, so the document object and
every observation are ONE ``scenario.json`` revision — a same-id PUT
between the two is ``READ_SNAPSHOT_CHANGED``, never an old document
projected beside new artifacts. The sources actually consumed —
``scenario.json``, ``arrays.npz`` and the world commit record (world
binding), ``network.json``, ``stopes.json``, ``timeline.json`` and
``economics.json`` — are observed under the store lock BEFORE the
projection and re-observed AFTER it; any movement is
``READ_SNAPSHOT_CHANGED``. Ramp / levels / shafts are not read
(the network is the development authority), so they are not part of the
consistency set.
"""

from __future__ import annotations

from typing import Any

from minegen.analysis.builder import AnalysisInputs, SourceRead, build_analysis
from minegen.analysis.economics import (
    EconomicsConfig,
    EconomicsConfigResponse,
    EconomicsObservation,
    observe_economics,
    write_economics,
)
from minegen.analysis.models import MineAnalysisPayload
from minegen.core.artifacts import NETWORK_ARTIFACT, STOPES_ARTIFACT, TIMELINE_ARTIFACT
from minegen.services.artifact_errors import ReadSnapshotChangedError, WorldNotGeneratedError
from minegen.services.artifact_reader import (
    STATE_ABSENT,
    ArtifactRead,
    ArtifactReader,
    ArtifactSnapshot,
)
from minegen.services.scenario_service import ScenarioStore

__all__ = ["ANALYSIS_ARTIFACTS", "AnalysisService"]

#: the derived artifacts the analysis consumes (development authority,
#: active production artifact, timeline)
ANALYSIS_ARTIFACTS: tuple[str, ...] = (NETWORK_ARTIFACT, STOPES_ARTIFACT, TIMELINE_ARTIFACT)


class AnalysisService:
    def __init__(self, store: ScenarioStore) -> None:
        self.store = store
        self._reader = ArtifactReader(store)

    # -- economics config ----------------------------------------------------- #

    def economics_config(self, scenario_id: str) -> EconomicsConfigResponse:
        self.store.get(scenario_id)  # 404 / schema 422 / migration-on-read
        obs = observe_economics(self.store, scenario_id)
        return EconomicsConfigResponse(
            configured=obs.config is not None, revision=obs.revision, config=obs.config
        )

    def put_economics_config(
        self, scenario_id: str, config: EconomicsConfig
    ) -> EconomicsConfigResponse:
        """Validate (the route's 422) → atomic write → revision. Touches no
        mine artifact: no derived deletion, no fingerprint, no cache."""
        self.store.get(scenario_id)
        revision = write_economics(self.store, scenario_id, config)
        return EconomicsConfigResponse(configured=True, revision=revision, config=config)

    # -- analysis ------------------------------------------------------------- #

    def _optional(self, snapshot: ArtifactSnapshot, name: str) -> SourceRead | None:
        read: ArtifactRead = self._reader.read(snapshot, name)
        if read.state == STATE_ABSENT:
            return None
        if read.error is not None:
            raise read.error
        assert read.model is not None and read.raw is not None
        return SourceRead(model=read.model, raw=read.raw, revision=read.revision or "")

    @staticmethod
    def _fingerprint(snapshot: ArtifactSnapshot, economics: EconomicsObservation) -> Any:
        return (
            snapshot.scenario_revision,
            snapshot.arrays_revision,
            # the world commit record is consumed by ``require_world`` and is
            # therefore part of the coherent set (PR #48 review)
            (snapshot.world_record.present, snapshot.world_record.revision),
            tuple(
                (name, obs.present, obs.revision) for name, obs in sorted(snapshot.files.items())
            ),
            economics.file_revision,
        )

    def analyze(self, scenario_id: str) -> MineAnalysisPayload:
        # the bound document read and the artifact observation are ONE
        # scenario revision (a PUT in between → READ_SNAPSHOT_CHANGED)
        scenario, scenario_revision = self.store.get_bound(scenario_id)
        snapshot = self._reader.snapshot(
            scenario_id, ANALYSIS_ARTIFACTS, expect_scenario_revision=scenario_revision
        )
        economics = observe_economics(self.store, scenario_id)
        assert snapshot.scenario_revision == scenario_revision  # bound above
        # the world guard decides whether derived artifacts may be read at all
        # (AC-01F: never trusted without a VALID committed world); a missing
        # world is a NORMAL partial analysis here, never a refusal
        world_generated = True
        try:
            self._reader.require_world(snapshot)
        except WorldNotGeneratedError:
            world_generated = False
        network = self._optional(snapshot, NETWORK_ARTIFACT) if world_generated else None
        production = self._optional(snapshot, STOPES_ARTIFACT) if world_generated else None
        timeline = self._optional(snapshot, TIMELINE_ARTIFACT) if world_generated else None
        payload = build_analysis(
            AnalysisInputs(
                scenario=scenario,
                scenario_revision=scenario_revision,
                world_generated=world_generated,
                network=network,
                production=production,
                timeline=timeline,
                economics=economics.config,
                economics_revision=economics.revision,
            )
        )
        after = self._reader.snapshot(scenario_id, ANALYSIS_ARTIFACTS)
        after_economics = observe_economics(self.store, scenario_id)
        if self._fingerprint(after, after_economics) != self._fingerprint(snapshot, economics):
            raise ReadSnapshotChangedError(
                scenario_id, "analysis sources changed while the analysis was computed"
            )
        return payload
