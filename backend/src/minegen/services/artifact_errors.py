"""Read-state exceptions of the persisted artifact set (AC-01F).

ONE definition per read-state error, so the validated read authority
(``services/artifact_reader.py``), the services that raise them
(``world_service``, ``design_service``, ``infrastructure_service``) and the
wire mapping (``api/errors.py``) all name the same class object. Every class
below was MOVED here verbatim from its previous module — same name, same base
class, same constructor, same ``str(exc)`` — and gained exactly two class
attributes:

``code``
    the wire code the four router ``_guard`` functions answer for it TODAY
    (``api/design.py:76-209``, ``api/world.py:31-51``, ``api/network.py:41-76``,
    ``api/infrastructure.py:34-74``). The five classes that already carried a
    ``code`` keep theirs unchanged.
``http_status``
    the status those guards answer TODAY. Where the four routers disagree
    (``NETWORK_NOT_GENERATED`` is 404 on ``api/network.py:62-67`` and 409 on
    ``api/design.py:163-168`` / ``api/infrastructure.py:37-42``) the attribute
    records the 409 and ``api/errors.py`` carries the per-router drift row.
    The 404/409 drift itself is RECORDED, not normalized (AC-01F A6 defers it
    to AC-01I).

``design_service`` / ``infrastructure_service`` / ``world_service`` re-export
every name they used to define, so every existing import — and every
``isinstance`` check in the routers and tests — keeps working against the one
class object. ``ClearancePolicyReconstructionError`` is NOT moved: it stays in
``layout/certification.py`` with the AC-01D certification contract.

The four classes at the bottom are NEW (AC-01F A1/A9/A14). Their messages name
FILES, never filesystem paths, and never carry a traceback or an exception
repr: the public detail of a read failure must not leak the server's layout.

This module is a LEAF of the services package: it imports nothing from
``minegen`` at all.
"""

from __future__ import annotations

from typing import Any, ClassVar

__all__ = [
    "ArtifactMalformedError",
    "ArtifactStaleError",
    "CapabilityGraphNotGeneratedError",
    "CapabilityGraphStaleError",
    "CommunicationNotGeneratedError",
    "DeclineNotGeneratedError",
    "DevelopmentMeshNotGeneratedError",
    "LayoutSelectionStaleError",
    "LayoutV2NotGeneratedError",
    "LayoutV2NotSelectedError",
    "LevelAccessesNotGeneratedError",
    "LevelsNotGeneratedError",
    "NetworkNotFoundError",
    "ReadSnapshotChangedError",
    "SceneArtifactInvalidError",
    "SensorsNotGeneratedError",
    "ShaftsNotGeneratedError",
    "ShaftsStaleError",
    "SmoothedNotGeneratedError",
    "StaleInputsError",
    "StopesNotGeneratedError",
    "TargetsNotGeneratedError",
    "TimelineNotGeneratedError",
    "TunnelNotGeneratedError",
    "WorldNotGeneratedError",
    "WorldPublicationStaleError",
    "read_state_code",
]


def read_state_code(exc: Exception) -> str:
    """The wire code of a read-state error. Every class in this module carries
    one as a class attribute; a class that does not is a programming error and
    must fail loudly rather than reach a client as a guessed code."""
    code = getattr(exc, "code", None)
    if not isinstance(code, str) or not code:  # pragma: no cover - defensive
        raise AssertionError(f"{type(exc).__name__} carries no wire code")
    return code


# --------------------------------------------------------------------------- #
# ABSENT — the artifact's fingerprint file does not exist. Expected and quiet:
# ``null`` in the scene, the artifact's own NOT_GENERATED code on its route.
# --------------------------------------------------------------------------- #


class WorldNotGeneratedError(LookupError):
    code: ClassVar[str] = "WORLD_NOT_GENERATED"
    http_status: ClassVar[int] = 409


class TargetsNotGeneratedError(LookupError):
    code: ClassVar[str] = "TARGETS_NOT_GENERATED"
    http_status: ClassVar[int] = 409


class DeclineNotGeneratedError(LookupError):
    code: ClassVar[str] = "DECLINE_NOT_GENERATED"
    http_status: ClassVar[int] = 409


class SmoothedNotGeneratedError(LookupError):
    """decline_smoothed.json does not exist for the scenario."""

    code: ClassVar[str] = "SMOOTHED_NOT_GENERATED"
    http_status: ClassVar[int] = 409

    def __init__(self, scenario_id: str) -> None:
        super().__init__(f"smoothed decline not generated for scenario {scenario_id}")
        self.scenario_id = scenario_id


class LayoutV2NotGeneratedError(LookupError):
    """layout_v2.json does not exist for the scenario."""

    code: ClassVar[str] = "LAYOUT_V2_NOT_GENERATED"
    http_status: ClassVar[int] = 409


class LayoutV2NotSelectedError(LookupError):
    """layout_v2_selected.json does not exist (no candidate selected), or
    LAYOUT_V2 is the active ramp source without a selection."""

    code: ClassVar[str] = "LAYOUT_V2_NOT_SELECTED"
    http_status: ClassVar[int] = 409


