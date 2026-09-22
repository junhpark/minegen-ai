"""Phase 03 design services: cost evaluator construction, access-target
generation and persistence (``derived/targets.json``).

Evaluators are cached per scenario and dropped whenever the world is
invalidated (the world service owns that lifecycle)."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import numpy as np

from minegen.assessment.builder import build_design_assessment
from minegen.assessment.models import DesignAssessmentPayload, DesignAssessmentSources
from minegen.capability.builder import (
    CapabilityGraphBuilder,
    can_reach,
    query_graph_from,
)
from minegen.capability.models import CapabilityGraphPayload, CapabilityPathQuery
from minegen.core.artifact_registry import LOCATION_DERIVED, fingerprint_paths, invalidated_by
from minegen.core.artifacts import (
    CAPABILITY_GRAPH_ARTIFACT,
    DECLINE_ARTIFACT,
    DEVELOPMENT_MESH_ARTIFACT,
    DEVELOPMENT_MESH_GLB,
    LAYOUT_V2_ARTIFACT,
    LAYOUT_V2_SELECTED_ARTIFACT,
    LEGACY_RAMP_ARTIFACT,
    LEVEL_ACCESSES_ARTIFACT,
    LEVELS_ARTIFACT,
    NETWORK_ARTIFACT,
    RAMP_SOURCE_FILE,
    SHAFTS_ARTIFACT,
    STOPES_ARTIFACT,
    TARGETS_ARTIFACT,
    TIMELINE_ARTIFACT,
    TUNNEL_MESH_ARTIFACT,
    TUNNEL_MESH_GLB,
)
from minegen.core.enums import Capability, DistanceContract, OrebodyType
from minegen.core.mesh_record import build_mesh_commit, mesh_commit_name
from minegen.core.models import ApiModel, Scenario
from minegen.core.publication import publish_bytes, publish_text
from minegen.design.constraints import DesignContext
from minegen.design.cost_field import ClearancePolicy, DesignCostEvaluator, clearance_policy_for
from minegen.design.development_mesh import DevelopmentMeshBuilder
from minegen.design.mine_designer import ChainedDeclineGenerator
from minegen.design.progress import (
    ProgressCallback,
    ProgressEvent,
    ProgressStage,
    no_progress,
)
from minegen.design.smoothing import DeclineSmoother
from minegen.design.targets import AccessTargetSet, generate_access_targets, resolve_portal
from minegen.design.tunnel_mesh import TunnelMeshBuilder
from minegen.layout.certification import (
    CandidateCertification,
    ClearancePolicyReconstructionError,
    candidate_points_from_catalogue,
    restore_candidate_policy,
)
from minegen.layout.materialize import materialize_effective_ramp, materialize_level_accesses
from minegen.layout.results import CandidateStatus, LayoutSearchResult
from minegen.layout.search import LayoutV2Search
from minegen.levels.builder import LevelDevelopmentBuilder, entries_from_level_accesses
from minegen.levels.models import LevelsPayload
from minegen.mining.methods.base import strategy_for, unsupported_method_payload
from minegen.mining.models import StopesPayload
from minegen.network.builder import MineNetworkBuilder
from minegen.network.models import NetworkPayload
from minegen.scheduling.builder import MineTimelineBuilder
from minegen.scheduling.models import TimelinePayload
from minegen.services.artifact_errors import (
    ArtifactMalformedError,
    CapabilityGraphNotGeneratedError,
    CapabilityGraphStaleError,
    DeclineNotGeneratedError,
    DevelopmentMeshNotGeneratedError,
    LayoutSelectionStaleError,
    LayoutV2NotGeneratedError,
    LayoutV2NotSelectedError,
    LevelAccessesNotGeneratedError,
    LevelsNotGeneratedError,
    NetworkNotFoundError,
    ShaftsNotGeneratedError,
    ShaftsStaleError,
    SmoothedNotGeneratedError,
    StaleInputsError,
    StopesNotGeneratedError,
    TargetsNotGeneratedError,
    TimelineNotGeneratedError,
    TunnelNotGeneratedError,
)
from minegen.services.artifact_reader import (
    STATE_ABSENT,
    ArtifactRead,
    ArtifactReader,
    ArtifactSnapshot,
)
from minegen.services.effective_ramp import (
    RAMP_FILES,
    RAMP_SOURCES,
    RampSource,
    file_revision,
    read_ramp_source,
    resolve_effective_ramp,
    write_ramp_source,
)
from minegen.services.scenario_service import ScenarioStore
from minegen.services.world_service import WorldService
from minegen.shafts.models import ShaftsPayload
from minegen.shafts.planner import ShaftPlanner
from minegen.world.synthetic_world import SyntheticWorld

#: AC-01F relocated every read-state exception to
#: ``services/artifact_errors.py`` so ONE class object exists for the reader,
#: the services and the routers. They are re-exported here (this ``__all__``
#: lists the re-exports only — the module's own definitions, ``DesignService``
#: and friends, are exported as always) so every existing
#: ``from minegen.services.design_service import <Error>`` and every
#: ``isinstance`` check in the routers and tests keeps working unchanged.
__all__ = [
    "CapabilityGraphNotGeneratedError",
    "CapabilityGraphStaleError",
    "DeclineNotGeneratedError",
    "DevelopmentMeshNotGeneratedError",
    "LayoutSelectionStaleError",
    "LayoutV2NotGeneratedError",
    "LayoutV2NotSelectedError",
    "LevelAccessesNotGeneratedError",
    "LevelsNotGeneratedError",
    "NetworkNotFoundError",
    "ShaftsNotGeneratedError",
    "ShaftsStaleError",
    "SmoothedNotGeneratedError",
    "StaleInputsError",
    "StopesNotGeneratedError",
    "TargetsNotGeneratedError",
    "TimelineNotGeneratedError",
    "TunnelNotGeneratedError",
]


class UnsupportedOrebodyError(RuntimeError):
    """The legacy Phase 03+ layout supports TABULAR only. Non-tabular
    scenarios are valid for world generation/visualization; generalized
    layout is deferred to Phase 20 — Parametric Layout Family Search
    (rule 123, docs/roadmap.md)."""


class UnknownNetworkNodeError(LookupError):
    """A capability path query names a node id the network does not have."""

    def __init__(self, node_id: str) -> None:
        super().__init__(f"network node '{node_id}' does not exist")
        self.node_id = node_id


class LayoutCandidateNotFoundError(LookupError):
    def __init__(self, candidate_id: str) -> None:
        super().__init__(f"layout-v2 candidate '{candidate_id}' does not exist")
        self.candidate_id = candidate_id


class LayoutCandidateInfeasibleError(ValueError):
    """Only FEASIBLE candidates can be selected / activated (rule 149)."""

    def __init__(self, candidate_id: str, status: str, reasons: list[str]) -> None:
        super().__init__(
            f"layout-v2 candidate '{candidate_id}' is {status}"
            + (f" ({', '.join(reasons)})" if reasons else "")
        )
        self.candidate_id = candidate_id
        self.status = status
        self.reasons = reasons


@dataclass(frozen=True)
class _RestoredPolicy:
    """One restored selected-candidate certification (AC-01D), valid for
    exactly one world object, catalogue revision and selection revision —
    any scenario mutation / world regeneration (new world object),
    catalogue regeneration (``layout_revision``) or re-selection of another
    candidate (``selected_revision``) misses. Policies are frozen value
    objects, so sharing one across the builders of a chain changes no
    number."""

    world: SyntheticWorld
    candidate_id: str
    layout_revision: str
    selected_revision: str
    evaluator: DesignCostEvaluator
    policy: ClearancePolicy


@dataclass(frozen=True)
class InputFingerprint:
    """Revision fingerprint of a decline job's inputs: (exists, size, mtime_ns)
    of scenario.json, arrays.npz and targets.json. Every invalidating mutation
    (scenario PUT, world regeneration, target regeneration, deletion) rewrites
    or removes at least one of these files, so equality of fingerprints means
    the inputs are the same revision — even when regenerated content is
    byte-identical, the revision is considered new (rules 40/46)."""

    entries: tuple[tuple[str, bool, int, int], ...]

    @staticmethod
    def _stat(path: Path) -> tuple[str, bool, int, int]:
        try:
            st = path.stat()
        except FileNotFoundError:
            return (path.name, False, 0, 0)
        return (path.name, True, st.st_size, st.st_mtime_ns)

    @classmethod
    def capture(cls, paths: list[Path]) -> InputFingerprint:
        return cls(entries=tuple(cls._stat(p) for p in paths))


def artifact_fingerprint(store: ScenarioStore, scenario_id: str, name: str) -> InputFingerprint:
    """The input revision of the registered artifact ``name`` (rule 60):
    ``InputFingerprint.capture`` over the registry's ORDERED, rooted input
    paths (``core/artifact_registry.py`` — ``scenario.json`` / ``arrays.npz``
    under the scenario directory, everything else under ``derived/``). The
    ONE consumer path of the fingerprint projection for every public
    ``*_fingerprint()`` of the design AND infrastructure services (AC-01E):
    the entry ORDER reaches persisted ``sourceRevision`` / selection
    ``revision`` bytes, so no service declares an input list of its own."""
    return InputFingerprint.capture(
        fingerprint_paths(
            name,
            scenario_dir=store.scenario_dir(scenario_id),
            derived_dir=store.derived_dir(scenario_id),
        )
    )


_Model = TypeVar("_Model", bound=ApiModel)


def _commit_mesh(commit_path: Path, report_revision: str, glb_revision: str | None) -> None:
    """Publish the INTERNAL mesh commit sidecar (AC-01F.2 correction B3) — the
    COMMIT POINT of a mesh generation. It names the identities this
    publication installed, never a stat of a path afterwards, and it stays out
    of the report, whose success shape is a public contract."""
    publish_text(
        commit_path,
        json.dumps(build_mesh_commit(report_revision=report_revision, glb_revision=glb_revision)),
    )


class DesignService:
    def __init__(self, store: ScenarioStore, worlds: WorldService) -> None:
        self.store = store
        self.worlds = worlds
        self._evaluators: dict[str, tuple[SyntheticWorld, DesignCostEvaluator]] = {}
        #: Stage D S16: bound to the WORLD object like its two siblings
        #: (``_evaluators``, ``_layouts``) — the cache was keyed on presence
        #: alone while its consumer (``generate_decline``) PERSISTS what it
        #: returns, so a warm set surviving a world change would have been
        #: written out (measured out-of-band: warm decline 599 centerline
        #: points vs cold 737 on bit-identical inputs)
        self._targets: dict[str, tuple[SyntheticWorld, AccessTargetSet]] = {}
        self._layouts: dict[str, tuple[SyntheticWorld, LayoutV2Search, LayoutSearchResult]] = {}
        self._selected_policies: dict[str, _RestoredPolicy] = {}
        #: AC-01F: the ONE validated read authority over ``derived/``. Every
        #: reader below — the direct GET methods AND the builders' upstream
        #: reads, which used to differ — goes through it, so a present-but
        #: -invalid artifact is refused with the same typed code everywhere.
        #: Internal: routers obtain the SERVICE through a FastAPI dependency
        #: (rule 40), never the reader.
        self._reader = ArtifactReader(store)

    # -- validated reads (AC-01F: READ ≠ TRUST) ----------------------------- #

    def _require_raw(self, scenario_id: str, name: str) -> dict[str, Any]:
        """The VALID document of a dict-only artifact, or its typed refusal.

        ``self.store.get`` stays the first call of every read path: it is the
        404 for an unknown scenario, the 422 for an unsupported schema, and —
        the ONE documented exception to "a read must not write" (A10) — the
        Phase 18 migration-on-read."""
        self.store.get(scenario_id)
        raw = self._reader.require(scenario_id, name).raw
        assert raw is not None, name  # a VALID read always carries its document
        return raw

    def _require_model(self, scenario_id: str, name: str, model: type[_Model]) -> _Model:
        """The VALID typed payload of one of the eight ``ApiModel``
        artifacts, validated by the reader against the SAME model the service
        used to validate with."""
        self.store.get(scenario_id)
        payload = self._reader.require(scenario_id, name).model
        if not isinstance(payload, model):  # pragma: no cover - READ_SPECS declares it
            raise ArtifactMalformedError(name, f"does not satisfy {model.__name__}")
        return payload

    # -- artifact lifecycle (AC-01E: the registry's ONE consumer path) ------- #

    def _fingerprint_of(self, scenario_id: str, name: str) -> InputFingerprint:
        return artifact_fingerprint(self.store, scenario_id, name)

    def _invalidate_downstream(
        self, scenario_id: str, *written: str, source: RampSource | None = None
    ) -> None:
        """Delete every derived artifact the registry derives from the
        artifacts a writer has JUST persisted (``invalidated_by`` — the
        transitive closure over ``core/artifact_registry.py``; rules 46 / 64
        / 67 / 74 / 79 / 86 / 92 / 98 / 151 / 162 / 184 / 185). This one
        method replaces the hand-sequenced per-writer cascades.

        PRECONDITION: called INSIDE the writer's ``with self.store.lock(sid)``
        block, immediately AFTER the write — the same lock that guards
        ``WorldService.invalidate`` (rule 60). The active ramp source that
        gates a ramp OWNER's downstream edges (``decline_smoothed.json`` →
        LEGACY, ``layout_v2_selected.json`` / ``level_accesses.json`` →
        LAYOUT_V2) is read from ``ramp_source.json`` AT THIS POINT, never
        earlier and never from memory (absent → LEGACY, rule 150); only a
        writer that has itself just written ``ramp_source.json`` passes the
        value explicitly. Every delete keeps the ``exists()`` guard; no
        in-memory cache is cleared. Scenario mutation / world regeneration are
        NOT this path — they stay ``WorldService.invalidate`` →
        ``ScenarioStore.clear_derived`` (rules 40 / 46).

        AC-01F A7: the source READ never aborts the cascade. It runs AFTER
        the writer's file write, so a typed refusal on an unusable
        ``ramp_source.json`` here would leave a published artifact with no cascade —
        a worse residue than the corruption. Unknown source at write cleanup
        therefore deletes the UNION of both closures: strictly more, never
        less, never a guessed LEGACY. Reads stay strict (ARTIFACT_MALFORMED)
        until an explicit ``PUT …/ramp-source`` repairs the file.

        C3: the rescue catches ``OSError`` beside ``ArtifactMalformedError``.
        "Unusable" is not only "corrupt bytes": a permission or I/O failure on
        the stat/read of the source file raises out of the snapshot itself,
        and the A7 principle is about the source READ never aborting the
        cascade — not about one exception class.

        S12 states the limit exactly: the DELETES themselves can still fail (a
        directory in place of a derived file, a permission error). The loop is
        MAXIMAL — every other file of the closure is still removed — and the
        failure is reported ONCE afterwards, as the ``OSError`` it has always
        been (an unmapped 500, unchanged). The pre-S12 loop stopped at the
        FIRST ``OSError``, leaving the rest of the closure on disk beside a
        freshly written artifact — measured: ``derived/tunnel_mesh.json``
        replaced by a directory, ``POST …/design/decline/smooth?sync=true``
        500, ``decline_smoothed.json`` rewritten and the deleted set ``[]``."""
        derived = self.store.derived_dir(scenario_id)
        artifacts: tuple[Any, ...]
        if source is not None:
            artifacts = invalidated_by(written, source)
        else:
            try:
                artifacts = invalidated_by(written, read_ramp_source(self._reader, scenario_id))
            except (ArtifactMalformedError, OSError):
                union: dict[str, Any] = {}
                for candidate in RAMP_SOURCES:
                    for artifact in invalidated_by(written, candidate):
                        union.setdefault(artifact.name, artifact)
                artifacts = tuple(union.values())
        failed: list[str] = []
        for artifact in artifacts:
            for file in artifact.files:
                # every invalidatable artifact lives under derived/ (the two
                # scenario-directory roots are reachable from no derived one)
                if file.location != LOCATION_DERIVED:  # pragma: no cover - registry invariant
                    raise ValueError(
                        f"'{file.name}' is invalidated but does not live under derived/"
                    )
                path = derived / file.name
                try:
                    if path.exists():
                        path.unlink()
                except OSError:
                    failed.append(file.name)
        if failed:
            # an UNDELETABLE file is an I/O fault, not an artifact read state:
            # it keeps the unmapped-500 answer it has always had (the guard
            # table's documented behaviour for an unmapped exception), and it
            # is raised only after the cascade has done everything it could
            raise OSError(
                f"scenario '{scenario_id}': the invalidation cascade could not delete "
                + ", ".join(failed)
            )

    # -- evaluator --------------------------------------------------------- #

    def evaluator(self, scenario_id: str) -> tuple[Scenario, SyntheticWorld, DesignCostEvaluator]:
        scenario, world = self.worlds.load(scenario_id)
        cached = self._evaluators.get(scenario_id)
        if cached is not None and cached[0] is world:
            return scenario, world, cached[1]
        if world.orebody.distance_contract is not DistanceContract.EXACT_METRIC_SDF:
            # rule 135: an implicit body's approximate clearance never feeds
            # the legacy hard-buffer evaluator — typed refusal, not a 500
            raise UnsupportedOrebodyError(scenario.orebody.orebody_type.value)
        ev = DesignCostEvaluator(world, scenario.design)
        self._evaluators[scenario_id] = (world, ev)
        return scenario, world, ev

    def evaluate(self, scenario_id: str, points: list[list[float]]) -> dict[str, Any]:
        _, _, ev = self.evaluator(scenario_id)
        res = ev.evaluate_points(np.asarray(points, dtype=np.float64))
        return {"count": len(res), "results": res.to_payload()}

    # -- targets ----------------------------------------------------------- #

    def targets_path(self, scenario_id: str) -> Any:
        return self.store.derived_dir(scenario_id) / TARGETS_ARTIFACT

    def generate_targets(self, scenario_id: str) -> dict[str, Any]:
        """Phase 03 access targets. AC-01F A3: the last unfingerprinted derived
        writer gets the rule-60 protocol — capture the registry input revision
        (``scenario.json`` + ``arrays.npz``) BEFORE the evaluator, generate
        outside the lock, re-check under the lock. A world regeneration or a
        scenario PUT that lands while the targets are being generated now
        fails the write closed (``JOB_INPUTS_CHANGED``) instead of persisting
        targets for a world that no longer exists (Stage A §5.4: 4 levels
        persisted where 3 were correct). The payload and its schema are
        unchanged — no provenance field is added."""
        fingerprint = self._fingerprint_of(scenario_id, TARGETS_ARTIFACT)
        scenario, world, ev = self.evaluator(scenario_id)
        if scenario.orebody.orebody_type is not OrebodyType.TABULAR:
            raise UnsupportedOrebodyError(scenario.orebody.orebody_type.value)
        portal, generated = resolve_portal(scenario, world)
        targets: AccessTargetSet = generate_access_targets(
            world,
            scenario.design,
            scenario.ramp,
            scenario.mining.sublevel_interval,
            ev,
            portal,
            generated,
        )
        payload = targets.to_dict()
        with self.store.lock(scenario_id):
            if self._fingerprint_of(scenario_id, TARGETS_ARTIFACT) != fingerprint:
                raise StaleInputsError(scenario_id)
            path = self.targets_path(scenario_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            publish_text(path, json.dumps(payload, indent=2))
            self._targets[scenario_id] = (world, targets)
            # rule 46: the decline built on the old targets and (rule 64) its
            # smoothed derivative are stale; everything derived from the
            # LEGACY effective ramp follows (rules 67/74/79/86/92/98/68 — a
            # LAYOUT_V2-derived chain does not)
            self._invalidate_downstream(scenario_id, TARGETS_ARTIFACT)
        return payload

    # -- decline (Phase 04) ------------------------------------------------ #

    def decline_path(self, scenario_id: str) -> Any:
        return self.store.derived_dir(scenario_id) / DECLINE_ARTIFACT

    def _targets_object(self, scenario_id: str) -> AccessTargetSet:
        """The Phase 04 precondition: ``targets.json`` must be a VALID
        artifact (AC-01F — a marker that is merely PRESENT no longer lets a
        corrupt file answer ``POST …/decline`` 200 SUCCESS, Stage A §2.2),
        and the in-memory set is then rebuilt deterministically exactly as
        before (``AccessTargetSet`` has no ``from_dict``)."""
        self._reader.require(scenario_id, TARGETS_ARTIFACT)
        scenario, world, ev = self.evaluator(scenario_id)
        cached = self._targets.get(scenario_id)
        if cached is not None and cached[0] is world:
            return cached[1]
        # targets.json exists from an earlier process: rebuild deterministically
        portal, generated = resolve_portal(scenario, world)
        targets = generate_access_targets(
            world,
            scenario.design,
            scenario.ramp,
            scenario.mining.sublevel_interval,
            ev,
            portal,
            generated,
        )
        self._targets[scenario_id] = (world, targets)
        return targets

    def input_fingerprint(self, scenario_id: str) -> InputFingerprint:
        return self._fingerprint_of(scenario_id, DECLINE_ARTIFACT)

    def generate_decline(
        self,
        scenario_id: str,
        max_levels: int | None = None,
        on_progress: ProgressCallback = no_progress,
    ) -> dict[str, Any]:
        # Capture the input revision BEFORE loading anything: a mutation that
        # lands between capture and load makes the check fail (fail-safe),
        # never the other way around.
        fingerprint = self.input_fingerprint(scenario_id)
        scenario, _, ev = self.evaluator(scenario_id)
        targets = self._targets_object(scenario_id)
        gen = ChainedDeclineGenerator(
            ev, scenario.ramp, scenario.design.search, scenario.tunnel_profile
        )
        result = gen.generate(targets, max_levels=max_levels, on_progress=on_progress)
        payload = result.to_dict()
        # Persist atomically w.r.t. invalidation: the same lock guards
        # WorldService.invalidate's deletions, so a stale job can never write
        # after a mutation cleared derived/ (rules 40/46/60).
        with self.store.lock(scenario_id):
            if self.input_fingerprint(scenario_id) != fingerprint:
                raise StaleInputsError(scenario_id)
            path = self.decline_path(scenario_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            publish_text(path, json.dumps(payload))
            # rule 64: the old smoothed artifact is stale, and with it (rules
            # 67–98) the chain derived from the LEGACY effective ramp
            self._invalidate_downstream(scenario_id, DECLINE_ARTIFACT)
        return payload

    # -- smoothing (Phase 05, rules 61–64) ---------------------------------- #

    def smoothed_path(self, scenario_id: str) -> Path:
        return self.store.derived_dir(scenario_id) / LEGACY_RAMP_ARTIFACT

    def smoothing_fingerprint(self, scenario_id: str) -> InputFingerprint:
        return self._fingerprint_of(scenario_id, LEGACY_RAMP_ARTIFACT)

    def generate_smoothed(
        self, scenario_id: str, on_progress: ProgressCallback = no_progress
    ) -> dict[str, Any]:
        """Phase 05: smooth + fully revalidate the persisted decline. The
        fingerprint additionally covers decline.json; persistence follows the
        same locked stale-input protocol as generate_decline (rule 60)."""
        fingerprint = self.smoothing_fingerprint(scenario_id)
        decline_payload = self.decline(scenario_id)  # 409 if not generated
        scenario, _, ev = self.evaluator(scenario_id)
        smoother = DeclineSmoother(ev, scenario.ramp, scenario.design.smoothing)

        def progress(i: int, n: int, level_id: str, stage: str) -> None:
            on_progress(
                ProgressEvent(
                    stage=ProgressStage(stage),
                    phase="DECLINE_SMOOTHING",
                    level=min(i + 1, n),
                    total_levels=n,
                    candidate=0,
                    total_candidates=0,
                    progress=min(i, n) / n if n else 1.0,
                    expanded_states=0,
                    level_id=level_id,
                )
            )

        result = smoother.smooth(decline_payload, on_progress=progress)
        payload = result.to_dict()
        n_seg = len(result.segments)
        on_progress(
            ProgressEvent(
                stage=ProgressStage.SMOOTHING_COMPLETED,
                phase="DECLINE_SMOOTHING",
                level=n_seg,
                total_levels=n_seg,
                candidate=0,
                total_candidates=0,
                progress=1.0,
                expanded_states=0,
                message=result.status,
            )
        )
        with self.store.lock(scenario_id):
            if self.smoothing_fingerprint(scenario_id) != fingerprint:
                raise StaleInputsError(scenario_id)
            path = self.smoothed_path(scenario_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            publish_text(path, json.dumps(payload))
            # rules 67/74/79/86/92/98/68: the LEGACY effective ramp changed
            self._invalidate_downstream(scenario_id, LEGACY_RAMP_ARTIFACT)
        return payload

    def smoothed(self, scenario_id: str) -> dict[str, Any]:
        return self._require_raw(scenario_id, LEGACY_RAMP_ARTIFACT)

    # -- layout-v2 + Effective Ramp (Phase 20A, rules 141–152) --------------- #

    def layout_path(self, scenario_id: str) -> Path:
        return self.store.derived_dir(scenario_id) / LAYOUT_V2_ARTIFACT

    def layout_selected_path(self, scenario_id: str) -> Path:
        return self.store.derived_dir(scenario_id) / LAYOUT_V2_SELECTED_ARTIFACT

    def level_accesses_path(self, scenario_id: str) -> Path:
        return self.store.derived_dir(scenario_id) / LEVEL_ACCESSES_ARTIFACT

    def ramp_source_path(self, scenario_id: str) -> Path:
        return self.store.derived_dir(scenario_id) / RAMP_SOURCE_FILE

    def layout_fingerprint(self, scenario_id: str) -> InputFingerprint:
        return self._fingerprint_of(scenario_id, LAYOUT_V2_ARTIFACT)

    def generate_layout_v2(
        self, scenario_id: str, on_progress: ProgressCallback = no_progress
    ) -> dict[str, Any]:
        """Phase 20A parametric family search over the generated world. Uses
        the layout's own evaluator (EXACT or COARSE_CONSERVATIVE clearance policy),
        so non-TABULAR orebodies are first-class here (rule 146). Persists
        ``derived/layout_v2.json``; a previous selection is stale and is
        deleted, and if LAYOUT_V2 is the active source its downstream chain
        is invalidated too (rule 151)."""
        fingerprint = self.layout_fingerprint(scenario_id)
        scenario, world = self.worlds.load(scenario_id)
        search = LayoutV2Search(scenario, world)
        result = search.run(on_progress)
        payload = result.to_dict()
        serialized = json.dumps(payload)
        with self.store.lock(scenario_id):
            if self.layout_fingerprint(scenario_id) != fingerprint:
                raise StaleInputsError(scenario_id)
            path = self.layout_path(scenario_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            publish_text(path, serialized)
            self._layouts[scenario_id] = (world, search, result)
            # rule 157: the selection (and the level accesses it owns) is
            # stale; the LAYOUT_V2-derived chain follows while that source
            # is active (rule 151)
            self._invalidate_downstream(scenario_id, LAYOUT_V2_ARTIFACT)
        return payload

    def layout_v2(self, scenario_id: str) -> dict[str, Any]:
        return self._require_raw(scenario_id, LAYOUT_V2_ARTIFACT)

    def _layout_object(self, scenario_id: str) -> tuple[LayoutV2Search, LayoutSearchResult]:
        """In-memory search result behind ``layout_v2.json``; rebuilt
        deterministically (same inputs → same result) when this process did
        not run the search itself. Used ONLY by ``select_layout_candidate``
        (materialization needs the full ``CandidateResult``); no downstream
        builder reads it — they restore the selected certification from its
        recipe (``_selected_candidate_policy``, AC-01D). The re-run on a cold
        cache for a DIFFERENT candidate than the persisted selection is the
        explicitly deferred residual recorded in
        ``docs/consolidation-baseline.md`` §7.

        AC-01F C3: the precondition is the VALIDATED read of the catalogue,
        not an ``is_file`` presence probe. The probe let a MALFORMED
        ``layout_v2.json`` through to the deterministic re-run — which rebuilds
        the result from scenario + world and never parses the catalogue — so
        the corrupt file was never noticed. MEASURED at HEAD ``12d7725``
        (``scratchpad/ac01f_C/select_malformed_probe.py``): with
        ``layout_v2.json`` = ``"{"``, ``POST …/design/layout-v2/select``
        answered **200** and WROTE ``layout_v2_selected.json`` +
        ``level_accesses.json`` carrying the corrupt catalogue's own
        ``layoutRevision``, and ``…/activate`` answered **200** — a fully
        activated LAYOUT_V2 ramp bound to a document nobody can parse. It is
        409 ``ARTIFACT_MALFORMED`` now, with nothing written."""
        self._reader.require(scenario_id, LAYOUT_V2_ARTIFACT)
        scenario, world = self.worlds.load(scenario_id)
        cached = self._layouts.get(scenario_id)
        if cached is not None and cached[0] is world:
            return cached[1], cached[2]
        search = LayoutV2Search(scenario, world)
        result = search.run()
        self._layouts[scenario_id] = (world, search, result)
        return search, result

    def select_layout_candidate(self, scenario_id: str, candidate_id: str) -> dict[str, Any]:
        """Materialize a FEASIBLE candidate as the layout-v2 Effective Ramp
        (``derived/layout_v2_selected.json``, rule 149). Selecting the
        candidate that is already selected for the same layout revision is a
        no-op; a different selection invalidates the LAYOUT_V2 downstream
        chain when that source is active.

        Stage D S3: ``store.get`` is the FIRST statement, before any
        fingerprint, snapshot or lock. An unknown, client-supplied scenario id
        used to reach ``ArtifactReader.snapshot`` → ``ScenarioStore.lock``
        first, and ``_locks`` is never pruned — measured at commit 3, 500
        distinct unknown ids on this route left ``len(_locks) == 502`` (base
        ``12d7725``: 0). The 404 is the same 404; it is just no longer paid for
        with an entry in a dict an attacker keys."""
        self.store.get(scenario_id)  # 404 / schema 422 / migration-on-read (A10)
        fingerprint = self._fingerprint_of(scenario_id, LAYOUT_V2_SELECTED_ARTIFACT)
        # AC-01D: the idempotent re-select / re-activate of the already
        # selected candidate at the same catalogue revision never touches
        # the in-memory search (and so never re-runs it on a cold cache).
        # AC-01F: the idempotency read is STATE-AWARE — only a VALID selection
        # is a usable one; a stale / malformed / certification-defective
        # document is "no usable selection", so this explicit re-selection
        # proceeds and WRITES. The repair is always the user's explicit write,
        # never a read-side fixup.
        # Stage D S5: the no-op requires BOTH halves of the rule-157 pair to
        # be VALID. With only the selection observed, a deleted or corrupt
        # ``level_accesses.json`` left the documented repair ("Repair is
        # always an explicit user write") a measured no-op — re-select and
        # re-activate both answered 200 and restored nothing.
        snapshot = self._reader.snapshot(
            scenario_id,
            [LAYOUT_V2_ARTIFACT, LAYOUT_V2_SELECTED_ARTIFACT, LEVEL_ACCESSES_ARTIFACT],
        )
        # AC-01F.2 correction: the SAME world guard the non-idempotent path
        # reaches one statement later through ``_layout_object``'s VALID
        # catalogue — applied here so the no-op early return cannot be the one
        # answer that trusts a derived artifact without a valid world
        self._reader.require_world(snapshot)
        layout_rev = snapshot.revision_of(LAYOUT_V2_ARTIFACT)
        existing = self._reader.read(snapshot, LAYOUT_V2_SELECTED_ARTIFACT)
        accesses_half = self._reader.read(snapshot, LEVEL_ACCESSES_ARTIFACT)
        # a VALID selection read has already passed ``_selection_revision_check``
        # against THIS snapshot's catalogue revision (R7: the old
        # ``layoutRevision == layout_rev`` conjunct here was the last textual
        # copy of a resolver freshness relation outside the reader)
        if (
            existing.state == "VALID"
            and accesses_half.state == "VALID"
            and existing.raw is not None
            and existing.raw.get("candidateId") == candidate_id
        ):
            return existing.raw
        search, result = self._layout_object(scenario_id)
        cand = result.candidate(candidate_id)
        if cand is None:
            raise LayoutCandidateNotFoundError(candidate_id)
        if cand.status != CandidateStatus.FEASIBLE:
            raise LayoutCandidateInfeasibleError(candidate_id, cand.status, cand.failure_reasons)
        revision = hashlib.sha256(
            json.dumps([fingerprint.entries, layout_rev, candidate_id], sort_keys=True).encode()
        ).hexdigest()[:16]
        # materialize under the candidate's OWN stage-4 evaluator, never the
        # whole-body search evaluator (Phase 20B.1-v2 1.1)
        cand_evaluator, _, _ = search.candidate_policy(result, candidate_id)
        payload = materialize_effective_ramp(result, cand, cand_evaluator, revision)
        payload["layoutRevision"] = layout_rev
        payload["owningArtifact"] = LAYOUT_V2_SELECTED_ARTIFACT
        # rule 157: the ramp junctions + level accesses of the SAME candidate,
        # same revision, persisted together with the main ramp
        accesses = materialize_level_accesses(
            result, cand, revision, self.store.get(scenario_id).mining.method.value
        )
        accesses["layoutRevision"] = layout_rev
        serialized = json.dumps(payload)
        serialized_accesses = json.dumps(accesses)
        with self.store.lock(scenario_id):
            current = self._fingerprint_of(scenario_id, LAYOUT_V2_SELECTED_ARTIFACT)
            if current != fingerprint:
                raise StaleInputsError(scenario_id)
            # AC-01F.2 D3: the level accesses are published FIRST and the
            # selection second. Two atomic replacements are not one atomic
            # pair, so the ORDER decides what a crash between them leaves:
            # accesses without a selection is an ABSENT selection
            # (LAYOUT_V2_NOT_SELECTED) beside the typed forward orphan
            # (LAYOUT_V2_SELECTION_STALE on the accesses), which the explicit
            # re-selection repairs — never a selection whose accesses are
            # missing, which rule 157 forbids and the network builder only
            # discovers as a weld error two builders later (Stage A §7.4).
            publish_text(self.level_accesses_path(scenario_id), serialized_accesses)
            path = self.layout_selected_path(scenario_id)
            publish_text(path, serialized)
            # rule 151 / 169: a NEW selection invalidates the LAYOUT_V2-derived
            # chain while that source is active (inert under LEGACY)
            self._invalidate_downstream(
                scenario_id, LAYOUT_V2_SELECTED_ARTIFACT, LEVEL_ACCESSES_ARTIFACT
            )
        return payload

    def _selected_candidate_policy(
        self, scenario_id: str
    ) -> tuple[DesignCostEvaluator, ClearancePolicy]:
        """The clearance policy the SELECTED layout-v2 candidate was validated
        under in stage 4, rebuilt from the persisted selection identity
        (``candidateId`` + ``layoutRevision``), the catalogue centerline of
        that candidate and the shared search setup
        (``layout.certification.restore_candidate_policy``) — never from the
        in-memory search and never by re-running it (AC-01D); checked
        against the recorded certification (basis, refinement provenance,
        error bound); fails closed on a stale selection or any recipe
        mismatch (Phase 20B.1-v2 1.1). One restore per (world object,
        catalogue revision, selection revision) is cached so a builder chain
        pays it once."""
        selected, catalogue_text, layout_rev, selected_rev = self._selection_snapshot(scenario_id)
        scenario, world = self.worlds.load(scenario_id)
        hit = self._selected_policies.get(scenario_id)
        if (
            hit is not None
            and hit.world is world
            and hit.layout_revision == layout_rev
            and hit.selected_revision == selected_rev
        ):
            return hit.evaluator, hit.policy
        # every shape defect of the persisted documents is the typed 409
        # (never a bare KeyError / TypeError / ValueError → 500)
        certification = CandidateCertification.from_selection(selected)
        try:
            catalogue = json.loads(catalogue_text)
        except ValueError as err:
            raise ClearancePolicyReconstructionError(
                certification.candidate_id,
                f"the catalogue is unreadable ({type(err).__name__})",
            ) from err
        points = candidate_points_from_catalogue(catalogue, certification.candidate_id)
        evaluator, policy, _ = restore_candidate_policy(
            scenario, world, certification=certification, points=points
        )
        # the entry is keyed by the revisions of the SNAPSHOT the policy was
        # rebuilt from, never by a revision read later: a selection written
        # by another request while this restore ran carries a different
        # selected_revision and therefore misses
        self._selected_policies[scenario_id] = _RestoredPolicy(
            world=world,
            candidate_id=certification.candidate_id,
            layout_revision=layout_rev,
            selected_revision=selected_rev,
            evaluator=evaluator,
            policy=policy,
        )
        return evaluator, policy

    def _selection_snapshot(self, scenario_id: str) -> tuple[dict[str, Any], str, str, str]:
        """ONE consistent snapshot of the persisted selection identity — the
        selection document, the catalogue TEXT it is bound to, and the two
        file revisions (catalogue, selection) — read together under the
        per-scenario store lock, the same lock every writer of these files
        holds (``select_layout_candidate``, ``generate_layout_v2``,
        ``_invalidate_downstream``, ``WorldService.invalidate``). Reading them
        separately let a concurrent re-selection interleave between the
        content read and the revision stat, so a policy rebuilt for one
        candidate could be cached under another candidate's revision and
        served on the next request (PR #31 review, TOCTOU). Only the
        snapshot is taken under the lock; the expensive rebuild runs
        outside it. Nothing is retried or repaired: a missing selection is
        ``LayoutV2NotSelectedError``, a selection bound to another catalogue
        revision is ``LayoutSelectionStaleError``, an unreadable catalogue is
        the typed reconstruction error.

        AC-01F: the lock-held snapshot IS ``ArtifactReader.snapshot`` — the
        same observation boundary every other read uses — and the selection's
        validation order (revision → certification → shape) is the resolver's
        table entry, so the AC-01D tamper codes are decided in ONE place."""
        snapshot = self._reader.snapshot(
            scenario_id, [LAYOUT_V2_ARTIFACT, LAYOUT_V2_SELECTED_ARTIFACT]
        )
        read = self._reader.read(snapshot, LAYOUT_V2_SELECTED_ARTIFACT)
        if read.state == "ABSENT":
            raise LayoutV2NotSelectedError(scenario_id)
        if read.error is not None:
            raise read.error
        assert read.raw is not None
        selected = read.raw
        layout_rev = snapshot.revision_of(LAYOUT_V2_ARTIFACT)
        selected_rev = read.revision or ""
        catalogue = snapshot.observation(LAYOUT_V2_ARTIFACT)
        if catalogue is None or not catalogue.present or catalogue.data is None:
            raise ClearancePolicyReconstructionError(
                str(selected.get("candidateId")), "the catalogue is unreadable (OSError)"
            )
        catalogue_text = catalogue.data.decode("utf-8")
        return selected, catalogue_text, layout_rev, selected_rev

    def _active_clearance_policy(self, scenario_id: str, world: SyntheticWorld) -> ClearancePolicy:
        """Clearance policy for every builder downstream of the ACTIVE ramp:
        LEGACY keeps the world's own policy (EXACT for analytic bodies —
        unchanged numerics); LAYOUT_V2 uses the selected candidate's own
        stage-4 certification (Phase 20B.1-v2 1.1 invariant), restored from
        its recipe without the search (AC-01D)."""
        if read_ramp_source(self._reader, scenario_id) != "LAYOUT_V2":
            return clearance_policy_for(world.orebody)
        return self._selected_candidate_policy(scenario_id)[1]

    def layout_selected(self, scenario_id: str) -> dict[str, Any]:
        return self._require_raw(scenario_id, LAYOUT_V2_SELECTED_ARTIFACT)

    def level_accesses(self, scenario_id: str) -> dict[str, Any]:
        return self._require_raw(scenario_id, LEVEL_ACCESSES_ARTIFACT)

    def active_level_accesses(self, scenario_id: str) -> dict[str, Any] | None:
        """The level-access artifact of the ACTIVE ramp: required (and
        present by construction of the selection) for LAYOUT_V2, ``None``
        for LEGACY (Phase 05 segment ends are the level entries).

        This is a READ, and nothing more: the active-source gate, then the
        validated read of the artifact. The co-published selection half is
        observed and compared by the READ SPEC of ``level_accesses.json``
        itself (rule 157 pair check), which classifies a candidate-identity
        or clearance-recipe disagreement as ``LAYOUT_V2_CLEARANCE_MISMATCH``
        and a capture-revision disagreement as ``LAYOUT_V2_SELECTION_STALE``
        (Stage-B checkpoint decision C1). No clearance policy is restored
        here: the four POST builders that NEED one
        (``generate_levels`` / ``generate_shafts`` / ``generate_tunnel`` /
        ``generate_development_mesh``) restore it themselves through
        ``_active_clearance_policy``, and ``generate_network`` /
        ``generate_timeline`` / the two infrastructure builders never needed
        one — a read outcome must not depend on a search-level check."""
        if read_ramp_source(self._reader, scenario_id) != "LAYOUT_V2":
            return None
        return self.level_accesses(scenario_id)

    def _ramp_snapshot(self, scenario_id: str) -> ArtifactSnapshot:
        """ONE observation of ``RAMP_FILES`` (source switch, both owners, the
        catalogue and — since the C5 pair read — the level accesses the
        layout-v2 owner is co-published with), so a resolution and its
        availability flags can never disagree (Stage A R4). The world guard is
        applied to that same observation — a derived artifact is never trusted
        without a VALID world (A1 / Q-WORLD-GUARD; ``require_world`` is the ONE
        definition these routes share with ``_read_bound``) — and never a
        second probe. These two routes have their own guard because they never
        pass through ``_read_bound``; before the AC-01F.2 correction that made
        them the two surfaces that still answered 200 for a world whose
        generation no longer matched the document."""
        self.store.get(scenario_id)  # 404 / schema 422 / migration-on-read (A10)
        snapshot = self._reader.snapshot(scenario_id, RAMP_FILES)
        self._reader.require_world(snapshot)
        return snapshot

    def ramp_source(self, scenario_id: str) -> dict[str, Any]:
        """The Effective Ramp status summary (AC-01F A8, amended by the
        Stage-B checkpoint decision C2).

        An EXPECTED ABSENCE stays ``available: false``. That covers BOTH
        owners, not only the legacy one: LEGACY with no
        ``decline_smoothed.json`` is the normal pre-generation state, and
        LAYOUT_V2 with no ``layout_v2_selected.json`` is reachable through the
        normal API (Stage A §1.3 / §4.3 — ``ramp_source.json`` lies outside
        every cascade, so regenerating the catalogue under an active LAYOUT_V2
        deletes the selection and the level accesses while ``activeSource``
        stays LAYOUT_V2 until the user re-selects). A8's third case assumed
        that state could not be produced; it can, so A8's own principle
        ("expected absence may be unavailable") applies and the answer is
        byte-equal to the pre-AC-01F summary. ``GET …/design/ramp`` still
        answers 409 ``LAYOUT_V2_NOT_SELECTED`` there, and the scene's
        ``rampSource`` slot says exactly what this endpoint says.

        A present-but-INVALID active owner is a different thing and still
        raises its typed error out of the resolution itself: this status
        endpoint must never report ``available: true`` for a ramp every
        builder refuses (Stage A I-11)."""
        return resolve_effective_ramp(self._ramp_snapshot(scenario_id), self._reader).summary()

    def set_ramp_source(self, scenario_id: str, source: RampSource) -> dict[str, Any]:
        """Explicit active-source switch (rule 150). Changing the source
        invalidates every ramp-derived artifact (rule 151) and nothing else;
        LAYOUT_V2 requires a VALID persisted selection.

        AC-01F C3: every guard runs BEFORE the lock is entered and before
        anything is written — a refused switch must leave ``ramp_source.json``
        byte-identical. The guard is therefore no longer atomic with the
        write: a catalogue regeneration landing between the VALID-selection
        check and the lock can leave the switch written with no selection on
        disk — exactly the C2 expected-absence state (``available:false``,
        ``GET …/design/ramp`` 409 LAYOUT_V2_NOT_SELECTED), never a served
        stale ramp. ``require`` takes its own lock-held snapshot, so
        evaluating it inside the write lock also made the reader re-enter the
        RLock for no reason. The world guard is part of ``require`` (a derived
        artifact is never trusted without a world, A1); for the LEGACY
        direction it is applied explicitly, so BOTH directions answer
        ``WORLD_NOT_GENERATED`` on a scenario with no world instead of
        silently writing a switch into an empty ``derived/``."""
        self.store.get(scenario_id)
        if source == "LAYOUT_V2":
            # rule 172 / A8: never ACTIVATE what every downstream builder
            # refuses — the selection must be VALID, not merely present
            self._reader.require(scenario_id, LAYOUT_V2_SELECTED_ARTIFACT)
        else:
            self._reader.require_world(self._reader.snapshot(scenario_id, ()))
        derived = self.store.derived_dir(scenario_id)
        with self.store.lock(scenario_id):
            try:
                current: RampSource | None = read_ramp_source(self._reader, scenario_id)
            except ArtifactMalformedError:
                # A7: an unusable source DIFFERS from every valid one — this
                # explicit write is the repair path, so it proceeds
                current = None
            if current != source:
                write_ramp_source(derived, source)
                # the file just written IS the source: passed explicitly, not
                # re-read (the closure is source-independent either way)
                self._invalidate_downstream(scenario_id, RAMP_SOURCE_FILE, source=source)
        return self.ramp_source(scenario_id)

    def activate_layout_candidate(self, scenario_id: str, candidate_id: str) -> dict[str, Any]:
        selected = self.select_layout_candidate(scenario_id, candidate_id)
        source = self.set_ramp_source(scenario_id, "LAYOUT_V2")
        return {"rampSource": source, "selected": selected}

    def effective_ramp(self, scenario_id: str) -> dict[str, Any]:
        """The ACTIVE Effective Ramp (rule 149): the only ramp geometry the
        downstream builders consume."""
        res = resolve_effective_ramp(self._ramp_snapshot(scenario_id), self._reader)
        if res.payload is None:
            if res.active_source == "LEGACY":
                raise SmoothedNotGeneratedError(scenario_id)
            raise LayoutV2NotSelectedError(scenario_id)
        return res.payload

    # -- level developments (Phase 08, rules 71–74) -------------------------- #

    def levels_path(self, scenario_id: str) -> Path:
        return self.store.derived_dir(scenario_id) / LEVELS_ARTIFACT

    def levels_fingerprint(self, scenario_id: str) -> InputFingerprint:
        return self._fingerprint_of(scenario_id, LEVELS_ARTIFACT)

    def generate_levels(self, scenario_id: str) -> LevelsPayload:
        """Synchronous deterministic analytic geometry (rule 71; rule 60
        reserves async jobs for long-running operations). Regenerating levels
        invalidates the MineNetwork but never the tunnel mesh (rule 74).

        The evaluators are built with the ACTIVE ramp's clearance policy
        (rule 146/172: EXACT for analytic bodies — numerically identical to
        the legacy path — the selected candidate's own stage-4 certification
        under LAYOUT_V2) instead of the exact-only ``self.evaluator``. An
        implicit body develops its levels along the curved
        SECTION_FOOTWALL_OFFSET_TRACE backbone (Phase 20C.2A) — the old
        LEVEL_DEVELOPMENT_UNSUPPORTED_FOR_IMPLICIT_OREBODY boundary exists
        only for entries without curved anchors (typed
        SECTION_TRACE_ANCHORS_REQUIRED)."""
        fingerprint = self.levels_fingerprint(scenario_id)
        smoothed_payload = self.effective_ramp(scenario_id)  # 409 if not available
        accesses_payload = self.active_level_accesses(scenario_id)
        scenario, world = self.worlds.load(scenario_id)
        policy = self._active_clearance_policy(scenario_id, world)
        drift_ev = DesignCostEvaluator(world, scenario.design, clearance=policy)
        crosscut_ev = DesignCostEvaluator(
            world, scenario.design, DesignContext.crosscut(scenario.design), clearance=policy
        )
        source_revision = hashlib.sha256(
            json.dumps(fingerprint.entries, sort_keys=True).encode()
        ).hexdigest()[:16]
        builder = LevelDevelopmentBuilder(scenario, world.orebody, drift_ev, crosscut_ev)
        entries = (
            entries_from_level_accesses(accesses_payload) if accesses_payload is not None else None
        )
        payload = builder.build(smoothed_payload, source_revision, entries=entries)
        serialized = json.dumps(payload.model_dump(mode="json", by_alias=True))
        with self.store.lock(scenario_id):
            if self.levels_fingerprint(scenario_id) != fingerprint:
                raise StaleInputsError(scenario_id)
            path = self.levels_path(scenario_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            publish_text(path, serialized)
            # rules 184 / 74 / 79 / 86 / 92 / 98 / closeout v3 §4: shafts,
            # network (+ capability), stopes, timeline, communication,
            # sensors, development mesh — never the tunnel (rule 74)
            self._invalidate_downstream(scenario_id, LEVELS_ARTIFACT)
        return payload

    def levels(self, scenario_id: str) -> LevelsPayload:
        return self._require_model(scenario_id, LEVELS_ARTIFACT, LevelsPayload)

    # -- stopes (Phase 09, rules 75–80) --------------------------------------- #

    def stopes_path(self, scenario_id: str) -> Path:
        return self.store.derived_dir(scenario_id) / STOPES_ARTIFACT

    def stopes_fingerprint(self, scenario_id: str) -> InputFingerprint:
        return self._fingerprint_of(scenario_id, STOPES_ARTIFACT)

    def generate_stopes(self, scenario_id: str) -> StopesPayload:
        """Synchronous Phase 09 stope generation (rules 75–80): consumes the
        validated levels artifact only, resolves the scenario mining method
        through the explicit strategy factory (rule 78 — unsupported methods
        fail, never silently substitute), and leaves tunnel/network untouched
        (rule 79)."""
        fingerprint = self.stopes_fingerprint(scenario_id)
        levels_payload = self.levels(scenario_id)  # 409 if not generated
        scenario, world, _ = self.evaluator(scenario_id)
        hard_ev = DesignCostEvaluator(
            world, scenario.design, DesignContext.crosscut(scenario.design)
        )
        source_revision = hashlib.sha256(
            json.dumps(fingerprint.entries, sort_keys=True).encode()
        ).hexdigest()[:16]
        strategy = strategy_for(scenario.mining.method)
        if strategy is None:
            payload = unsupported_method_payload(scenario.mining.method, source_revision)
        else:
            payload = strategy.generate(
                scenario,
                world,
                levels_payload.model_dump(mode="json", by_alias=True),
                hard_ev,
                source_revision,
            )
        serialized = json.dumps(payload.model_dump(mode="json", by_alias=True))
        with self.store.lock(scenario_id):
            if self.stopes_fingerprint(scenario_id) != fingerprint:
                raise StaleInputsError(scenario_id)
            path = self.stopes_path(scenario_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            publish_text(path, serialized)
            self._invalidate_downstream(scenario_id, STOPES_ARTIFACT)  # rule 86: timeline
        return payload

    def stopes(self, scenario_id: str) -> StopesPayload:
        return self._require_model(scenario_id, STOPES_ARTIFACT, StopesPayload)

    # -- timeline (Phase 10, rules 81–86) ------------------------------------- #

    def timeline_path(self, scenario_id: str) -> Path:
        return self.store.derived_dir(scenario_id) / TIMELINE_ARTIFACT

    def timeline_fingerprint(self, scenario_id: str) -> InputFingerprint:
        return self._fingerprint_of(scenario_id, TIMELINE_ARTIFACT)

    def generate_timeline(self, scenario_id: str) -> TimelinePayload:
        """Synchronous deterministic precedence-only baseline (rules 81–86):
        the task graph is small, so no async job (rule 60). Regenerating the
        timeline touches NOTHING upstream."""
        fingerprint = self.timeline_fingerprint(scenario_id)
        network_payload = self.network(scenario_id)  # NetworkNotFoundError if absent
        stopes_payload = self.stopes(scenario_id)  # 409 if absent
        smoothed_payload = self.effective_ramp(scenario_id)
        accesses_payload = self.active_level_accesses(scenario_id)
        levels_payload = self.levels(scenario_id)
        shafts_payload = self.shafts_if_present(scenario_id)  # optional (rule 184)
        scenario = self.store.get(scenario_id)
        source_revision = hashlib.sha256(
            json.dumps(fingerprint.entries, sort_keys=True).encode()
        ).hexdigest()[:16]
        builder = MineTimelineBuilder(scenario)
        payload = builder.build(
            network_payload.model_dump(mode="json", by_alias=True),
            stopes_payload.model_dump(mode="json", by_alias=True),
            smoothed_payload,
            levels_payload.model_dump(mode="json", by_alias=True),
            source_revision,
            accesses_payload=accesses_payload,
            shafts_payload=(
                shafts_payload.model_dump(mode="json", by_alias=True)
                if shafts_payload is not None
                else None
            ),
        )
        serialized = json.dumps(payload.model_dump(mode="json", by_alias=True))
        with self.store.lock(scenario_id):
            if self.timeline_fingerprint(scenario_id) != fingerprint:
                raise StaleInputsError(scenario_id)
            path = self.timeline_path(scenario_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            publish_text(path, serialized)
        return payload

    def timeline(self, scenario_id: str) -> TimelinePayload:
        return self._require_model(scenario_id, TIMELINE_ARTIFACT, TimelinePayload)

    # -- mine network (Phase 07, rules 13, 68–70) ---------------------------- #

    def network_path(self, scenario_id: str) -> Path:
        return self.store.derived_dir(scenario_id) / NETWORK_ARTIFACT

    # -- shafts (Phase 20C.2B, rules 182–184) --------------------------------- #

    def shafts_path(self, scenario_id: str) -> Path:
        return self.store.derived_dir(scenario_id) / SHAFTS_ARTIFACT

    def capability_graph_path(self, scenario_id: str) -> Path:
        return self.store.derived_dir(scenario_id) / CAPABILITY_GRAPH_ARTIFACT

    def shafts_fingerprint(self, scenario_id: str) -> InputFingerprint:
        return self._fingerprint_of(scenario_id, SHAFTS_ARTIFACT)

    def generate_shafts(self, scenario_id: str) -> ShaftsPayload:
        """Phase 20C.2B: deterministic vertical shaft planning against the
        validated ``levels.json`` (rule 183). Synchronous (milliseconds).
        Regenerating shafts invalidates the network and everything below it
        (timeline, communication, sensors, capability graph) and nothing
        upstream (rule 184). The evaluators carry the ACTIVE ramp's clearance
        policy (rule 172), like every other downstream builder."""
        fingerprint = self.shafts_fingerprint(scenario_id)
        levels_payload = self.levels(scenario_id)  # 409 if not generated
        levels_revision = file_revision(self.levels_path(scenario_id)) or ""
        scenario, world = self.worlds.load(scenario_id)
        policy = self._active_clearance_policy(scenario_id, world)
        axis_ev = DesignCostEvaluator(
            world, scenario.design, DesignContext.shaft(scenario.design), clearance=policy
        )
        access_ev = DesignCostEvaluator(world, scenario.design, clearance=policy)
        source_revision = hashlib.sha256(
            json.dumps(fingerprint.entries, sort_keys=True).encode()
        ).hexdigest()[:16]
        planner = ShaftPlanner(scenario, world, axis_ev, access_ev)
        payload = planner.build(
            levels_payload.model_dump(mode="json", by_alias=True), source_revision, levels_revision
        )
        serialized = json.dumps(payload.model_dump(mode="json", by_alias=True))
        with self.store.lock(scenario_id):
            if self.shafts_fingerprint(scenario_id) != fingerprint:
                raise StaleInputsError(scenario_id)
            path = self.shafts_path(scenario_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            publish_text(path, serialized)
            # rule 184: shafts → network (+ capability), timeline,
            # communication, sensors — never stopes / development mesh
            self._invalidate_downstream(scenario_id, SHAFTS_ARTIFACT)
        return payload

    def shafts(self, scenario_id: str) -> ShaftsPayload:
        """The persisted shaft artifact. AC-01F closes the Stage A canary
        (I-1): the ``levelsRevision`` the builders compare is now compared
        HERE too, so this route no longer serves 200 what every builder
        refuses with 409 ``SHAFTS_STALE``."""
        return self._require_model(scenario_id, SHAFTS_ARTIFACT, ShaftsPayload)

    def shafts_if_present(self, scenario_id: str) -> ShaftsPayload | None:
        """The shaft artifact for the downstream builders: ``None`` when no
        shaft was generated (shafts are OPTIONAL, rule 184); a persisted
        artifact must belong to the current levels revision (fail closed) —
        the SAME check ``shafts()`` now applies (one authority)."""
        read = self._reader.optional(scenario_id, SHAFTS_ARTIFACT)
        if read is None:
            return None
        if not isinstance(read.model, ShaftsPayload):  # pragma: no cover - declared
            raise ArtifactMalformedError(SHAFTS_ARTIFACT, "does not satisfy ShaftsPayload")
        return read.model

    # -- capability graph (Phase 20C.2B, rule 185) --------------------------- #

    def capability_fingerprint(self, scenario_id: str) -> InputFingerprint:
        return self._fingerprint_of(scenario_id, CAPABILITY_GRAPH_ARTIFACT)

    def generate_capability_graph(self, scenario_id: str) -> CapabilityGraphPayload:
        """Semantic layer over the persisted MineNetwork (rule 185): explicit
        capability assignment, reference / revision validation, required
        capability paths and the egress advisory. Synchronous; touches
        nothing upstream and nothing downstream."""
        fingerprint = self.capability_fingerprint(scenario_id)
        network_payload = self.network(scenario_id)  # NetworkNotFoundError if absent
        shafts_payload = self.shafts_if_present(scenario_id)
        network_revision = file_revision(self.network_path(scenario_id)) or ""
        scenario = self.store.get(scenario_id)
        source_revision = hashlib.sha256(
            json.dumps(fingerprint.entries, sort_keys=True).encode()
        ).hexdigest()[:16]
        payload = CapabilityGraphBuilder(scenario).build(
            network_payload.model_dump(mode="json", by_alias=True),
            shafts_payload.model_dump(mode="json", by_alias=True) if shafts_payload else None,
            source_revision,
            network_revision,
        )
        serialized = json.dumps(payload.model_dump(mode="json", by_alias=True))
        with self.store.lock(scenario_id):
            if self.capability_fingerprint(scenario_id) != fingerprint:
                raise StaleInputsError(scenario_id)
            path = self.capability_graph_path(scenario_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            publish_text(path, serialized)
        return payload

    def capability_graph(self, scenario_id: str) -> CapabilityGraphPayload:
        """The persisted graph, refused (409) when ``network.json`` moved on
        without it — silent reuse of a stale semantic layer is forbidden. The
        recorded ``networkSourceRevision`` is cross-checked against the
        network document of the SAME snapshot as well (AC-01F: the field
        ``capability/models.py`` calls "recorded, cross-checked" was compared
        by nobody)."""
        return self._require_model(scenario_id, CAPABILITY_GRAPH_ARTIFACT, CapabilityGraphPayload)

    # -- design assessment (Phase 20D.3, rule 189) -------------------------- #

    def design_assessment(self, scenario_id: str) -> DesignAssessmentPayload:
        """READ-ONLY projection of the persisted design results into typed
        engineering checks and a candidate comparison (rule 189). ONE
        validated snapshot of the catalogue, the selection (with its
        co-published level accesses, the reader's pair unit), the source
        switch, the network and the capability graph; nothing is generated,
        persisted or recomputed.

        Read semantics (directive §17 / §18): the catalogue is REQUIRED
        (absent → ``LAYOUT_V2_NOT_GENERATED``, the assessment is unavailable
        without a layout-v2 catalogue); the selection and the capability
        graph are OPTIONAL when ABSENT (no selection → the layout checks are
        NOT_EVALUATED; no graph → the capability / egress checks are
        NOT_EVALUATED) but every present artifact must be VALID — a STALE or
        MALFORMED document raises its own typed refusal
        (``LAYOUT_V2_SELECTION_STALE``, ``CAPABILITY_GRAPH_STALE``,
        ``ARTIFACT_MALFORMED``, …) and is never projected."""
        self.store.get(scenario_id)  # 404 / schema 422 / migration-on-read (A10)
        names = (
            LAYOUT_V2_ARTIFACT,
            LAYOUT_V2_SELECTED_ARTIFACT,
            LEVEL_ACCESSES_ARTIFACT,
            RAMP_SOURCE_FILE,
            NETWORK_ARTIFACT,
            CAPABILITY_GRAPH_ARTIFACT,
        )
        snapshot = self._reader.snapshot(scenario_id, names)
        self._reader.require_world(snapshot)
        catalogue = self._reader.read(snapshot, LAYOUT_V2_ARTIFACT)
        if catalogue.state == STATE_ABSENT:
            raise LayoutV2NotGeneratedError(scenario_id)
        if catalogue.error is not None:
            raise catalogue.error
        assert catalogue.raw is not None
        source = self._reader.resolve_ramp_source(snapshot)
        selected = self._optional_read(snapshot, LAYOUT_V2_SELECTED_ARTIFACT)
        # the co-published half is observed by the selection's pair check; its
        # own read is taken so a stale / malformed access artifact refuses too
        self._optional_read(snapshot, LEVEL_ACCESSES_ARTIFACT)
        self._optional_read(snapshot, NETWORK_ARTIFACT)
        capability = self._optional_read(snapshot, CAPABILITY_GRAPH_ARTIFACT)
        capability_payload: CapabilityGraphPayload | None = None
        if capability is not None:
            assert isinstance(capability.model, CapabilityGraphPayload)
            capability_payload = capability.model
        return build_design_assessment(
            catalogue=catalogue.raw,
            selected=None if selected is None else selected.raw,
            capability=capability_payload,
            sources=DesignAssessmentSources(
                active_source=source,
                layout_v2_revision=catalogue.revision,
                selected_layout_revision=None if selected is None else selected.revision,
                level_accesses_revision=self._present_revision(snapshot, LEVEL_ACCESSES_ARTIFACT),
                network_revision=self._present_revision(snapshot, NETWORK_ARTIFACT),
                capability_graph_revision=None if capability is None else capability.revision,
            ),
        )

    def _optional_read(self, snapshot: ArtifactSnapshot, name: str) -> ArtifactRead | None:
        """``ArtifactReader.optional`` over an ALREADY-taken snapshot: ABSENT
        → ``None``, any error → raised, VALID → the read."""
        read = self._reader.read(snapshot, name)
        if read.state == STATE_ABSENT:
            return None
        if read.error is not None:
            raise read.error
        return read

    @staticmethod
    def _present_revision(snapshot: ArtifactSnapshot, name: str) -> str | None:
        obs = snapshot.observation(name)
        return obs.revision if obs is not None and obs.present else None

    def capability_path(
        self, scenario_id: str, source: str, target: str, capability: Capability
    ) -> CapabilityPathQuery:
        """``can_reach(source, target, capability)`` (directive §35): the
        physical answer and the capability-filtered answer, distinct.

        Stage D S2: the ONE read endpoint that needs TWO artifacts reads them
        from ONE snapshot. It used to take two independent
        ``ArtifactReader`` snapshots, and it is not a builder, so no rule-60
        fingerprint re-check could fail it closed: with a
        ``POST …/network/generate`` landing between them the capability
        payload came from the OLD network and the node set from the NEW one,
        and the route answered a bare **500** (``KeyError`` in
        ``capability/builder.py`` building the endpoints). One snapshot is the
        linearization point — the same shape ``_glb`` uses for its two-file
        unit; a non-VALID network raises the NETWORK's own typed error.
        ``READ_SPECS[capability_graph.json].provenance_inputs`` already names
        ``network.json``, so the bytes were in the first snapshot all along
        and were simply discarded."""
        self.store.get(scenario_id)
        cap_read, snapshot = self._reader.require_files(scenario_id, CAPABILITY_GRAPH_ARTIFACT)
        cap = cap_read.model
        if not isinstance(cap, CapabilityGraphPayload):  # pragma: no cover - READ_SPECS declares it
            raise ArtifactMalformedError(
                CAPABILITY_GRAPH_ARTIFACT, "does not satisfy CapabilityGraphPayload"
            )
        network_read = self._reader.read(snapshot, NETWORK_ARTIFACT)
        if network_read.state == "ABSENT":
            raise NetworkNotFoundError(scenario_id)
        if network_read.error is not None:
            raise network_read.error
        network = network_read.model
        if not isinstance(network, NetworkPayload):  # pragma: no cover - READ_SPECS declares it
            raise ArtifactMalformedError(NETWORK_ARTIFACT, "does not satisfy NetworkPayload")
        graph = query_graph_from(
            network.model_dump(mode="json", by_alias=True),
            cap.model_dump(mode="json", by_alias=True),
        )
        for nid in (source, target):
            if nid not in graph.node_ids:
                raise UnknownNetworkNodeError(nid)
        return can_reach(graph, source, target, capability)

    def network_fingerprint(self, scenario_id: str) -> InputFingerprint:
        return self._fingerprint_of(scenario_id, NETWORK_ARTIFACT)

    def generate_network(self, scenario_id: str) -> NetworkPayload:
        """Synchronous full rebuild from smoothed + levels (rule 74: never
        patched from a stale artifact; rule 60 reserves async jobs for
        long-running operations). Sibling branch of the tunnel mesh: neither
        invalidates the other (rule 68)."""
        fingerprint = self.network_fingerprint(scenario_id)
        smoothed_payload = self.effective_ramp(scenario_id)  # 409 if not available
        accesses_payload = self.active_level_accesses(scenario_id)
        levels_payload = self.levels(scenario_id)  # 409 if not generated (rule 74)
        shafts_payload = self.shafts_if_present(scenario_id)  # optional (rule 184)
        scenario = self.store.get(scenario_id)
        source_revision = hashlib.sha256(
            json.dumps(fingerprint.entries, sort_keys=True).encode()
        ).hexdigest()[:16]
        builder = MineNetworkBuilder(scenario)
        result = builder.build(
            smoothed_payload,
            source_revision,
            levels_payload=levels_payload.model_dump(mode="json", by_alias=True),
            geometry_artifact=str(smoothed_payload.get("owningArtifact", LEGACY_RAMP_ARTIFACT)),
            accesses_payload=accesses_payload,
            shafts_payload=(
                shafts_payload.model_dump(mode="json", by_alias=True)
                if shafts_payload is not None
                else None
            ),
        )
        # deterministic serialization of the TYPED contract (rule 69): field
        # order is the model definition order, values are JSON-mode primitives
        serialized = json.dumps(result.payload.model_dump(mode="json", by_alias=True))
        with self.store.lock(scenario_id):
            if self.network_fingerprint(scenario_id) != fingerprint:
                raise StaleInputsError(scenario_id)
            path = self.network_path(scenario_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            publish_text(path, serialized)
            # rules 86 / 92 / 98 / 185: timeline, communication, sensors,
            # capability graph — rebuilt, never patched; shafts kept (rule 184)
            self._invalidate_downstream(scenario_id, NETWORK_ARTIFACT)
        return result.payload

    def network(self, scenario_id: str) -> NetworkPayload:
        return self._require_model(scenario_id, NETWORK_ARTIFACT, NetworkPayload)

    # -- tunnel mesh (Phase 06, rules 65–67) -------------------------------- #

    def tunnel_report_path(self, scenario_id: str) -> Path:
        return self.store.derived_dir(scenario_id) / TUNNEL_MESH_ARTIFACT

    def tunnel_glb_path(self, scenario_id: str) -> Path:
        return self.store.derived_dir(scenario_id) / TUNNEL_MESH_GLB

    def tunnel_commit_path(self, scenario_id: str) -> Path:
        """The INTERNAL mesh commit sidecar (AC-01F.2 correction B3) — never a
        public payload, never registered."""
        return self.store.derived_dir(scenario_id) / mesh_commit_name(TUNNEL_MESH_ARTIFACT)

    def tunnel_fingerprint(self, scenario_id: str) -> InputFingerprint:
        return self._fingerprint_of(scenario_id, TUNNEL_MESH_ARTIFACT)

    def generate_tunnel(
        self, scenario_id: str, on_progress: ProgressCallback = no_progress
    ) -> dict[str, Any]:
        """Phase 06: gravity-aligned sweep of the Phase 05 effective
        centerline (rules 65–67). The fingerprint covers all five upstream
        inputs; persistence follows the locked stale-input protocol
        (rule 60). The GLB is written only on SUCCESS; the report is always
        persisted with an explicit status.

        The sweep evaluator is built with the world's own clearance policy
        (rule 146: EXACT for analytic bodies — the default constructor path
        yields the very same ``ExactClearance``, so TABULAR is numerically
        unchanged — COARSE_CONSERVATIVE for implicit ones) rather than the
        exact-only ``self.evaluator``. Phase 06 does not route a search
        through the hard orebody buffer; it sweeps an ALREADY validated
        centerline and checks the resulting envelope, and under a
        COARSE_CONSERVATIVE policy that envelope check is strictly stricter. Rule
        135 still guards the legacy Hybrid-A* chain, which keeps refusing an
        implicit body at ``/design/targets``."""
        fingerprint = self.tunnel_fingerprint(scenario_id)
        smoothed_payload = self.effective_ramp(scenario_id)  # 409 if not available
        scenario, world = self.worlds.load(scenario_id)
        ev = DesignCostEvaluator(
            world, scenario.design, clearance=self._active_clearance_policy(scenario_id, world)
        )
        builder = TunnelMeshBuilder(ev, scenario.ramp, scenario.tunnel_profile)

        def progress(i: int, n: int, label: str, stage: str) -> None:
            on_progress(
                ProgressEvent(
                    stage=ProgressStage(stage),
                    phase="TUNNEL_MESH",
                    level=min(i + 1, n) if n else 1,
                    total_levels=max(n, 1),
                    candidate=0,
                    total_candidates=0,
                    progress=min(i, n) / n if n else 1.0,
                    expanded_states=0,
                    level_id=label,
                )
            )

        # Phase 20D.1: the level accesses the ACTIVE ramp is co-published
        # with (already a fingerprint input of the tunnel mesh) declare the
        # RAMP_ACCESS turnouts the ramp render mesh opens; LEGACY has none
        result = builder.build(
            smoothed_payload,
            on_progress=progress,
            accesses_payload=self.active_level_accesses(scenario_id),
        )
        payload = dict(result.report)
        if result.glb is not None:
            revision = hashlib.sha256(result.glb).hexdigest()
            payload["artifactRevision"] = revision
            payload["meshUrl"] = (
                f"/api/v1/scenarios/{scenario_id}/design/tunnel/mesh.glb?v={revision[:16]}"
            )
        else:
            payload["artifactRevision"] = None
            payload["meshUrl"] = None
        with self.store.lock(scenario_id):
            if self.tunnel_fingerprint(scenario_id) != fingerprint:
                raise StaleInputsError(scenario_id)
            report_path = self.tunnel_report_path(scenario_id)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            # AC-01F.2 D3, SUCCESS path: GLB FIRST, report second. Two atomic
            # replacements are not one atomic pair, so a crash between them
            # leaves a GLB with no report — the artifact is ABSENT, a stray
            # GLB no reader looks up and the next publish overwrites — never a
            # SUCCESS report whose GLB is missing or stale (ARTIFACT_MALFORMED,
            # the Stage A §7.4 R2 residue).
            #
            # FAILED path: the OTHER order, HEAD's — the FAILED report is
            # published FIRST, and only then is the stale GLB unlinked.
            # Unlinking first would open a window in which a failing report
            # publish leaves the PREVIOUS SUCCESS report beside no GLB: exactly
            # the MALFORMED half D3 exists to avoid, and a 200 scene turned
            # into a 409. Report-then-unlink leaves at worst a FAILED report
            # beside a stale GLB, which the reader already refuses on the
            # binary route and serves as FAILED on the report route.
            glb_path = self.tunnel_glb_path(scenario_id)
            commit_path = self.tunnel_commit_path(scenario_id)
            # AC-01F.2 correction B3: the publication IDENTITY of the pair goes
            # into an INTERNAL sidecar published LAST — never into the report,
            # whose success shape is a public contract. The sidecar's
            # publication is the COMMIT POINT of this mesh generation.
            if result.glb is not None:
                glb_revision = publish_bytes(glb_path, result.glb)
                report_revision = publish_text(report_path, json.dumps(payload))
                _commit_mesh(commit_path, report_revision, glb_revision)
            else:
                report_revision = publish_text(report_path, json.dumps(payload))
                # the record commits the FAILED generation BEFORE the cleanup:
                # a FAILED report has no GLB contract, so unlinking a stale GLB
                # is housekeeping no reader depends on
                _commit_mesh(commit_path, report_revision, None)
                if glb_path.exists():
                    glb_path.unlink()  # never leave a stale GLB beside a FAILED report
        return payload

    # -- development mesh (Phase 20B closeout v3 §4) ------------------------- #

    def development_mesh_report_path(self, scenario_id: str) -> Path:
        return self.store.derived_dir(scenario_id) / DEVELOPMENT_MESH_ARTIFACT

    def development_mesh_glb_path(self, scenario_id: str) -> Path:
        return self.store.derived_dir(scenario_id) / DEVELOPMENT_MESH_GLB

    def development_mesh_commit_path(self, scenario_id: str) -> Path:
        """The INTERNAL mesh commit sidecar (AC-01F.2 correction B3)."""
        return self.store.derived_dir(scenario_id) / mesh_commit_name(DEVELOPMENT_MESH_ARTIFACT)

    def development_mesh_fingerprint(self, scenario_id: str) -> InputFingerprint:
        return self._fingerprint_of(scenario_id, DEVELOPMENT_MESH_ARTIFACT)

    def generate_development_mesh(
        self, scenario_id: str, on_progress: ProgressCallback = no_progress
    ) -> dict[str, Any]:
        """Sweep every LEVEL_ACCESS / DRIFT / CROSSCUT of the owning
        artifacts (``level_accesses.json`` of the ACTIVE ramp, ``levels.json``)
        with the shared profile frame. Requires the levels artifact OR active
        level accesses (409 LEVELS_NOT_GENERATED otherwise); the GLB is
        written only on SUCCESS under the locked stale-input protocol
        (rule 60)."""
        fingerprint = self.development_mesh_fingerprint(scenario_id)
        accesses_payload = self.active_level_accesses(scenario_id)
        try:
            levels_payload: dict[str, Any] | None = self.levels(scenario_id).model_dump(
                mode="json", by_alias=True
            )
        except LevelsNotGeneratedError:
            # an implicit body has no level development yet (Phase 20B
            # boundary): its validated access branches alone are swept
            if accesses_payload is None:
                raise
            levels_payload = None
        scenario, world = self.worlds.load(scenario_id)
        # the drift / access envelope uses the layout clearance policy of the
        # world (EXACT for analytic bodies, COARSE_CONSERVATIVE for implicit ones —
        # rule 146); crosscuts keep their orebody-contact context (rule 72)
        policy = self._active_clearance_policy(scenario_id, world)
        drift_ev = DesignCostEvaluator(
            world,
            scenario.design,
            DesignContext.decline(scenario.design),
            clearance=policy,
        )
        crosscut_ev = DesignCostEvaluator(
            world,
            scenario.design,
            DesignContext.crosscut(scenario.design),
            clearance=policy,
        )
        builder = DevelopmentMeshBuilder(
            drift_ev, crosscut_ev, scenario.ramp, scenario.tunnel_profile
        )

        def progress(i: int, n: int, label: str, stage: str) -> None:
            on_progress(
                ProgressEvent(
                    stage=ProgressStage(stage),
                    phase="DEVELOPMENT_MESH",
                    level=min(i + 1, n) if n else 1,
                    total_levels=max(n, 1),
                    candidate=0,
                    total_candidates=0,
                    progress=min(i, n) / n if n else 1.0,
                    expanded_states=0,
                    level_id=label,
                )
            )

        t0 = time.perf_counter()
        # Phase 20D.1: the active Effective Ramp (a fingerprint input already)
        # is the PARENT of every level access at its turnout
        result = builder.build(
            accesses_payload,
            levels_payload,
            on_progress=progress,
            ramp_payload=self.effective_ramp(scenario_id) if accesses_payload is not None else None,
        )
        payload = dict(result.report)
        payload["generationSeconds"] = time.perf_counter() - t0
        # which owning artifacts actually CONTRIBUTED geometry: a persisted
        # but FAILED levels artifact (e.g. the implicit-orebody Phase 20B
        # boundary) contributes no drift / crosscut
        payload["sources"] = {
            "levelAccesses": accesses_payload is not None,
            "levels": levels_payload is not None and levels_payload.get("status") == "SUCCESS",
            "rampSource": read_ramp_source(self._reader, scenario_id),
        }
        if result.glb is not None:
            revision = hashlib.sha256(result.glb).hexdigest()
            payload["artifactRevision"] = revision
            payload["glbBytes"] = len(result.glb)
            payload["meshUrl"] = (
                f"/api/v1/scenarios/{scenario_id}/design/development-mesh/mesh.glb"
                f"?v={revision[:16]}"
            )
        else:
            payload["artifactRevision"] = None
            payload["glbBytes"] = 0
            payload["meshUrl"] = None
        with self.store.lock(scenario_id):
            if self.development_mesh_fingerprint(scenario_id) != fingerprint:
                raise StaleInputsError(scenario_id)
            report_path = self.development_mesh_report_path(scenario_id)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            # AC-01F.2 D3, exactly as ``generate_tunnel``: on SUCCESS the GLB
            # is published first and the report second; on FAILED the report is
            # published first and only then is the stale GLB unlinked (see the
            # comment there for why the two paths differ)
            glb_path = self.development_mesh_glb_path(scenario_id)
            commit_path = self.development_mesh_commit_path(scenario_id)
            # correction B3, exactly as ``generate_tunnel``
            if result.glb is not None:
                glb_revision = publish_bytes(glb_path, result.glb)
                report_revision = publish_text(report_path, json.dumps(payload))
                _commit_mesh(commit_path, report_revision, glb_revision)
            else:
                report_revision = publish_text(report_path, json.dumps(payload))
                _commit_mesh(commit_path, report_revision, None)
                if glb_path.exists():
                    glb_path.unlink()
        return payload

    def development_mesh(self, scenario_id: str) -> dict[str, Any]:
        return self._require_raw(scenario_id, DEVELOPMENT_MESH_ARTIFACT)

    def development_mesh_glb(self, scenario_id: str) -> bytes:
        return self._glb(
            scenario_id,
            DEVELOPMENT_MESH_ARTIFACT,
            DEVELOPMENT_MESH_GLB,
            DevelopmentMeshNotGeneratedError,
        )

    def tunnel(self, scenario_id: str) -> dict[str, Any]:
        return self._require_raw(scenario_id, TUNNEL_MESH_ARTIFACT)

    def tunnel_glb(self, scenario_id: str) -> bytes:
        return self._glb(
            scenario_id, TUNNEL_MESH_ARTIFACT, TUNNEL_MESH_GLB, TunnelNotGeneratedError
        )

    def _glb(
        self,
        scenario_id: str,
        report_name: str,
        glb_name: str,
        absent_error: type[Exception],
    ) -> bytes:
        """The binary half of a two-file artifact (rule 67).

        The report and the GLB BYTES are observed in ONE snapshot, and the
        report is required VALID — which for a SUCCESS report means its GLB is
        present AND its bytes hash to the report's own ``artifactRevision``
        (the existing content hash, not a new revision semantic). A torn or
        truncated GLB is therefore ``ARTIFACT_MALFORMED``, never a 200
        ``model/gltf-binary`` response the browser caches as ``immutable``
        (Stage A §7.2). The bytes served are the bytes that were hashed."""
        self.store.get(scenario_id)
        read, snapshot = self._reader.require_files(scenario_id, report_name, glb_bytes=True)
        assert read.raw is not None
        if read.raw.get("status") != "SUCCESS":
            raise absent_error(scenario_id)
        obs = snapshot.observation(glb_name)
        if obs is None or not obs.present or obs.data is None:
            raise ArtifactMalformedError(report_name, f"the bytes of '{glb_name}' are unreadable")
        return obs.data

    def decline(self, scenario_id: str) -> dict[str, Any]:
        return self._require_raw(scenario_id, DECLINE_ARTIFACT)

    def targets(self, scenario_id: str) -> dict[str, Any]:
        return self._require_raw(scenario_id, TARGETS_ARTIFACT)
