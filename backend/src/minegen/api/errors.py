"""ONE wire mapping for every typed service error (AC-01F).

At HEAD ``12d7725`` each router carried its own ``_guard`` isinstance ladder
(``api/design.py:76-209``, ``api/world.py:31-51``, ``api/network.py:41-76``,
``api/infrastructure.py:34-74``) with its own status, its own message text and
its own fall-through — which is why the same ``ShaftsStaleError`` was a typed
409 on ``/network/generate`` and a 500 ``INTERNAL_ERROR`` on
``/infrastructure/communication`` (Stage A I-6), and why a read-state failure
had no code at all.

This module is that ladder ONCE:

    code   = the exception's ``code`` class attribute, or the explicit
             ordered type ladder below for the classes that carry none
    status = ``STATUS_BY_CODE[code]``, per-router drift in ``ROUTER_OVERRIDES``
    body   = ``ErrorDetail(code, message)`` (``core/models.py``), plus
             ``artifacts[]`` for the scene aggregate (A14)

**Characterization, not normalization.** Every row below is transcribed from a
router body at HEAD ``12d7725`` with its ``file:line`` provenance, so wiring
this table (AC-01F commit 2) reproduces today's status AND today's message on
each router. The two deliberate exceptions are named at their rows:

* ``NETWORK_NOT_GENERATED`` is 404 on ``api/network.py:62-67`` and 409 on the
  other two routers — the recorded 404/409 drift (I-8), kept as a per-router
  override because AC-01F A6 defers normalization to AC-01I;
* ``StaleInputsError`` answers the literal ``STALE_INPUTS`` on three routers
  today while the very same exception answers its canonical
  ``JOB_INPUTS_CHANGED`` on the five ``?sync=true`` branches
  (``api/design.py:249``) and on the async job path
  (``job_service.py:111``). A9 approves the canonical code everywhere; the
  literal it replaces is recorded — with every other router answer at HEAD —
  in the literal oracle table of ``tests/test_api_errors.py``.

WIRED from AC-01F commit 2: the four routers call ``guard`` through their own
``_fail`` and carry no ladder of their own any more. The oracle that proved
the move did not change a wire answer is the LITERAL table in
``tests/test_api_errors.py``, transcribed row by row from the four ladders as
they stood at HEAD ``12d7725`` (with ``file:line`` provenance per row) — the
AC-01E frozen-census pattern, never live dead code kept in the router.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from fastapi import HTTPException

from minegen.core.models import ErrorDetail
from minegen.layout.certification import ClearancePolicyReconstructionError
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
    SceneArtifactInvalidError,
    SensorsNotGeneratedError,
    ShaftsNotGeneratedError,
    ShaftsStaleError,
    SmoothedNotGeneratedError,
    StaleInputsError,
    StopesNotGeneratedError,
    TargetsNotGeneratedError,
    TimelineNotGeneratedError,
    TunnelNotGeneratedError,
    WorldNotGeneratedError,
    WorldPublicationStaleError,
)
from minegen.services.design_service import (
    LayoutCandidateInfeasibleError,
    LayoutCandidateNotFoundError,
    UnknownNetworkNodeError,
    UnsupportedOrebodyError,
)
from minegen.services.scenario_service import ScenarioNotFoundError
from minegen.services.world_service import WorldArtifactIncompatibleError

__all__ = [
    "CODE_LADDER",
    "ERRORS",
    "ROUTERS",
    "ROUTER_OVERRIDES",
    "ErrorSpec",
    "code_of",
    "guard",
]

ROUTER_DESIGN: Final = "design"
ROUTER_WORLD: Final = "world"
ROUTER_NETWORK: Final = "network"
ROUTER_INFRASTRUCTURE: Final = "infrastructure"
ROUTERS: Final[tuple[str, ...]] = (
    ROUTER_DESIGN,
    ROUTER_WORLD,
    ROUTER_NETWORK,
    ROUTER_INFRASTRUCTURE,
)


@dataclass(frozen=True)
class ErrorSpec:
    """What one wire code answers. ``message=None`` means ``str(exc)`` — the
    exception carries its own human message (every ``code``-bearing class does
    and so does every AC-01F read-state error); otherwise the literal template
    the router builds today, with ``{scenario_id}`` / ``{exc}`` placeholders."""

    status: int
    message: str | None = None
    #: where this row was transcribed from
    source: str = ""

    def detail(self, scenario_id: str, exc: Exception) -> str:
        if self.message is None:
            return str(exc)
        return self.message.format(scenario_id=scenario_id, exc=exc)


#: the isinstance ladder of ``api/design.py::_guard`` at HEAD ``12d7725`` (its
#: ORDER decides which row wins for a subclass —
#: ``WorldArtifactIncompatibleError`` before its base
#: ``WorldNotGeneratedError``), extended with the infrastructure-only classes
#: and the AC-01F read-state errors.
CODE_LADDER: Final[tuple[tuple[type[Exception], str], ...]] = (
    (UnsupportedOrebodyError, "UNSUPPORTED_OREBODY_FOR_LEGACY_LAYOUT"),
    (ScenarioNotFoundError, "SCENARIO_NOT_FOUND"),
    (WorldArtifactIncompatibleError, "WORLD_ARTIFACT_INCOMPATIBLE"),
    (WorldNotGeneratedError, "WORLD_NOT_GENERATED"),
    # AC-01F.2 correction (B1): NOT a subclass of WorldNotGeneratedError, so
    # this row's position is documentation, not precedence
    (WorldPublicationStaleError, "WORLD_PUBLICATION_STALE"),
    (TargetsNotGeneratedError, "TARGETS_NOT_GENERATED"),
    (DeclineNotGeneratedError, "DECLINE_NOT_GENERATED"),
    (SmoothedNotGeneratedError, "SMOOTHED_NOT_GENERATED"),
    (TunnelNotGeneratedError, "TUNNEL_NOT_GENERATED"),
    (DevelopmentMeshNotGeneratedError, "DEVELOPMENT_MESH_NOT_GENERATED"),
    (LevelsNotGeneratedError, "LEVELS_NOT_GENERATED"),
    (ShaftsNotGeneratedError, "SHAFTS_NOT_GENERATED"),
    (ShaftsStaleError, "SHAFTS_STALE"),
    (CapabilityGraphNotGeneratedError, "CAPABILITY_GRAPH_NOT_GENERATED"),
    (CapabilityGraphStaleError, "CAPABILITY_GRAPH_STALE"),
    (UnknownNetworkNodeError, "UNKNOWN_NETWORK_NODE"),
    (StopesNotGeneratedError, "STOPES_NOT_GENERATED"),
    (NetworkNotFoundError, "NETWORK_NOT_GENERATED"),
    (TimelineNotGeneratedError, "TIMELINE_NOT_GENERATED"),
    (LayoutV2NotGeneratedError, "LAYOUT_V2_NOT_GENERATED"),
    (LayoutV2NotSelectedError, "LAYOUT_V2_NOT_SELECTED"),
    (LevelAccessesNotGeneratedError, "LEVEL_ACCESSES_NOT_GENERATED"),
    (LayoutSelectionStaleError, "LAYOUT_V2_SELECTION_STALE"),
    (ClearancePolicyReconstructionError, "LAYOUT_V2_CLEARANCE_MISMATCH"),
    (LayoutCandidateNotFoundError, "LAYOUT_V2_CANDIDATE_NOT_FOUND"),
    (LayoutCandidateInfeasibleError, "LAYOUT_V2_CANDIDATE_INFEASIBLE"),
    (StaleInputsError, "JOB_INPUTS_CHANGED"),
    # infrastructure-only rows (api/infrastructure.py:55-67)
    (SensorsNotGeneratedError, "SENSORS_NOT_GENERATED"),
    (CommunicationNotGeneratedError, "COMMUNICATION_NOT_GENERATED"),
    # AC-01F read states (A1 / A9 / A14) — new codes, all 409
    (ArtifactMalformedError, "ARTIFACT_MALFORMED"),
    (ArtifactStaleError, "ARTIFACT_STALE"),
    (SceneArtifactInvalidError, "SCENE_ARTIFACT_INVALID"),
    (ReadSnapshotChangedError, "READ_SNAPSHOT_CHANGED"),
)

#: status + message per wire code, transcribed from the router bodies at HEAD
ERRORS: Final[dict[str, ErrorSpec]] = {
    "UNSUPPORTED_OREBODY_FOR_LEGACY_LAYOUT": ErrorSpec(
        422,
        "orebody type '{exc}' is valid for Phase 17 world generation, but the "
        "current legacy decline/access layout supports TABULAR orebodies only; "
        "generalized mine layout is deferred to Phase 20 (Parametric Layout "
        "Family Search)",
        "api/design.py:77-85",
    ),
    "SCENARIO_NOT_FOUND": ErrorSpec(
        404,
        "scenario '{scenario_id}' does not exist",
        "api/design.py:86-87, world.py:32-37, network.py:42-43, infrastructure.py:35-36",
    ),
    "WORLD_ARTIFACT_INCOMPATIBLE": ErrorSpec(
        409,
        "scenario '{scenario_id}' has a world artifact from an older schema "
        "({exc}); POST …/world/generate to regenerate it",
        "api/design.py:88-94, world.py:38-44",
    ),
    "WORLD_NOT_GENERATED": ErrorSpec(
        409,
        "scenario '{scenario_id}' has no generated world; POST …/world/generate first",
        "api/design.py:95-100, world.py:45-50, network.py:44-49",
    ),
    "WORLD_PUBLICATION_STALE": ErrorSpec(409, None, "AC-01F.2 correction B1"),
    "TARGETS_NOT_GENERATED": ErrorSpec(
        409,
        "scenario '{scenario_id}' has no access targets; POST …/design/targets first",
        "api/design.py:101-106",
    ),
    "DECLINE_NOT_GENERATED": ErrorSpec(
        409,
        "scenario '{scenario_id}' has no decline; POST …/design/decline first",
        "api/design.py:107-112",
    ),
    "SMOOTHED_NOT_GENERATED": ErrorSpec(
        409,
        "scenario '{scenario_id}' has no smoothed decline; POST …/design/decline/smooth first",
        "api/design.py:113-118, network.py:50-55",
    ),
    "TUNNEL_NOT_GENERATED": ErrorSpec(
        409,
        "scenario '{scenario_id}' has no tunnel mesh; POST …/design/tunnel first",
        "api/design.py:119-124",
    ),
    "DEVELOPMENT_MESH_NOT_GENERATED": ErrorSpec(
        409,
        "scenario '{scenario_id}' has no development mesh; POST …/design/development-mesh first",
        "api/design.py:125-131",
    ),
    "LEVELS_NOT_GENERATED": ErrorSpec(
        409,
        "scenario '{scenario_id}' has no level developments; POST …/design/levels first",
        "api/design.py:132-137, network.py:56-61",
    ),
    "SHAFTS_NOT_GENERATED": ErrorSpec(
        404,  # recorded 404/409 drift (I-8), unchanged — AC-01I owns it
        "scenario '{scenario_id}' has no shaft artifact; POST …/design/shafts first",
        "api/design.py:138-143",
    ),
    "SHAFTS_STALE": ErrorSpec(409, None, "api/design.py:144-145, network.py:74-75"),
    "CAPABILITY_GRAPH_NOT_GENERATED": ErrorSpec(
        404,  # recorded 404/409 drift (I-8), unchanged
        "scenario '{scenario_id}' has no capability graph; POST …/design/capability-graph first",
        "api/design.py:146-152",
    ),
    "CAPABILITY_GRAPH_STALE": ErrorSpec(409, None, "api/design.py:153-154"),
    "UNKNOWN_NETWORK_NODE": ErrorSpec(422, None, "api/design.py:155-156"),
    "STOPES_NOT_GENERATED": ErrorSpec(
        409,
        "scenario '{scenario_id}' has no planned stopes; POST …/design/stopes first",
        "api/design.py:157-162",
    ),
    "NETWORK_NOT_GENERATED": ErrorSpec(
        409,  # 404 on api/network.py — see ROUTER_OVERRIDES
        "scenario '{scenario_id}' has no MineNetwork; POST …/network/generate first",
        "api/design.py:163-168, infrastructure.py:37-42",
    ),
    "TIMELINE_NOT_GENERATED": ErrorSpec(
        409,
        "scenario '{scenario_id}' has no timeline; POST …/design/timeline first",
        "api/design.py:169-174",
    ),
    "LAYOUT_V2_NOT_GENERATED": ErrorSpec(
        409,
        "scenario '{scenario_id}' has no layout-v2 catalogue; POST …/design/layout-v2 first",
        "api/design.py:175-180",
    ),
    "LAYOUT_V2_NOT_SELECTED": ErrorSpec(
        409,
        "scenario '{scenario_id}' has no selected layout-v2 candidate; "
        "POST …/design/layout-v2/select first",
        "api/design.py:181-187",
    ),
    "LEVEL_ACCESSES_NOT_GENERATED": ErrorSpec(
        409,
        "scenario '{scenario_id}' has no level-access artifact; select a layout-v2 "
        "candidate first (POST …/design/layout-v2/select)",
        "api/design.py:188-194",
    ),
    "LAYOUT_V2_SELECTION_STALE": ErrorSpec(409, None, "api/design.py:195-196"),
    "LAYOUT_V2_CLEARANCE_MISMATCH": ErrorSpec(409, None, "api/design.py:197-198"),
    "LAYOUT_V2_CANDIDATE_NOT_FOUND": ErrorSpec(404, None, "api/design.py:199-200"),
    "LAYOUT_V2_CANDIDATE_INFEASIBLE": ErrorSpec(422, None, "api/design.py:201-202"),
    # A9: the canonical code of the exception (``StaleInputsError.code``), the
    # one the five ?sync=true branches (api/design.py:249) and the async job
    # path (job_service.py:111) already answer. ``message=None`` = ``str(exc)``,
    # which REPLACES three per-router literals recorded verbatim in
    # ``tests/test_api_errors.py::STALE_INPUTS_MESSAGES_REPLACED``:
    #   design         "inputs changed during generation; retry"
    #   network        "network inputs changed during generation; retry"
    #   infrastructure "inputs changed while generating; retry"
    "JOB_INPUTS_CHANGED": ErrorSpec(409, None, "api/design.py:248-249 (sync), A9"),
    "SENSORS_NOT_GENERATED": ErrorSpec(
        409,
        "scenario '{scenario_id}' has no sensor plan; POST …/infrastructure/sensors first",
        "api/infrastructure.py:55-60",
    ),
    "COMMUNICATION_NOT_GENERATED": ErrorSpec(
        409,
        "scenario '{scenario_id}' has no communication plan; "
        "POST …/infrastructure/communication first",
        "api/infrastructure.py:61-67",
    ),
    "ARTIFACT_MALFORMED": ErrorSpec(409, None, "AC-01F A1"),
    "ARTIFACT_STALE": ErrorSpec(409, None, "AC-01F A1"),
    "SCENE_ARTIFACT_INVALID": ErrorSpec(409, None, "AC-01F A14"),
    "READ_SNAPSHOT_CHANGED": ErrorSpec(409, None, "AC-01F A9"),
}

#: the per-router drift that stays (A6): a router row REPLACES the base row.
ROUTER_OVERRIDES: Final[dict[str, dict[str, ErrorSpec]]] = {
    ROUTER_NETWORK: {
        "NETWORK_NOT_GENERATED": ErrorSpec(
            404,
            "scenario '{scenario_id}' has no network; POST …/network/generate first",
            "api/network.py:62-67",
        ),
    },
    ROUTER_INFRASTRUCTURE: {
        "SMOOTHED_NOT_GENERATED": ErrorSpec(
            409,
            "scenario '{scenario_id}' has no smoothed decline; POST …/design/smooth first",
            "api/infrastructure.py:43-48",
        ),
        "LEVELS_NOT_GENERATED": ErrorSpec(
            409,
            "scenario '{scenario_id}' has no levels; POST …/design/levels first",
            "api/infrastructure.py:49-54",
        ),
    },
}


def code_of(exc: Exception) -> str | None:
    """The wire code of an exception, or ``None`` when no router maps it (the
    fall-through: ``raise exc`` — a bare 500 with no ``detail.code``)."""
    for exc_type, code in CODE_LADDER:
        if isinstance(exc, exc_type):
            return code
    return None


def error_response(status_code: int, code: str, message: str, **extra: Any) -> HTTPException:
    detail: dict[str, Any] = ErrorDetail(code=code, message=message).model_dump(by_alias=True)
    detail.update(extra)
    return HTTPException(status_code=status_code, detail=detail)


def guard(scenario_id: str, exc: Exception, *, router: str) -> HTTPException | None:
    """The wire answer for a typed service error, or ``None`` when nothing
    maps it — the caller then re-raises (the three routers' ``raise exc``).

    ``router`` selects the recorded per-router drift (A6) and is REQUIRED with
    no default: a wiring that forgets it must fail loudly (``TypeError``)
    rather than silently normalize ``api/network.py``'s 404
    ``NETWORK_NOT_GENERATED`` into the design router's 409, which A6 defers to
    AC-01I."""
    code = code_of(exc)
    if code is None:
        return None
    spec = ROUTER_OVERRIDES.get(router, {}).get(code, ERRORS[code])
    if isinstance(exc, SceneArtifactInvalidError):
        # A14: every invalid artifact of the SAME snapshot, each as
        # {artifact, state, code, message} — never a path, never a traceback
        return error_response(
            spec.status, code, spec.detail(scenario_id, exc), artifacts=list(exc.failures)
        )
    return error_response(spec.status, code, spec.detail(scenario_id, exc))
