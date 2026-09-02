"""Phase 03 design endpoints: cost evaluation probe and access targets."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import Field

from minegen.api.deps import get_design_service, get_job_service
from minegen.core.models import ApiModel, ErrorDetail
from minegen.levels.models import LevelsPayload
from minegen.mining.models import StopesPayload
from minegen.scheduling.models import TimelinePayload
from minegen.services.design_service import (
    DeclineNotGeneratedError,
    DesignService,
    LevelsNotGeneratedError,
    NetworkNotFoundError,
    SmoothedNotGeneratedError,
    StaleInputsError,
    StopesNotGeneratedError,
    TargetsNotGeneratedError,
    TimelineNotGeneratedError,
    TunnelNotGeneratedError,
    UnsupportedOrebodyError,
)
from minegen.services.job_service import JobAlreadyRunningError, JobService
from minegen.services.scenario_service import ScenarioNotFoundError
from minegen.services.world_service import (
    WorldArtifactIncompatibleError,
    WorldNotGeneratedError,
)

router = APIRouter(prefix="/scenarios/{scenario_id}/design", tags=["design"])

Service = Annotated[DesignService, Depends(get_design_service)]
Jobs = Annotated[JobService, Depends(get_job_service)]


class EvaluateRequest(ApiModel):
    points: Annotated[list[list[float]], Field(min_length=1, max_length=200_000)]


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=ErrorDetail(code=code, message=message).model_dump(by_alias=True),
    )


def _guard(scenario_id: str, exc: Exception) -> HTTPException:
    if isinstance(exc, UnsupportedOrebodyError):
        return _error(
            422,
            "UNSUPPORTED_OREBODY_FOR_LEGACY_LAYOUT",
            f"orebody type '{exc}' is valid for Phase 17 world generation, but the "
            "current legacy decline/access layout supports TABULAR orebodies only; "
            "generalized mine layout is deferred to Phase 20 (Parametric Layout "
            "Family Search)",
        )
    if isinstance(exc, ScenarioNotFoundError):
        return _error(404, "SCENARIO_NOT_FOUND", f"scenario '{scenario_id}' does not exist")
    if isinstance(exc, WorldArtifactIncompatibleError):
        return _error(
            status.HTTP_409_CONFLICT,
            "WORLD_ARTIFACT_INCOMPATIBLE",
            f"scenario '{scenario_id}' has a world artifact from an older schema "
            f"({exc}); POST …/world/generate to regenerate it",
        )
    if isinstance(exc, WorldNotGeneratedError):
        return _error(
            status.HTTP_409_CONFLICT,
            "WORLD_NOT_GENERATED",
            f"scenario '{scenario_id}' has no generated world; POST …/world/generate first",
        )
    if isinstance(exc, TargetsNotGeneratedError):
        return _error(
            status.HTTP_409_CONFLICT,
            "TARGETS_NOT_GENERATED",
            f"scenario '{scenario_id}' has no access targets; POST …/design/targets first",
        )
    if isinstance(exc, DeclineNotGeneratedError):
        return _error(
            status.HTTP_409_CONFLICT,
            "DECLINE_NOT_GENERATED",
            f"scenario '{scenario_id}' has no decline; POST …/design/decline first",
        )
    if isinstance(exc, SmoothedNotGeneratedError):
        return _error(
            status.HTTP_409_CONFLICT,
            "SMOOTHED_NOT_GENERATED",
            f"scenario '{scenario_id}' has no smoothed decline; POST …/design/decline/smooth first",
        )
    if isinstance(exc, TunnelNotGeneratedError):
        return _error(
            status.HTTP_409_CONFLICT,
            "TUNNEL_NOT_GENERATED",
            f"scenario '{scenario_id}' has no tunnel mesh; POST …/design/tunnel first",
        )
    if isinstance(exc, LevelsNotGeneratedError):
        return _error(
            status.HTTP_409_CONFLICT,
            "LEVELS_NOT_GENERATED",
            f"scenario '{scenario_id}' has no level developments; POST …/design/levels first",
        )
    if isinstance(exc, StopesNotGeneratedError):
        return _error(
            status.HTTP_409_CONFLICT,
            "STOPES_NOT_GENERATED",
            f"scenario '{scenario_id}' has no planned stopes; POST …/design/stopes first",
        )
    if isinstance(exc, NetworkNotFoundError):
        return _error(
            status.HTTP_409_CONFLICT,
            "NETWORK_NOT_GENERATED",
            f"scenario '{scenario_id}' has no MineNetwork; POST …/network/generate first",
        )
    if isinstance(exc, TimelineNotGeneratedError):
        return _error(
            status.HTTP_409_CONFLICT,
            "TIMELINE_NOT_GENERATED",
            f"scenario '{scenario_id}' has no timeline; POST …/design/timeline first",
        )
    if isinstance(exc, StaleInputsError):
        return _error(
            status.HTTP_409_CONFLICT,
            "STALE_INPUTS",
            "inputs changed during generation; retry",
        )
    raise exc


@router.post("/levels")
def generate_levels(scenario_id: str, svc: Service) -> LevelsPayload:
    """Phase 08 (rules 71–74): synchronous deterministic level developments."""
    try:
        return svc.generate_levels(scenario_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise _guard(scenario_id, exc) from exc


@router.get("/levels")
def get_levels(scenario_id: str, svc: Service) -> LevelsPayload:
    try:
        return svc.levels(scenario_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise _guard(scenario_id, exc) from exc


@router.post("/stopes")
def generate_stopes(scenario_id: str, svc: Service) -> StopesPayload:
    """Phase 09 (rules 75–80): synchronous planned-stope generation."""
    try:
        return svc.generate_stopes(scenario_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise _guard(scenario_id, exc) from exc


@router.get("/stopes")
def get_stopes(scenario_id: str, svc: Service) -> StopesPayload:
    try:
        return svc.stopes(scenario_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise _guard(scenario_id, exc) from exc


@router.post("/timeline")
def generate_timeline(scenario_id: str, svc: Service) -> TimelinePayload:
    """Phase 10 (rules 81–86): synchronous deterministic timeline baseline."""
    try:
        return svc.generate_timeline(scenario_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise _guard(scenario_id, exc) from exc


@router.get("/timeline")
def get_timeline(scenario_id: str, svc: Service) -> TimelinePayload:
    try:
        return svc.timeline(scenario_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise _guard(scenario_id, exc) from exc


@router.post("/cost/evaluate")
def evaluate_cost(scenario_id: str, body: EvaluateRequest, svc: Service) -> dict[str, Any]:
    if any(len(p) != 3 for p in body.points):
        raise _error(422, "VALIDATION_ERROR", "every point must have exactly 3 coordinates")
    try:
        return svc.evaluate(scenario_id, body.points)
    except (ScenarioNotFoundError, WorldNotGeneratedError) as e:
        raise _guard(scenario_id, e) from e


@router.post("/targets")
def generate_targets(scenario_id: str, svc: Service) -> dict[str, Any]:
    try:
        return svc.generate_targets(scenario_id)
    except (ScenarioNotFoundError, WorldNotGeneratedError, UnsupportedOrebodyError) as e:
        raise _guard(scenario_id, e) from e


@router.get("/targets")
def get_targets(scenario_id: str, svc: Service) -> dict[str, Any]:
    try:
        return svc.targets(scenario_id)
    except (ScenarioNotFoundError, WorldNotGeneratedError, TargetsNotGeneratedError) as e:
        raise _guard(scenario_id, e) from e


@router.post("/decline", status_code=status.HTTP_202_ACCEPTED)
def generate_decline(
    scenario_id: str,
    svc: Service,
    jobs: Jobs,
    response: Response,
    max_levels: Annotated[int | None, Query(ge=1, le=200, alias="maxLevels")] = None,
    sync: Annotated[
        bool, Query(description="Run inline and return the result (tests/CLI).")
    ] = False,
) -> dict[str, Any]:
    """Chained Hybrid-A* decline (raw centerline, Phase 04).

    Default: submit an asynchronous job → ``202 {jobId, status}``; poll
    ``GET /jobs/{jobId}`` or subscribe to ``/ws/jobs/{jobId}``. The result is
    also persisted to ``derived/decline.json`` and served by ``GET …/decline``.
    ``?sync=true`` runs inline (≈ 30 s for the default scenario)."""
    # validate preconditions up front so the caller gets 404/409 immediately
    try:
        svc.evaluator(scenario_id)
        svc._targets_object(scenario_id)
    except (ScenarioNotFoundError, WorldNotGeneratedError, TargetsNotGeneratedError) as e:
        raise _guard(scenario_id, e) from e
    if sync:
        response.status_code = status.HTTP_200_OK
        try:
            return svc.generate_decline(scenario_id, max_levels)
        except StaleInputsError as e:
            raise _error(status.HTTP_409_CONFLICT, e.code, str(e)) from e
    try:
        job = jobs.submit(
            scenario_id,
            "DECLINE",
            lambda on_progress: svc.generate_decline(scenario_id, max_levels, on_progress),
        )
    except JobAlreadyRunningError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ErrorDetail(
                code="JOB_ALREADY_RUNNING",
                message=f"scenario '{scenario_id}' already has job '{e.job_id}' running",
            ).model_dump(by_alias=True)
            | {"jobId": e.job_id},
        ) from e
    return {
        "jobId": job.id,
        "status": "QUEUED",  # as submitted; the pool may already be running it
        "scenarioId": scenario_id,
        "kind": job.kind,
    }


@router.get("/decline")
def get_decline(scenario_id: str, svc: Service) -> dict[str, Any]:
    try:
        return svc.decline(scenario_id)
    except (ScenarioNotFoundError, WorldNotGeneratedError, DeclineNotGeneratedError) as e:
        raise _guard(scenario_id, e) from e


@router.post("/decline/smooth", status_code=status.HTTP_202_ACCEPTED)
def smooth_decline(
    scenario_id: str,
    svc: Service,
    jobs: Jobs,
    response: Response,
    sync: Annotated[
        bool, Query(description="Run inline and return the result (tests/CLI).")
    ] = False,
) -> dict[str, Any]:
    """Phase 05: smooth + fully revalidate the persisted decline (rules 61–64).

    Default: submit an asynchronous job (kind ``SMOOTH``) → ``202 {jobId,
    status}``. The result is persisted to ``derived/decline_smoothed.json``
    and served by ``GET …/decline/smooth``. Requires an existing decline
    (409 ``DECLINE_NOT_GENERATED`` otherwise)."""
    try:
        svc.evaluator(scenario_id)
        svc.decline(scenario_id)  # precondition: raw decline must exist
    except (
        ScenarioNotFoundError,
        WorldNotGeneratedError,
        TargetsNotGeneratedError,
        DeclineNotGeneratedError,
    ) as e:
        raise _guard(scenario_id, e) from e
    if sync:
        response.status_code = status.HTTP_200_OK
        try:
            return svc.generate_smoothed(scenario_id)
        except StaleInputsError as e:
            raise _error(status.HTTP_409_CONFLICT, e.code, str(e)) from e
    try:
        job = jobs.submit(
            scenario_id,
            "SMOOTH",
            lambda on_progress: svc.generate_smoothed(scenario_id, on_progress),
        )
    except JobAlreadyRunningError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ErrorDetail(
                code="JOB_ALREADY_RUNNING",
                message=f"scenario '{scenario_id}' already has job '{e.job_id}' running",
            ).model_dump(by_alias=True)
            | {"jobId": e.job_id},
        ) from e
    return {
        "jobId": job.id,
        "status": "QUEUED",
        "scenarioId": scenario_id,
        "kind": job.kind,
    }


@router.get("/decline/smooth")
def get_smoothed_decline(scenario_id: str, svc: Service) -> dict[str, Any]:
    try:
        return svc.smoothed(scenario_id)
    except (
        ScenarioNotFoundError,
        WorldNotGeneratedError,
        SmoothedNotGeneratedError,
    ) as e:
        raise _guard(scenario_id, e) from e


@router.post("/tunnel", status_code=status.HTTP_202_ACCEPTED)
def generate_tunnel(
    scenario_id: str,
    svc: Service,
    jobs: Jobs,
    response: Response,
    sync: Annotated[
        bool, Query(description="Run inline and return the report (tests/CLI).")
    ] = False,
) -> dict[str, Any]:
    """Phase 06: gravity-aligned tunnel sweep of the Phase 05 effective
    centerline (rules 65–67). Async job kind ``MESH`` → 202; requires a
    persisted smoothed decline (409 ``SMOOTHED_NOT_GENERATED`` otherwise)."""
    try:
        svc.evaluator(scenario_id)
        svc.smoothed(scenario_id)  # precondition
    except (
        ScenarioNotFoundError,
        WorldNotGeneratedError,
        TargetsNotGeneratedError,
        DeclineNotGeneratedError,
        SmoothedNotGeneratedError,
    ) as e:
        raise _guard(scenario_id, e) from e
    if sync:
        response.status_code = status.HTTP_200_OK
        try:
            return svc.generate_tunnel(scenario_id)
        except StaleInputsError as e:
            raise _error(status.HTTP_409_CONFLICT, e.code, str(e)) from e
    try:
        job = jobs.submit(
            scenario_id,
            "MESH",
            lambda on_progress: svc.generate_tunnel(scenario_id, on_progress),
        )
    except JobAlreadyRunningError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ErrorDetail(
                code="JOB_ALREADY_RUNNING",
                message=f"scenario '{scenario_id}' already has job '{e.job_id}' running",
            ).model_dump(by_alias=True)
            | {"jobId": e.job_id},
        ) from e
    return {
        "jobId": job.id,
        "status": "QUEUED",
        "scenarioId": scenario_id,
        "kind": job.kind,
    }


@router.get("/tunnel")
def get_tunnel(scenario_id: str, svc: Service) -> dict[str, Any]:
    try:
        return svc.tunnel(scenario_id)
    except (
        ScenarioNotFoundError,
        WorldNotGeneratedError,
        TunnelNotGeneratedError,
    ) as e:
        raise _guard(scenario_id, e) from e


@router.get("/tunnel/mesh.glb")
def get_tunnel_glb(scenario_id: str, svc: Service) -> Response:
    """Binary glTF artifact; the report's ``meshUrl`` carries a
    revision-busting ``?v=`` query (rule 67)."""
    try:
        data = svc.tunnel_glb(scenario_id)
    except (
        ScenarioNotFoundError,
        WorldNotGeneratedError,
        TunnelNotGeneratedError,
    ) as e:
        raise _guard(scenario_id, e) from e
    return Response(
        content=data,
        media_type="model/gltf-binary",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