class LevelAccessesNotGeneratedError(LookupError):
    """level_accesses.json does not exist for the scenario (Phase 20B)."""

    code: ClassVar[str] = "LEVEL_ACCESSES_NOT_GENERATED"
    http_status: ClassVar[int] = 409


class TunnelNotGeneratedError(LookupError):
    """tunnel_mesh.json does not exist for the scenario."""

    code: ClassVar[str] = "TUNNEL_NOT_GENERATED"
    http_status: ClassVar[int] = 409

    def __init__(self, scenario_id: str) -> None:
        super().__init__(f"tunnel mesh not generated for scenario {scenario_id}")
        self.scenario_id = scenario_id


class DevelopmentMeshNotGeneratedError(LookupError):
    """development_mesh.json does not exist for the scenario."""

    code: ClassVar[str] = "DEVELOPMENT_MESH_NOT_GENERATED"
    http_status: ClassVar[int] = 409


class LevelsNotGeneratedError(LookupError):
    """levels.json does not exist for the scenario."""

    code: ClassVar[str] = "LEVELS_NOT_GENERATED"
    http_status: ClassVar[int] = 409


class ShaftsNotGeneratedError(LookupError):
    """shafts.json does not exist for the scenario (Phase 20C.2B)."""

    #: 404 on ``api/design.py:138-143`` — the recorded 404/409 drift (I-8),
    #: unchanged in AC-01F (A6: normalization is AC-01I)
    code: ClassVar[str] = "SHAFTS_NOT_GENERATED"
    http_status: ClassVar[int] = 404


class CapabilityGraphNotGeneratedError(LookupError):
    """capability_graph.json does not exist for the scenario (Phase 20C.2B)."""

    #: 404 on ``api/design.py:146-152`` — recorded drift, unchanged
    code: ClassVar[str] = "CAPABILITY_GRAPH_NOT_GENERATED"
    http_status: ClassVar[int] = 404


class NetworkNotFoundError(LookupError):
    """network.json does not exist for the scenario."""

    #: 409 on ``api/design.py:163-168`` and ``api/infrastructure.py:37-42``;
    #: 404 on ``api/network.py:62-67`` (recorded drift — the per-router row
    #: lives in ``api/errors.py``)
    code: ClassVar[str] = "NETWORK_NOT_GENERATED"
    http_status: ClassVar[int] = 409


class StopesNotGeneratedError(LookupError):
    """stopes.json does not exist for the scenario."""

    code: ClassVar[str] = "STOPES_NOT_GENERATED"
    http_status: ClassVar[int] = 409


class TimelineNotGeneratedError(LookupError):
    """timeline.json does not exist for the scenario."""

    code: ClassVar[str] = "TIMELINE_NOT_GENERATED"
    http_status: ClassVar[int] = 409


class CommunicationNotGeneratedError(LookupError):
    """communication.json does not exist for the scenario."""

    code: ClassVar[str] = "COMMUNICATION_NOT_GENERATED"
    http_status: ClassVar[int] = 409


class SensorsNotGeneratedError(LookupError):
    """sensors.json does not exist for the scenario."""

    code: ClassVar[str] = "SENSORS_NOT_GENERATED"
    http_status: ClassVar[int] = 409


# --------------------------------------------------------------------------- #
# STALE — present and well-shaped, but a persisted provenance field disagrees
# with the live revision of the upstream file it names.
# --------------------------------------------------------------------------- #


class CapabilityGraphStaleError(RuntimeError):
    """capability_graph.json was built over a different ``network.json``
    revision than the one on disk (rule 185): never silently reused."""

    code: ClassVar[str] = "CAPABILITY_GRAPH_STALE"
    http_status: ClassVar[int] = 409

    def __init__(self, scenario_id: str) -> None:
        super().__init__(
            f"the capability graph of scenario '{scenario_id}' belongs to a previous "
            "network revision; POST …/design/capability-graph again"
        )


class WorldPublicationStaleError(RuntimeError):
    """``arrays.npz`` exists, but ``derived/world.json`` — the world COMMIT
    RECORD (AC-01F.2 correction, B1) — does not commit THIS scenario document
    and THIS ``arrays.npz``.

    It is the *_STALE family in the exact sense of the two above: a published
    product whose own recorded inputs no longer match the live ones. Reachable
    states: a writer died between the document publication and the derived
    invalidation (NEW ``scenario.json`` beside an OLD world, which a fresh
    process previously served as 200), a generation died after publishing
    ``arrays.npz`` and before its record, an input was replaced afterwards, or
    a CROSS-PROCESS reader caught a live writer between the two publications.

    The message therefore does NOT claim that a retry never succeeds — in that
    last case it does — and it is deliberately NOT folded into the scene's
    bounded ``READ_SNAPSHOT_CHANGED`` retry, which exists for inputs that moved
    under ONE reader. The remedy named to the client is the regeneration."""

    code: ClassVar[str] = "WORLD_PUBLICATION_STALE"
    http_status: ClassVar[int] = 409

    def __init__(self, scenario_id: str, detail: str) -> None:
        super().__init__(
            f"the world of scenario '{scenario_id}' is not a committed generation of the "
            f"current document ({detail}); POST …/world/generate"
        )
        self.scenario_id = scenario_id
        self.detail = detail


