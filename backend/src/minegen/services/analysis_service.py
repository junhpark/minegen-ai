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
from minegen.analysis.layout_comparison import (
    LayoutComparisonPayload,
    build_layout_comparison,
)
from minegen.analysis.models import MineAnalysisPayload
from minegen.analysis.sensitivity import (
    DEFAULT_PERTURBATIONS_PCT,
    SensitivityInputs,
    SensitivityPayload,
    WhatIfFactors,
    WhatIfOutcome,
    build_sensitivity,
    evaluate_what_if,
)
from minegen.analysis.timeseries import DEFAULT_BUCKET_DAYS, TimeseriesPayload, build_timeseries
from minegen.assessment.builder import CatalogueShapeError
from minegen.core.artifacts import (
    LAYOUT_V2_ARTIFACT,
    LAYOUT_V2_SELECTED_ARTIFACT,
    LEVEL_ACCESSES_ARTIFACT,
    LEVELS_ARTIFACT,
    NETWORK_ARTIFACT,
    RAMP_SOURCE_FILE,
    SHAFTS_ARTIFACT,
    STOPES_ARTIFACT,
    TIMELINE_ARTIFACT,
)
from minegen.services.artifact_errors import (
    ArtifactMalformedError,
    ReadSnapshotChangedError,
    WorldNotGeneratedError,
)
from minegen.services.artifact_reader import (
    STATE_ABSENT,
    ArtifactRead,
    ArtifactReader,
    ArtifactSnapshot,
)
from minegen.services.effective_ramp import RAMP_FILES, resolve_effective_ramp
from minegen.services.scenario_service import ScenarioStore

__all__ = [
    "ANALYSIS_ARTIFACTS",
    "LAYOUT_COMPARISON_ARTIFACTS",
    "SENSITIVITY_ARTIFACTS",
    "AnalysisService",
]

#: the derived artifacts the analysis consumes (development authority,
#: active production artifact, timeline)
ANALYSIS_ARTIFACTS: tuple[str, ...] = (NETWORK_ARTIFACT, STOPES_ARTIFACT, TIMELINE_ARTIFACT)

#: hardening PR-2 H3 §8.3: the sensitivity what-if additionally reads the
#: owning-centerline documents the in-memory reschedule needs (the Effective
#: Ramp resolution files, levels, shafts) — all observed in the ONE snapshot
SENSITIVITY_ARTIFACTS: tuple[str, ...] = tuple(
    dict.fromkeys([*ANALYSIS_ARTIFACTS, *RAMP_FILES, LEVELS_ARTIFACT, SHAFTS_ARTIFACT])
)

