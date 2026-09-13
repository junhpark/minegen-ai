"""Validated read authority for every persisted derived artifact (AC-01F).

READ ≠ TRUST. One generic read ALGORITHM over a per-artifact SPEC TABLE
(:data:`READ_SPECS`): existence → one lock-held snapshot of bytes + stats →
parse → payload model / first-level shape precondition → provenance agreement
with the OTHER observations of the SAME snapshot → a typed read state.

    ABSENT     the fingerprint file does not exist. Expected and quiet: the
               artifact's own ``*_NOT_GENERATED`` code on its route, ``null``
               in the scene. ``ramp_source.json`` is the ONE artifact with a
               documented absent DEFAULT (``LEGACY``, rule 150).
    VALID      exists, parses to a JSON object, satisfies its model / shape,
               satisfies every provenance check of the same snapshot. A
               ``status: "FAILED"`` payload is VALID — a legitimately
               persisted result.
    STALE      well-shaped, but a persisted provenance field disagrees with
               the live revision of the upstream file it names, or a
               co-published pair disagrees. Never served, never ``null``.
    MALFORMED  present but not a usable document (unreadable bytes, not a
               JSON object, a failed model / shape precondition, an
               incomplete two-file unit, GLB bytes ≠ the report's content
               hash). Never served, never ``null``.

Scope and non-goals, stated because they are contract (AC-01F A12 / §10.2):

* **No new revision semantics.** Every freshness comparison uses
  :func:`minegen.core.revision.file_revision` — the frozen rule-60 stat
  identity — against the relations that EXIST on disk today:
  ``layout_v2_selected.layoutRevision`` ↔ ``layout_v2.json``,
  ``shafts.levelsRevision`` ↔ ``levels.json``,
  ``capabilityGraph.networkRevision`` ↔ ``network.json`` (plus its recorded
  ``networkSourceRevision`` against the network payload's own
  ``sourceRevision``), the selection ↔ level-access agreement, and
  ``development_mesh.sources.rampSource`` against the resolved active source.
* **``sourceRevision`` is NOT a freshness token** and is never compared to a
  recomputed fingerprint (A12): the Effective Ramp fingerprint group expands
  to the INACTIVE owner's files, so a persisted-vs-recomputed mismatch is a
  NORMAL state of a correct artifact. Where persisted evidence cannot prove
  freshness, this reader says nothing about freshness.
* **No read-side mutation**: no repair, no migration, no regeneration, no
  cache. ``ScenarioStore.get``'s Phase 18 migration-on-read is the one
  existing exception to "a read must not write" and is NOT moved here.
* **In-process scope**: ``ScenarioStore.lock`` is a ``threading.RLock``; a
  second process over the same ``data/scenarios`` tree is an unsupported
  deployment and is unchanged by this module.

Layering: this module imports the registry (names, ``files``,
``derived_artifacts``), ``core.artifacts``, ``core.revision``, the eight
``ApiModel`` payloads, ``layout.certification`` and the read-state
exceptions. It imports NOTHING from ``design_service``, ``world_service`` or
``effective_ramp`` — those consume it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from minegen.capability.models import CapabilityGraphPayload
from minegen.core.artifact_registry import derived_artifacts, spec
from minegen.core.artifacts import (
    CAPABILITY_GRAPH_ARTIFACT,
    COMMUNICATION_ARTIFACT,
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
    SENSORS_ARTIFACT,
    SHAFTS_ARTIFACT,
    STOPES_ARTIFACT,
    TARGETS_ARTIFACT,
    TIMELINE_ARTIFACT,
    TUNNEL_MESH_ARTIFACT,
    TUNNEL_MESH_GLB,
    RampSource,
)
from minegen.core.models import ApiModel
from minegen.core.revision import file_revision
from minegen.infrastructure.models import CommunicationPayload, SensorPayload
from minegen.layout.certification import (
    CandidateCertification,
    ClearancePolicyReconstructionError,
)
from minegen.levels.models import LevelsPayload
from minegen.mining.models import StopesPayload
from minegen.network.models import NetworkPayload
from minegen.scheduling.models import TimelinePayload
from minegen.services.artifact_errors import (
    ArtifactMalformedError,
    ArtifactStaleError,
    CapabilityGraphNotGeneratedError,
    CapabilityGraphStaleError,
    CommunicationNotGeneratedError,
    DeclineNotGeneratedError,
    DevelopmentMeshNotGeneratedError,
    LayoutSelectionStaleError,
    LayoutV2NotGeneratedError,
    LayoutV2NotSelectedError,
    LevelAccessesNotGeneratedError,
    LevelsNotGeneratedError,
    NetworkNotFoundError,
    ReadSnapshotChangedError,
    SensorsNotGeneratedError,
    ShaftsNotGeneratedError,
    ShaftsStaleError,
    SmoothedNotGeneratedError,
    StopesNotGeneratedError,
    TargetsNotGeneratedError,
    TimelineNotGeneratedError,
    TunnelNotGeneratedError,
    WorldNotGeneratedError,
)
from minegen.services.scenario_service import ScenarioNotFoundError, ScenarioStore
from minegen.shafts.models import ShaftsPayload

__all__ = [
    "READ_SPECS",
    "ArtifactRead",
    "ArtifactReader",
    "ArtifactSnapshot",
    "FileObservation",
    "ReadSpec",
    "ReadState",
]

ReadState = Literal["ABSENT", "VALID", "STALE", "MALFORMED"]

STATE_ABSENT: ReadState = "ABSENT"
STATE_VALID: ReadState = "VALID"
STATE_STALE: ReadState = "STALE"
STATE_MALFORMED: ReadState = "MALFORMED"

RAMP_SOURCES: tuple[RampSource, ...] = ("LEGACY", "LAYOUT_V2")


# --------------------------------------------------------------------------- #
# Observation DTOs
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FileObservation:
    """ONE stat (+ bytes) observation of one file, taken under the store lock."""

    name: str
    present: bool
    #: ``file_revision(path)``: the rule-60 stat identity, formula unchanged
    revision: str | None
    #: the bytes at that instant (``None`` when absent, and for a GLB unless
    #: the snapshot was asked for GLB bytes)
    data: bytes | None


@dataclass(frozen=True)
class ArtifactSnapshot:
    """Everything a caller asked for, observed under ONE lock hold."""

    scenario_id: str
    #: ``file_revision(scenario.json)`` — ``None`` ⇒ the scenario does not exist
    scenario_revision: str | None
    #: ``file_revision(arrays.npz)`` — ``None`` ⇒ no generated world
    arrays_revision: str | None
    files: Mapping[str, FileObservation]

    def observation(self, file_name: str) -> FileObservation | None:
        return self.files.get(file_name)

    def revision_of(self, file_name: str) -> str:
        """The live revision of an upstream file as the persisted provenance
        fields compare it: ``file_revision(path) or ""`` (an absent file is
        the empty revision — ``DesignService.shafts_if_present`` /
        ``DesignService.capability_graph`` / ``DesignService._selection_snapshot``)."""
        obs = self.files.get(file_name)
        return (obs.revision or "") if obs is not None and obs.present else ""


@dataclass(frozen=True)
class ArtifactRead:
    """The typed outcome of reading ONE artifact out of ONE snapshot."""

    name: str
    state: ReadState
    #: the parsed JSON object (VALID only) — what the scene projects
    raw: dict[str, Any] | None = None
    #: the typed payload (VALID only, for the specs that declare a model)
    model: ApiModel | None = None
    #: the file revision the read was taken at
    revision: str | None = None
    #: the typed read-state exception for STALE / MALFORMED. ``read()`` never
    #: raises it; ``require()`` does.
    error: Exception | None = None


# --------------------------------------------------------------------------- #
# The per-artifact read specification — the ONLY artifact-specific knowledge
# --------------------------------------------------------------------------- #

#: a first-level shape precondition: the defect description, or ``None``
ShapeCheck = Callable[[dict[str, Any]], str | None]
#: an ordered check over the parsed document and the rest of the snapshot:
#: ``(state, exception)`` on failure, ``None`` when it passes
Check = Callable[[dict[str, Any], ArtifactSnapshot], tuple[ReadState, Exception] | None]


@dataclass(frozen=True)
class ReadSpec:
    """What one artifact needs beyond the generic algorithm."""

    name: str
    #: the exception a ``require`` raises when the artifact is ABSENT;
    #: ``None`` only for ``ramp_source.json`` (it has an absent DEFAULT)
    absent_error: Callable[[str], Exception] | None
    #: typed payload model (the eight ``ApiModel`` artifacts)
    model: type[ApiModel] | None = None
    #: first-level structural precondition of a dict-only artifact — the very
    #: subscript its consumers perform today, never a new schema
    shape: ShapeCheck | None = None
    #: ORDERED artifact-specific checks, run after parse + model/shape
    checks: tuple[Check, ...] = ()
    #: UPSTREAM artifacts whose live revision this one records — a registry
    #: DEPENDENCY link (``invalidated_by`` closes over it), observed in the
    #: same snapshot
    provenance_inputs: tuple[str, ...] = ()
    #: CO-PUBLISHED artifacts this one must agree with — not a dependency but
    #: one registry capture (identical ordered ``inputs`` and ramp-source
    #: gate), e.g. the selection ↔ level-access pair of rule 157
    agreement_inputs: tuple[str, ...] = ()
    #: the documented value an ABSENT artifact resolves to (rule 150)
    absent_default: str | None = None


def _is_dict_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, dict) for v in value)


def _shape_any_document(_: dict[str, Any]) -> str | None:
    """No first-level precondition beyond "is a JSON object"."""
    return None


def _shape_decline(data: dict[str, Any]) -> str | None:
    # design/smoothing.py:806 subscripts payload["levels"]
    if not isinstance(data.get("levels"), list):
        return "'levels' is not a list"
    return None


def _shape_smoothed(data: dict[str, Any]) -> str | None:
    # effective_ramp.py legacy_adapter, tunnel_mesh.py, network/builder.py and
    # levels/builder.py all iterate payload["segments"] as dicts
    if not _is_dict_list(data.get("segments")):
        return "'segments' is not a list of objects"
    return None


def _shape_catalogue(data: dict[str, Any]) -> str | None:
    # world_service._layout_summary and certification.candidate_points_from_catalogue
    if not isinstance(data.get("candidates"), list):
        return "'candidates' is not a list"
    return None


def _shape_ramp_source(data: dict[str, Any]) -> str | None:
    source = data.get("activeSource")
    if source not in RAMP_SOURCES:
        return "'activeSource' is not one of LEGACY / LAYOUT_V2"
    return None


def _shape_mesh_report(data: dict[str, Any]) -> str | None:
    status = data.get("status")
    if status not in ("SUCCESS", "FAILED"):
        return "'status' is not one of SUCCESS / FAILED"
    if status == "SUCCESS":
        revision = data.get("artifactRevision")
        if not isinstance(revision, str) or len(revision) != 64:
            return "a SUCCESS report carries no 64-hex 'artifactRevision'"
        try:
            int(revision, 16)
        except ValueError:
            return "a SUCCESS report carries no 64-hex 'artifactRevision'"
        if not isinstance(data.get("meshUrl"), str):
            return "a SUCCESS report carries no 'meshUrl'"
    return None


def _shape_development_mesh_report(data: dict[str, Any]) -> str | None:
    defect = _shape_mesh_report(data)
    if defect is not None:
        return defect
    sources = data.get("sources")
    if not isinstance(sources, dict) or not isinstance(sources.get("rampSource"), str):
        return "'sources.rampSource' is missing"
    return None


def _glb_check(report_name: str, glb_name: str) -> Check:
    """Two-file unit (rule: ``ArtifactSpec.files``): a SUCCESS report requires
    its GLB, and where the snapshot captured the GLB bytes they must hash to
    the report's own ``artifactRevision`` (the existing content hash,
    ``DesignService.generate_tunnel`` / ``DesignService.generate_development_mesh``
    — not a new revision semantic)."""

    def check(
        data: dict[str, Any], snapshot: ArtifactSnapshot
    ) -> tuple[ReadState, Exception] | None:
        if data.get("status") != "SUCCESS":
            return None
        obs = snapshot.observation(glb_name)
        if obs is None:
            return None  # the caller did not ask for the GLB half
        if not obs.present:
            return (
                STATE_MALFORMED,
                ArtifactMalformedError(
                    report_name, f"the report is SUCCESS but '{glb_name}' is missing"
                ),
            )
        if obs.data is not None:
            digest = hashlib.sha256(obs.data).hexdigest()
            if digest != data.get("artifactRevision"):
                return (
                    STATE_MALFORMED,
                    ArtifactMalformedError(
                        report_name,
                        f"the bytes of '{glb_name}' do not hash to the report's 'artifactRevision'",
                    ),
                )
        return None

    return check


def _upstream_revision_check(
    artifact: str, field: str, upstream_file: str, error: Callable[[str], Exception]
) -> Check:
    """A persisted upstream FILE revision compared to the live one — the one
    freshness relation that exists on disk, expressed once per artifact."""

    def check(
        data: dict[str, Any], snapshot: ArtifactSnapshot
    ) -> tuple[ReadState, Exception] | None:
        recorded = data.get(field)
        if recorded != snapshot.revision_of(upstream_file):
            return (STATE_STALE, error(snapshot.scenario_id))
        return None

    return check


def _selection_revision_check(
    data: dict[str, Any], snapshot: ArtifactSnapshot
) -> tuple[ReadState, Exception] | None:
    """A1, fixed order: a parsed selection bound to ANOTHER catalogue revision
    is ``LAYOUT_V2_SELECTION_STALE`` BEFORE any certification check — exactly
    ``DesignService._selection_snapshot``
    (``selected.get("layoutRevision") != layout_rev``, a missing
    ``layoutRevision`` counts as a mismatch)."""
    if data.get("layoutRevision") != snapshot.revision_of(LAYOUT_V2_ARTIFACT):
        return (STATE_STALE, LayoutSelectionStaleError(snapshot.scenario_id))
    return None


def _selection_certification_check(
    data: dict[str, Any], _: ArtifactSnapshot
) -> tuple[ReadState, Exception] | None:
    """A13: every defect of the persisted ``clearance`` block stays the pinned
    ``LAYOUT_V2_CLEARANCE_MISMATCH`` (``CandidateCertification.from_selection``);
    the generic ``ARTIFACT_MALFORMED`` never overwrites it."""
    try:
        CandidateCertification.from_selection(data)
    except ClearancePolicyReconstructionError as err:
        return (STATE_MALFORMED, err)
    return None


def _selection_segments_check(
    data: dict[str, Any], _: ArtifactSnapshot
) -> tuple[ReadState, Exception] | None:
    if not _is_dict_list(data.get("segments")):
        return (
            STATE_MALFORMED,
            ArtifactMalformedError(
                LAYOUT_V2_SELECTED_ARTIFACT, "'segments' is not a list of objects"
            ),
        )
    return None


def _accesses_revision_check(
    data: dict[str, Any], snapshot: ArtifactSnapshot
) -> tuple[ReadState, Exception] | None:
    """A1's fixed SELECTION order, mirrored for the co-published half: a
    document bound to ANOTHER catalogue revision (a missing ``layoutRevision``
    counts as a mismatch, exactly as ``DesignService._selection_snapshot``
    reads the selection) is ``LAYOUT_V2_SELECTION_STALE`` BEFORE any
    certification, shape or pair check."""
    if data.get("layoutRevision") != snapshot.revision_of(LAYOUT_V2_ARTIFACT):
        return (
            STATE_STALE,
            LayoutSelectionStaleError(
                snapshot.scenario_id,
                f"{LEVEL_ACCESSES_ARTIFACT} belongs to another catalogue revision",
            ),
        )
    return None


def _accesses_certification_check(
    data: dict[str, Any], _: ArtifactSnapshot
) -> tuple[ReadState, Exception] | None:
    """``CandidateCertification.from_level_accesses`` — the typed reader the
    AC-01D contract already declares for this document (tests-only until
    AC-01F wires it)."""
    try:
        CandidateCertification.from_level_accesses(data)
    except ClearancePolicyReconstructionError as err:
        return (STATE_MALFORMED, err)
    return None


def _accesses_shape_check(
    data: dict[str, Any], _: ArtifactSnapshot
) -> tuple[ReadState, Exception] | None:
    if not isinstance(data.get("accesses"), list):
        return (
            STATE_MALFORMED,
            ArtifactMalformedError(LEVEL_ACCESSES_ARTIFACT, "'accesses' is not a list"),
        )
    for field in ("layoutRevision", "sourceRevision"):
        if not isinstance(data.get(field), str):
            return (
                STATE_MALFORMED,
                ArtifactMalformedError(LEVEL_ACCESSES_ARTIFACT, f"'{field}' is not a string"),
            )
    return None


def _accesses_pair_check(
    data: dict[str, Any], snapshot: ArtifactSnapshot
) -> tuple[ReadState, Exception] | None:
    """The co-published pair (rule 157): ``level_accesses.json`` is written
    with ``layout_v2_selected.json`` under ONE capture, so an orphaned or
    disagreeing half is a crash residue, never a legitimate state (Stage A
    §7.4 reproduced it and every existing reader served it). The comparison
    is the persisted identity both halves carry — candidate, selection
    revision, catalogue revision and the certification provenance key + error
    bound — never a recomputed fingerprint (A12). The catalogue-revision half
    runs BEFORE this one (:func:`_accesses_revision_check`)."""
    obs = snapshot.observation(LAYOUT_V2_SELECTED_ARTIFACT)
    if obs is None:
        return None  # the caller did not ask for the selection half
    if not obs.present or obs.data is None:
        return (
            STATE_STALE,
            LayoutSelectionStaleError(
                snapshot.scenario_id,
                f"{LEVEL_ACCESSES_ARTIFACT} has no {LAYOUT_V2_SELECTED_ARTIFACT} beside it",
            ),
        )
    try:
        selection = json.loads(obs.data)
    except ValueError:
        selection = None
    if not isinstance(selection, dict):
        return (
            STATE_STALE,
            LayoutSelectionStaleError(
                snapshot.scenario_id,
                f"{LAYOUT_V2_SELECTED_ARTIFACT} is not a usable document",
            ),
        )
    for field in ("candidateId", "sourceRevision", "layoutRevision"):
        if data.get(field) != selection.get(field):
            return (
                STATE_STALE,
                LayoutSelectionStaleError(
                    snapshot.scenario_id,
                    f"{LEVEL_ACCESSES_ARTIFACT} and {LAYOUT_V2_SELECTED_ARTIFACT} "
                    f"disagree on '{field}'",
                ),
            )
    try:
        mine = CandidateCertification.from_level_accesses(data)
        theirs = CandidateCertification.from_selection(selection)
    except ClearancePolicyReconstructionError as err:
        return (STATE_MALFORMED, err)
    if mine.provenance_key != theirs.provenance_key or mine.error_bound != theirs.error_bound:
        return (
            STATE_STALE,
            LayoutSelectionStaleError(
                snapshot.scenario_id,
                f"{LEVEL_ACCESSES_ARTIFACT} and {LAYOUT_V2_SELECTED_ARTIFACT} "
                "disagree on the recorded clearance certification",
            ),
        )
    return None


def _capability_network_source_check(
    data: dict[str, Any], snapshot: ArtifactSnapshot
) -> tuple[ReadState, Exception] | None:
    """``capabilityGraph.networkSourceRevision`` is the network payload's own
    ``sourceRevision`` recorded at build time (``capability/models.py:126``,
    "recorded, cross-checked" — cross-checked by nobody today). It is
    compared to the PERSISTED field of the network document in the same
    snapshot, never to a recomputed fingerprint (A12)."""
    obs = snapshot.observation(NETWORK_ARTIFACT)
    if obs is None or not obs.present or obs.data is None:
        return None  # the network half is not in this snapshot / not present
    try:
        network = json.loads(obs.data)
    except ValueError:
        return None  # the network's own read reports its MALFORMED state
    if not isinstance(network, dict) or "sourceRevision" not in network:
        return None
    if data.get("networkSourceRevision") != network.get("sourceRevision"):
        return (STATE_STALE, CapabilityGraphStaleError(snapshot.scenario_id))
    return None


def _development_mesh_source_check(
    data: dict[str, Any], snapshot: ArtifactSnapshot
) -> tuple[ReadState, Exception] | None:
    """``development_mesh.sources.rampSource`` was recorded at build time
    (``DesignService.generate_development_mesh``) and is re-checked against
    the resolved active source: a switch would have DELETED the mesh
    (rule 151), so a mismatch is residue. No rule-named stale code exists for
    it → ``ARTIFACT_STALE``."""
    obs = snapshot.observation(RAMP_SOURCE_FILE)
    if obs is None:
        return None  # the caller did not ask for the ramp source
    active: str | None
    if not obs.present:
        active = "LEGACY"  # rule 150: the documented absent default
    elif obs.data is None:
        return None
    else:
        try:
            document = json.loads(obs.data)
        except ValueError:
            document = None
        active = document.get("activeSource") if isinstance(document, dict) else None
        if active not in RAMP_SOURCES:
            return (
                STATE_STALE,
                ArtifactStaleError(
                    DEVELOPMENT_MESH_ARTIFACT,
                    f"the active ramp source cannot be resolved ('{RAMP_SOURCE_FILE}' "
                    "is not usable)",
                ),
            )
    sources = data.get("sources")
    recorded = sources.get("rampSource") if isinstance(sources, dict) else None
    if recorded != active:
        return (
            STATE_STALE,
            ArtifactStaleError(
                DEVELOPMENT_MESH_ARTIFACT,
                f"it was swept under ramp source '{recorded}' while '{active}' is active",
            ),
        )
    return None


def _spec(name: str, **kwargs: Any) -> ReadSpec:
    return ReadSpec(name=name, **kwargs)


#: ONE entry per registered derived artifact (``derived_artifacts()``), keyed
#: by its fingerprint file name. Everything artifact-specific is a TABLE ENTRY
#: here, never a branch in the algorithm.
READ_SPECS: Mapping[str, ReadSpec] = {
    # -- legacy Phase 03–05 chain: no persisted upstream revision exists, so
    #    no freshness claim is made (A12 — honest, not a gap)
    TARGETS_ARTIFACT: _spec(
        TARGETS_ARTIFACT,
        absent_error=TargetsNotGeneratedError,
        shape=_shape_any_document,
    ),
    DECLINE_ARTIFACT: _spec(
        DECLINE_ARTIFACT,
        absent_error=DeclineNotGeneratedError,
        shape=_shape_decline,
    ),
    LEGACY_RAMP_ARTIFACT: _spec(
        LEGACY_RAMP_ARTIFACT,
        absent_error=SmoothedNotGeneratedError,
        shape=_shape_smoothed,
    ),
    # -- layout-v2 catalogue, selection, accesses, source switch ------------ #
    LAYOUT_V2_ARTIFACT: _spec(
        LAYOUT_V2_ARTIFACT,
        absent_error=LayoutV2NotGeneratedError,
        shape=_shape_catalogue,
    ),
    LAYOUT_V2_SELECTED_ARTIFACT: _spec(
        LAYOUT_V2_SELECTED_ARTIFACT,
        absent_error=LayoutV2NotSelectedError,
        # A1 fixes the ORDER: revision (STALE) → certification (MISMATCH) →
        # the generic shape precondition
        checks=(
            _selection_revision_check,
            _selection_certification_check,
            _selection_segments_check,
        ),
        provenance_inputs=(LAYOUT_V2_ARTIFACT,),
    ),
    LEVEL_ACCESSES_ARTIFACT: _spec(
        LEVEL_ACCESSES_ARTIFACT,
        absent_error=LevelAccessesNotGeneratedError,
        # the SAME A1 order as the selection above, mirrored for the
        # co-published half: revision (STALE) → certification (MISMATCH) →
        # shape → pair agreement with the VALID selection (STALE)
        checks=(
            _accesses_revision_check,
            _accesses_certification_check,
            _accesses_shape_check,
            _accesses_pair_check,
        ),
        provenance_inputs=(LAYOUT_V2_ARTIFACT,),
        agreement_inputs=(LAYOUT_V2_SELECTED_ARTIFACT,),
    ),
    RAMP_SOURCE_FILE: _spec(
        RAMP_SOURCE_FILE,
        absent_error=None,  # the ONE documented absent default (rule 150)
        shape=_shape_ramp_source,
        absent_default="LEGACY",
    ),
    # -- sweeps (two-file units) -------------------------------------------- #
    TUNNEL_MESH_ARTIFACT: _spec(
        TUNNEL_MESH_ARTIFACT,
        absent_error=TunnelNotGeneratedError,
        shape=_shape_mesh_report,
        checks=(_glb_check(TUNNEL_MESH_ARTIFACT, TUNNEL_MESH_GLB),),
    ),
    DEVELOPMENT_MESH_ARTIFACT: _spec(
        DEVELOPMENT_MESH_ARTIFACT,
        absent_error=DevelopmentMeshNotGeneratedError,
        shape=_shape_development_mesh_report,
        checks=(
            _glb_check(DEVELOPMENT_MESH_ARTIFACT, DEVELOPMENT_MESH_GLB),
            _development_mesh_source_check,
        ),
        provenance_inputs=(RAMP_SOURCE_FILE,),
    ),
    # -- typed payloads ------------------------------------------------------ #
    LEVELS_ARTIFACT: _spec(
        LEVELS_ARTIFACT, absent_error=LevelsNotGeneratedError, model=LevelsPayload
    ),
    SHAFTS_ARTIFACT: _spec(
        SHAFTS_ARTIFACT,
        absent_error=ShaftsNotGeneratedError,
        model=ShaftsPayload,
        checks=(
            _upstream_revision_check(
                SHAFTS_ARTIFACT, "levelsRevision", LEVELS_ARTIFACT, ShaftsStaleError
            ),
        ),
        provenance_inputs=(LEVELS_ARTIFACT,),
    ),
    STOPES_ARTIFACT: _spec(
        STOPES_ARTIFACT, absent_error=StopesNotGeneratedError, model=StopesPayload
    ),
    TIMELINE_ARTIFACT: _spec(
        TIMELINE_ARTIFACT, absent_error=TimelineNotGeneratedError, model=TimelinePayload
    ),
    COMMUNICATION_ARTIFACT: _spec(
        COMMUNICATION_ARTIFACT,
        absent_error=CommunicationNotGeneratedError,
        model=CommunicationPayload,
    ),
    SENSORS_ARTIFACT: _spec(
        SENSORS_ARTIFACT, absent_error=SensorsNotGeneratedError, model=SensorPayload
    ),
    NETWORK_ARTIFACT: _spec(
        NETWORK_ARTIFACT, absent_error=NetworkNotFoundError, model=NetworkPayload
    ),
    CAPABILITY_GRAPH_ARTIFACT: _spec(
        CAPABILITY_GRAPH_ARTIFACT,
        absent_error=CapabilityGraphNotGeneratedError,
        model=CapabilityGraphPayload,
        checks=(
            _upstream_revision_check(
                CAPABILITY_GRAPH_ARTIFACT,
                "networkRevision",
                NETWORK_ARTIFACT,
                CapabilityGraphStaleError,
            ),
            _capability_network_source_check,
        ),
        provenance_inputs=(NETWORK_ARTIFACT,),
    ),
}


# --------------------------------------------------------------------------- #
# The reader
# --------------------------------------------------------------------------- #


class ArtifactReader:
    """The ONE read authority over ``data/scenarios/{id}/derived/``.

    ``snapshot()`` is the ONLY method that touches the file system, and it
    does so inside ``with store.lock(sid)`` — the same per-scenario lock every
    writer holds across its write + cascade. Nothing is parsed, validated or
    constructed inside the lock; ``read()`` is a PURE function of the captured
    bytes."""

    def __init__(self, store: ScenarioStore) -> None:
        self.store = store

    # -- snapshot (the only filesystem access) ----------------------------- #

    def snapshot(
        self,
        scenario_id: str,
        names: Iterable[str] | None = None,
        *,
        expect_scenario_revision: str | None = None,
        expect_arrays_revision: str | None = None,
        glb_bytes: bool = False,
    ) -> ArtifactSnapshot:
        """Observe ``scenario.json``, ``arrays.npz`` and the files of every
        requested ARTIFACT under one lock hold.

        ``names=None`` observes every registered derived artifact
        (``derived_artifacts()``, which includes ``ramp_source.json``), each
        expanded through ``ArtifactSpec.files`` so a two-file unit is one
        observation pair. JSON files are captured with their bytes; a GLB is
        stat-only unless ``glb_bytes`` is set (the GLB route serves the bytes
        anyway and hashes them against the report).

        ``expect_scenario_revision`` / ``expect_arrays_revision`` bind the
        snapshot to an earlier observation of the scenario document / world
        arrays: a mismatch means the inputs moved under the reader and raises
        ``ReadSnapshotChangedError`` (A9) — never ``StaleInputsError``, which
        is a GENERATION whose inputs moved."""
        requested = self._files_of(names)
        observations: dict[str, FileObservation] = {}
        derived = self.store.derived_dir(scenario_id)
        with self.store.lock(scenario_id):
            scenario_revision = file_revision(self.store.scenario_path(scenario_id))
            arrays_revision = file_revision(self.store.arrays_path(scenario_id))
            for file_name in requested:
                want_bytes = file_name.endswith(".json") or glb_bytes
                observations[file_name] = self._observe(derived / file_name, want_bytes)
        if expect_scenario_revision is not None and scenario_revision != expect_scenario_revision:
            raise ReadSnapshotChangedError(scenario_id, "scenario.json changed")
        if expect_arrays_revision is not None and arrays_revision != expect_arrays_revision:
            raise ReadSnapshotChangedError(scenario_id, "arrays.npz changed")
        return ArtifactSnapshot(
            scenario_id=scenario_id,
            scenario_revision=scenario_revision,
            arrays_revision=arrays_revision,
            files=observations,
        )

    @staticmethod
    def _observe(path: Path, want_bytes: bool) -> FileObservation:
        revision = file_revision(path)
        if revision is None:
            return FileObservation(path.name, False, None, None)
        data: bytes | None = None
        if want_bytes:
            try:
                data = path.read_bytes()
            except FileNotFoundError:
                # it vanished between the stat and the read: ABSENT is the
                # honest observation, never half a document
                return FileObservation(path.name, False, None, None)
            except OSError:
                # present but UNREADABLE (permissions, I/O): the file exists,
                # so ABSENT would be a lie — ``read`` reports it MALFORMED
                return FileObservation(path.name, True, revision, None)
        return FileObservation(path.name, True, revision, data)

    @staticmethod
    def _files_of(names: Iterable[str] | None) -> tuple[str, ...]:
        specs = derived_artifacts() if names is None else tuple(spec(n) for n in names)
        files: list[str] = []
        for artifact in specs:
            for file in artifact.files:
                if file.name not in files:
                    files.append(file.name)
        return tuple(files)

    # -- read (pure over the snapshot) -------------------------------------- #

    def read(self, snapshot: ArtifactSnapshot, name: str) -> ArtifactRead:
        """Classify ONE artifact of ``snapshot``. Never touches the file
        system and never raises the read-state exception — it is carried in
        ``ArtifactRead.error`` so a caller (the scene) can collect them all."""
        read_spec = READ_SPECS[name]
        obs = snapshot.observation(name)
        if obs is None:
            raise KeyError(f"'{name}' was not observed by this snapshot")
        if not obs.present:
            return ArtifactRead(name=name, state=STATE_ABSENT)
        if obs.data is None:
            return self._malformed(name, obs, "its bytes could not be read")
        try:
            document = json.loads(obs.data)
        except ValueError as err:
            return self._malformed(name, obs, f"invalid JSON ({type(err).__name__})")
        if not isinstance(document, dict):
            return self._malformed(
                name, obs, f"not a JSON object (it is a {type(document).__name__})"
            )
        if read_spec.model is not None:
            try:
                model: ApiModel | None = read_spec.model.model_validate(document)
            except (ValidationError, TypeError) as err:
                return self._malformed(
                    name, obs, f"does not satisfy {read_spec.model.__name__} ({_first_line(err)})"
                )
        else:
            model = None
        if read_spec.shape is not None:
            defect = read_spec.shape(document)
            if defect is not None:
                return self._malformed(name, obs, defect)
        for check in read_spec.checks:
            outcome = check(document, snapshot)
            if outcome is not None:
                state, error = outcome
                return ArtifactRead(name=name, state=state, revision=obs.revision, error=error)
        return ArtifactRead(
            name=name, state=STATE_VALID, raw=document, model=model, revision=obs.revision
        )

    @staticmethod
    def _malformed(name: str, obs: FileObservation, detail: str) -> ArtifactRead:
        return ArtifactRead(
            name=name,
            state=STATE_MALFORMED,
            revision=obs.revision,
            error=ArtifactMalformedError(name, detail),
        )

    # -- require / optional ------------------------------------------------- #

    def require(self, scenario_id: str, name: str) -> ArtifactRead:
        """The VALID artifact, or the typed refusal. Guard order (A1 / Q-WORLD-
        GUARD): ``ScenarioNotFoundError`` → ``WorldNotGeneratedError`` → the
        artifact's own ABSENT error → MALFORMED → STALE."""
        read = self._read_bound(scenario_id, name)
        if read.state == STATE_ABSENT:
            raise self._absent_error(scenario_id, name)
        if read.error is not None:
            raise read.error
        return read

    def optional(self, scenario_id: str, name: str) -> ArtifactRead | None:
        """``None`` when the artifact is ABSENT (a legitimately optional
        artifact, rule 184), otherwise :meth:`require`'s contract."""
        read = self._read_bound(scenario_id, name)
        if read.state == STATE_ABSENT:
            return None
        if read.error is not None:
            raise read.error
        return read

    def _read_bound(self, scenario_id: str, name: str) -> ArtifactRead:
        read_spec = READ_SPECS[name]
        names = (name, *read_spec.provenance_inputs, *read_spec.agreement_inputs)
        snapshot = self.snapshot(scenario_id, names)
        if snapshot.scenario_revision is None:
            raise ScenarioNotFoundError(scenario_id)
        if snapshot.arrays_revision is None:
            # derived artifacts are never trusted without a world (A1)
            raise WorldNotGeneratedError(scenario_id)
        return self.read(snapshot, name)

    @staticmethod
    def _absent_error(scenario_id: str, name: str) -> Exception:
        absent_error = READ_SPECS[name].absent_error
        if absent_error is None:
            raise ValueError(
                f"'{name}' has a documented absent default "
                f"({READ_SPECS[name].absent_default}); read it through resolve_ramp_source"
            )
        return absent_error(scenario_id)

    # -- the one absent DEFAULT (rule 150) ---------------------------------- #

    def resolve_ramp_source(self, snapshot: ArtifactSnapshot) -> RampSource:
        """The active ramp source of a snapshot: ABSENT → ``LEGACY`` (the
        documented rule-150 default — LEGACY IS the absence of the file);
        present but not a usable document → ``ArtifactMalformedError`` (A7:
        never a silent LEGACY)."""
        read = self.read(snapshot, RAMP_SOURCE_FILE)
        if read.state == STATE_ABSENT:
            return "LEGACY"
        if read.error is not None:
            raise read.error
        assert read.raw is not None
        source = read.raw["activeSource"]
        assert source in RAMP_SOURCES
        return source  # type: ignore[no-any-return]


def _first_line(err: Exception) -> str:
    """A one-line, path-free summary of a validation failure: the public
    detail of a read refusal never carries a traceback, a filesystem path or
    an exception repr (A14)."""
    text = str(err).strip().splitlines()
    return text[0] if text else type(err).__name__