class ShaftsStaleError(RuntimeError):
    """shafts.json was planned against a different ``levels.json`` revision
    than the one on disk (Phase 20C.2B, rule 184): the network builder
    fails closed instead of welding stations onto moved level nodes."""

    code: ClassVar[str] = "SHAFTS_STALE"
    http_status: ClassVar[int] = 409

    def __init__(self, scenario_id: str) -> None:
        super().__init__(
            f"the shaft artifact of scenario '{scenario_id}' belongs to a previous "
            "level-development revision; POST …/design/shafts again"
        )


class LayoutSelectionStaleError(RuntimeError):
    """``layout_v2_selected.json`` was written for a different layout-v2
    catalogue revision than the one on disk (Phase 20B.1-v2 1.1). The
    downstream builders fail closed rather than rebuild the selected
    candidate's clearance policy from a catalogue it does not belong to."""

    code: ClassVar[str] = "LAYOUT_V2_SELECTION_STALE"
    http_status: ClassVar[int] = 409

    def __init__(self, scenario_id: str, detail: str | None = None) -> None:
        super().__init__(
            f"the selected layout-v2 candidate of scenario '{scenario_id}' belongs to a "
            "previous catalogue revision; re-select or re-activate a candidate"
            + (f" ({detail})" if detail else "")
        )
        self.detail = detail


class StaleInputsError(RuntimeError):
    """The scenario/world/targets revision changed while a design job was
    running (rule 60). The stale result is discarded, never persisted."""

    code: ClassVar[str] = "JOB_INPUTS_CHANGED"
    http_status: ClassVar[int] = 409

    def __init__(self, scenario_id: str) -> None:
        super().__init__(
            f"inputs of scenario '{scenario_id}' changed while the job was running; "
            "the stale result was discarded (regenerate to get a current one)"
        )


# --------------------------------------------------------------------------- #
# NEW in AC-01F (A1 / A9 / A14): the read states that have no code today and
# reach the client as a bare 500 or as silently served junk.
# --------------------------------------------------------------------------- #


class ArtifactMalformedError(RuntimeError):
    """A persisted artifact exists but is not a usable document: unreadable
    bytes, not a JSON object, a failed payload model / first-level shape
    precondition, an incomplete two-file unit, or GLB bytes that disagree
    with the report's content hash. Never served, never ``null`` — the read
    is refused with the artifact's FILE name (never a path)."""

    code: ClassVar[str] = "ARTIFACT_MALFORMED"
    http_status: ClassVar[int] = 409

    def __init__(self, artifact: str, detail: str) -> None:
        super().__init__(f"the persisted artifact '{artifact}' is not usable: {detail}")
        self.artifact = artifact
        self.detail = detail


class ArtifactStaleError(RuntimeError):
    """A persisted artifact is well-shaped but a provenance check against
    another file of the SAME read snapshot failed, and no rule-named stale
    code exists for it (A1: an existing domain-specific error always wins)."""

    code: ClassVar[str] = "ARTIFACT_STALE"
    http_status: ClassVar[int] = 409

    def __init__(self, artifact: str, detail: str) -> None:
        super().__init__(f"the persisted artifact '{artifact}' is stale: {detail}")
        self.artifact = artifact
        self.detail = detail


class SceneArtifactInvalidError(RuntimeError):
    """``GET …/scene`` found at least one present-but-invalid artifact in its
    snapshot (A14). EVERY failure of that snapshot is reported, each as
    ``{artifact, state, code, message}`` — never a filesystem path, never a
    traceback, never an exception repr."""

    code: ClassVar[str] = "SCENE_ARTIFACT_INVALID"
    http_status: ClassVar[int] = 409

    def __init__(self, scenario_id: str, failures: list[dict[str, Any]]) -> None:
        names = ", ".join(str(f.get("artifact")) for f in failures)
        super().__init__(
            f"the scene of scenario '{scenario_id}' cannot be served: "
            f"{len(failures)} artifact(s) are not usable ({names})"
        )
        self.scenario_id = scenario_id
        self.failures = failures


class ReadSnapshotChangedError(RuntimeError):
    """A coherent READ snapshot could not be acquired because the scenario /
    artifact set kept changing (A9). Distinct from ``StaleInputsError``,
    which is a GENERATION whose inputs moved: nothing was built and nothing
    was discarded here — the read is simply retried."""

    code: ClassVar[str] = "READ_SNAPSHOT_CHANGED"
    http_status: ClassVar[int] = 409

    def __init__(self, scenario_id: str, detail: str = "") -> None:
        super().__init__(
            f"a coherent read snapshot of scenario '{scenario_id}' could not be acquired "
            "because its inputs kept changing; retry the read" + (f" ({detail})" if detail else "")
        )
        self.scenario_id = scenario_id