#: the sources the Phase 22C layout comparison consumes (directive §9): the
#: catalogue, the selection with its co-published level accesses (the
#: reader's pair unit — observed so a stale / malformed half refuses), and
#: the ramp-source switch; ``economics.json`` is observed beside them
LAYOUT_COMPARISON_ARTIFACTS: tuple[str, ...] = (
    LAYOUT_V2_ARTIFACT,
    LAYOUT_V2_SELECTED_ARTIFACT,
    LEVEL_ACCESSES_ARTIFACT,
    RAMP_SOURCE_FILE,
)


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

    def _optional_read(self, snapshot: ArtifactSnapshot, name: str) -> ArtifactRead | None:
        """ABSENT → ``None``, any read error → raised, VALID → the read (raw
        document; the layout artifacts declare no typed payload model)."""
        read = self._reader.read(snapshot, name)
        if read.state == STATE_ABSENT:
            return None
        if read.error is not None:
            raise read.error
        assert read.raw is not None
        return read

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

    def _bound_inputs(
        self, scenario_id: str, artifacts: tuple[str, ...] = ANALYSIS_ARTIFACTS
    ) -> tuple[AnalysisInputs, Any, EconomicsObservation]:
        """The ONE bound read + artifact snapshot + economics observation every
        analysis projection starts from (``analyze`` / ``timeseries`` /
        ``sensitivity``)."""
        scenario, scenario_revision = self.store.get_bound(scenario_id)
        snapshot = self._reader.snapshot(
            scenario_id, artifacts, expect_scenario_revision=scenario_revision
        )
        economics = observe_economics(self.store, scenario_id)
        assert snapshot.scenario_revision == scenario_revision  # bound above
        world_generated = True
        try:
            self._reader.require_world(snapshot)
        except WorldNotGeneratedError:
            world_generated = False
        network = self._optional(snapshot, NETWORK_ARTIFACT) if world_generated else None
        production = self._optional(snapshot, STOPES_ARTIFACT) if world_generated else None
        timeline = self._optional(snapshot, TIMELINE_ARTIFACT) if world_generated else None
        inputs = AnalysisInputs(
            scenario=scenario,
            scenario_revision=scenario_revision,
            world_generated=world_generated,
            network=network,
            production=production,
            timeline=timeline,
            economics=economics.config,
            economics_revision=economics.revision,
        )
        return inputs, snapshot, economics

    def _verify_unmoved(
        self,
        scenario_id: str,
        snapshot: Any,
        economics: EconomicsObservation,
        what: str,
        artifacts: tuple[str, ...] = ANALYSIS_ARTIFACTS,
    ) -> None:
        after = self._reader.snapshot(scenario_id, artifacts)
        after_economics = observe_economics(self.store, scenario_id)
        if self._fingerprint(after, after_economics) != self._fingerprint(snapshot, economics):
            raise ReadSnapshotChangedError(
                scenario_id, f"analysis sources changed while the {what} was computed"
            )

    def timeseries(self, scenario_id: str, bucket_days: float | None = None) -> TimeseriesPayload:
        """Hardening PR-2 H3 §6: the READ-ONLY bucketed time series. Same
        bound-snapshot protocol as :meth:`analyze`; ``bucketDays`` defaults
        to the configured ``cashflowBucketDays`` (else the 30-day display
        default). Nothing is persisted or invalidated."""
        inputs, snapshot, economics = self._bound_inputs(scenario_id)
        resolution = (
            bucket_days
            if bucket_days is not None
            else economics.config.cashflow_bucket_days
            if economics.config is not None
            else DEFAULT_BUCKET_DAYS
        )
        payload = build_timeseries(inputs, resolution)
        self._verify_unmoved(scenario_id, snapshot, economics, "time series")
        return payload

    def _sensitivity_inputs(
        self, scenario_id: str
    ) -> tuple[SensitivityInputs, Any, EconomicsObservation]:
        """The analysis inputs plus the owning-centerline documents of the
        in-memory reschedule, from ONE snapshot. A missing optional document
        is ``None`` (the what-if answers NOT_AVAILABLE); a present unusable one
        raises its typed read error."""
        inputs, snapshot, economics = self._bound_inputs(scenario_id, SENSITIVITY_ARTIFACTS)
        ramp: dict[str, Any] | None = None
        levels: dict[str, Any] | None = None
        accesses: dict[str, Any] | None = None
        shafts: dict[str, Any] | None = None
        if inputs.world_generated:
            resolution = resolve_effective_ramp(snapshot, self._reader)
            ramp = resolution.payload
            levels_read = self._optional_read(snapshot, LEVELS_ARTIFACT)
            levels = None if levels_read is None else levels_read.raw
            if resolution.active_source == "LAYOUT_V2":
                accesses_read = self._optional_read(snapshot, LEVEL_ACCESSES_ARTIFACT)
                accesses = None if accesses_read is None else accesses_read.raw
            shafts_read = self._optional_read(snapshot, SHAFTS_ARTIFACT)
            shafts = None if shafts_read is None else shafts_read.raw
        return (
            SensitivityInputs(
                analysis=inputs,
                ramp_payload=ramp,
                levels_payload=levels,
                accesses_payload=accesses,
                shafts_payload=shafts,
            ),
            snapshot,
            economics,
        )

    def sensitivity(
        self, scenario_id: str, perturbations_pct: tuple[float, ...] | None = None
    ) -> SensitivityPayload:
        """Hardening PR-2 H3 §8.3: the finite what-if grid (nine declared
        parameters × the perturbations) over the current authoritative
        quantities and timing; schedule parameters rerun the timeline builder
        in memory. Read-only — nothing persisted, nothing invalidated."""
        inputs, snapshot, economics = self._sensitivity_inputs(scenario_id)
        payload = build_sensitivity(
            inputs, perturbations_pct if perturbations_pct else DEFAULT_PERTURBATIONS_PCT
        )
        self._verify_unmoved(scenario_id, snapshot, economics, "sensitivity", SENSITIVITY_ARTIFACTS)
        return payload

    def what_if(self, scenario_id: str, factors: WhatIfFactors) -> WhatIfOutcome:
        """One explicit what-if override (same contract as ``sensitivity``)."""
        inputs, snapshot, economics = self._sensitivity_inputs(scenario_id)
        outcome = evaluate_what_if(inputs, factors)
        self._verify_unmoved(scenario_id, snapshot, economics, "what-if", SENSITIVITY_ARTIFACTS)
        return outcome

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

    # -- layout comparison (Phase 22C) ---------------------------------------- #

    def layout_comparison(self, scenario_id: str) -> LayoutComparisonPayload:
        """READ-ONLY comparable layout development cost over the persisted
        layout-v2 catalogue (rules 204–206). Same snapshot protocol as
        :meth:`analyze`: bound scenario read, ONE artifact snapshot at that
        revision, ``economics.json`` beside it, re-observation after the
        projection (``READ_SNAPSHOT_CHANGED`` on any movement). Nothing is
        generated, persisted or invalidated; no per-candidate artifact is
        read or imagined. A catalogue that lacks a field THIS consumer reads
        is ``ARTIFACT_MALFORMED`` (409), never a bare 500."""
        _scenario, scenario_revision = self.store.get_bound(scenario_id)
        snapshot = self._reader.snapshot(
            scenario_id, LAYOUT_COMPARISON_ARTIFACTS, expect_scenario_revision=scenario_revision
        )
        economics = observe_economics(self.store, scenario_id)
        assert snapshot.scenario_revision == scenario_revision  # bound above
        world_generated = True
        try:
            self._reader.require_world(snapshot)
        except WorldNotGeneratedError:
            world_generated = False
        catalogue: ArtifactRead | None = None
        selected: ArtifactRead | None = None
        active_source = "LEGACY"
        if world_generated:
            # the active source FIRST, as the assessment does (rule 189); a
            # present-but-unusable switch file refuses (never a silent LEGACY)
            active_source = self._reader.resolve_ramp_source(snapshot)
            catalogue = self._optional_read(snapshot, LAYOUT_V2_ARTIFACT)
            selected = self._optional_read(snapshot, LAYOUT_V2_SELECTED_ARTIFACT)
            # the co-published half is part of the selection's pair unit
            self._optional_read(snapshot, LEVEL_ACCESSES_ARTIFACT)
        try:
            payload = build_layout_comparison(
                catalogue=None if catalogue is None else catalogue.raw,
                selected=None if selected is None else selected.raw,
                active_source=active_source,
                world_generated=world_generated,
                economics=economics.config,
                economics_revision=economics.revision,
                layout_revision=None if catalogue is None else catalogue.revision,
                selection_revision=None if selected is None else selected.revision,
            )
        except CatalogueShapeError as err:
            raise ArtifactMalformedError(LAYOUT_V2_ARTIFACT, str(err)) from err
        after = self._reader.snapshot(scenario_id, LAYOUT_COMPARISON_ARTIFACTS)
        after_economics = observe_economics(self.store, scenario_id)
        if self._fingerprint(after, after_economics) != self._fingerprint(snapshot, economics):
            raise ReadSnapshotChangedError(
                scenario_id, "layout comparison sources changed while the comparison was computed"
            )
        return payload
