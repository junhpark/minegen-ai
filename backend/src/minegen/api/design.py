"""Phase 03 design endpoints: cost evaluation probe and access targets."""

from __future__ import annotations

from typing import Annotated, Any, Literal

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
    DevelopmentMeshNotGeneratedError,
    LayoutCandidateInfeasibleError,
    LayoutCandidateNotFoundError,
    LayoutV2NotGeneratedError,
    LayoutV2NotSelectedError,
    LevelAccessesNotGeneratedError,
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


class LayoutCandidateRequest(ApiModel):
    candidate_id: Annotated[str, Field(min_length=1, max_length=120)]


class RampSourceRequest(ApiModel):
    active_source: Literal["LEGACY", "LAYOUT_V2"]


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
    if isinstance(exc, DevelopmentMeshNotGeneratedError):
        return _error(
            status.HTTP_409_CONFLICT,
            "DEVELOPMENT_MESH_NOT_GENERATED",
            f"scenario '{scenario_id}' has no development mesh; "
            "POST …/design/development-mesh first",
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
    if isinstance(exc, LayoutV2NotGeneratedError):
        return _error(
            status.HTTP_409_CONFLICT,
            "LAYOUT_V2_NOT_GENERATED",
            f"scenario '{scenario_id}' has no layout-v2 catalogue; POST …/design/layout-v2 first",
        )
    if isinstance(exc, LayoutV2NotSelectedError):
        return _error(
            status.HTTP_409_CONFLICT,
            "LAYOUT_V2_NOT_SELECTED",
            f"scenario '{scenario_id}' has no selected layout-v2 candidate; "
            "POST …/design/layout-v2/select first",
        )
    if isinstance(exc, LevelAccessesNotGeneratedError):
        return _error(
            status.HTTP_409_CONFLICT,
            "LEVEL_ACCESSES_NOT_GENERATED",
            f"scenario '{scenario_id}' has no level-access artifact; select a layout-v2 "
            "candidate first (POST …/design/layout-v2/select)",
        )
    if isinstance(exc, LayoutCandidateNotFoundError):
        return _error(404, "LAYOUT_V2_CANDIDATE_NOT_FOUND", str(exc))
    if isinstance(exc, LayoutCandidateInfeasibleError):
        return _error(422, "LAYOUT_V2_CANDIDATE_INFEASIBLE", str(exc))
    if isinstance(exc, StaleInputsError):
        return _error(
            status.HTTP_409_CONFLICT,
            "STALE_INPUTS",
            "inputs changed during generation; retry",
        )
    raise exc


def _job_conflict(scenario_id: str, e: JobAlreadyRunningError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=ErrorDetail(
            code="JOB_ALREADY_RUNNING",
            message=f"scenario '{scenario_id}' already has job '{e.job_id}' running",
        ).model_dump(by_alias=True)
        | {"jobId": e.job_id},
    )


# -- Phase 20A: layout-v2 + Effective Ramp (rules 141–152) ------------------- #


@router.post("/layout-v2", status_code=status.HTTP_202_ACCEPTED)
def generate_layout_v2(
    scenario_id: str,
    svc: Service,
    jobs: Jobs,
    response: Response,
    sync: Annotated[
        bool, Query(description="Run inline and return the catalogue (tests/CLI).")
    ] = False,
) -> dict[str, Any]:
    """Parametric whole-mine layout search (Phase 20A): finite family grid
    → cheap evaluation → shortlist → detailed validation → ranking. Async
    job kind ``LAYOUT_V2`` → 202; persisted as ``derived/layout_v2.json``.
    Works for every orebody type (EXACT or CONSERVATIVE clearance)."""
    try:
        svc.worlds.load(scenario_id)
    except (ScenarioNotFoundError, WorldNotGeneratedError) as e:
        raise _guard(scenario_id, e) from e
    if sync:
        response.status_code = status.HTTP_200_OK
        try:
            return svc.generate_layout_v2(scenario_id)
        except StaleInputsError as e:
            raise _error(status.HTTP_409_CONFLICT, e.code, str(e)) from e
    try:
        job = jobs.submit(
            scenario_id,
            "LAYOUT_V2",
            lambda on_progress: svc.generate_layout_v2(scenario_id, on_progress),
        )
    except JobAlreadyRunningError as e:
        raise _job_conflict(scenario_id, e) from e
    return {"jobId": job.id, "status": "QUEUED", "scenarioId": scenario_id, "kind": job.kind}


@router.get("/layout-v2")
def get_layout_v2(scenario_id: str, svc: Service) -> dict[str, Any]:
    try:
        return svc.layout_v2(scenario_id)
    except Exception as exc:
        raise _guard(scenario_id, exc) from exc


@router.post("/layout-v2/select")
def select_layout_candidate(
    scenario_id: str, body: LayoutCandidateRequest, svc: Service
) -> dict[str, Any]:
    """Materialize a FEASIBLE candidate as ``derived/layout_v2_selected.json``
    (the layout-v2 Effective Ramp). Does not change the active source."""
    try:
        return svc.select_layout_candidate(scenario_id, body.candidate_id)
    except Exception as exc:
        raise _guard(scenario_id, exc) from exc


@router.get("/layout-v2/selected")
def get_layout_selected(scenario_id: str, svc: Service) -> dict[str, Any]:
    try:
        return svc.layout_selected(scenario_id)
    except Exception as exc:
        raise _guard(scenario_id, exc) from exc


@router.get("/level-accesses")
def get_level_accesses(scenario_id: str, svc: Service) -> dict[str, Any]:
    """Phase 20B: ramp junctions + level-access branches of the selected
    layout-v2 candidate (``derived/level_accesses.json``, rule 157)."""
    try:
        return svc.level_accesses(scenario_id)
    except Exception as exc:
        raise _guard(scenario_id, exc) from exc


@router.post("/layout-v2/activate")
def activate_layout_candidate(
    scenario_id: str, body: LayoutCandidateRequest, svc: Service
) -> dict[str, Any]:
    """Select the candidate AND make LAYOUT_V2 the active ramp source
    (invalidates every ramp-derived artifact, rule 151)."""
    try:
        return svc.activate_layout_candidate(scenario_id, body.candidate_id)
    except Exception as exc:
        raise _guard(scenario_id, exc) from exc


@router.get("/ramp-source")
def get_ramp_source(scenario_id: str, svc: Service) -> dict[str, Any]:
    try:
        return svc.ramp_source(scenario_id)
    except Exception as exc:
        raise _guard(scenario_id, exc) from exc


@router.put("/ramp-source")
def set_ramp_source(scenario_id: str, body: RampSourceRequest, svc: Service) -> dict[str, Any]:
    """Explicit active-source switch (LEGACY | LAYOUT_V2). LAYOUT_V2 needs a
    persisted selection (409 ``LAYOUT_V2_NOT_SELECTED`` otherwise)."""
    try:
        return svc.set_ramp_source(scenario_id, body.active_source)
    except Exception as exc:
        raise _guard(scenario_id, exc) from exc


@router.get("/ramp")
def get_effective_ramp(scenario_id: str, svc: Service) -> dict[str, Any]:
    """The ACTIVE Effective Ramp in the source-neutral contract."""
    try:
        return svc.effective_ramp(scenario_id)
    except Exception as exc:
        raise _guard(scenario_id, exc) from exc


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
    except (ScenarioNotFoundError, WorldNotGeneratedError, UnsupportedOrebodyError) as e:
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
    persisted smoothed decline (409 ``SMOOTHED_NOT_GENERATED`` otherwise).

    Closeout v5: the precondition is the ACTIVE ramp, NOT the exact-only
    ``svc.evaluator``. Phase 06 sweeps an already validated centerline and
    checks the resulting envelope under the world's own clearance policy, so
    an implicit body gets a real tunnel mesh; ``effective_ramp`` already
    raises the same scenario / world errors. Rule 135 still guards the LEGACY
    Hybrid-A* routes above, which keep the exact-only precondition."""
    try:
        svc.effective_ramp(scenario_id)  # precondition: the ACTIVE ramp exists
    except (
        ScenarioNotFoundError,
        WorldNotGeneratedError,
        TargetsNotGeneratedError,
        DeclineNotGeneratedError,
        SmoothedNotGeneratedError,
        LayoutV2NotSelectedError,
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


@router.post("/development-mesh", status_code=status.HTTP_202_ACCEPTED)
def generate_development_mesh(
    scenario_id: str,
    svc: Service,
    jobs: Jobs,
    response: Response,
    sync: Annotated[
        bool, Query(description="Run inline and return the report (tests/CLI).")
    ] = False,
) -> dict[str, Any]:
    """Phase 20B closeout v3 §4: excavation meshes of every LEVEL_ACCESS /
    DRIFT / CROSSCUT swept on their authoritative centerlines with the shared
    profile frame (CAP / OPEN endpoint policy). Async job kind
    ``DEVELOPMENT_MESH`` → 202; requires the levels artifact
    (409 ``LEVELS_NOT_GENERATED`` otherwise)."""
    try:
        try:
            svc.levels(scenario_id)
        except LevelsNotGeneratedError:
            # implicit bodies: the access branches alone can be swept
            if svc.active_level_accesses(scenario_id) is None:
                raise
    except (ScenarioNotFoundError, WorldNotGeneratedError, LevelsNotGeneratedError) as e:
        raise _guard(scenario_id, e) from e
    if sync:
        response.status_code = status.HTTP_200_OK
        try:
            return svc.generate_development_mesh(scenario_id)
        except StaleInputsError as e:
            raise _error(status.HTTP_409_CONFLICT, e.code, str(e)) from e
    try:
        job = jobs.submit(
            scenario_id,
            "DEVELOPMENT_MESH",
            lambda on_progress: svc.generate_development_mesh(scenario_id, on_progress),
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


@router.get("/development-mesh")
def get_development_mesh(scenario_id: str, svc: Service) -> dict[str, Any]:
    try:
        return svc.development_mesh(scenario_id)
    except (
        ScenarioNotFoundError,
        WorldNotGeneratedError,
        DevelopmentMeshNotGeneratedError,
    ) as e:
        raise _guard(scenario_id, e) from e


@router.get("/development-mesh/mesh.glb")
def get_development_mesh_glb(scenario_id: str, svc: Service) -> Response:
    try:
        data = svc.development_mesh_glb(scenario_id)
    except (
        ScenarioNotFoundError,
        WorldNotGeneratedError,
        DevelopmentMeshNotGeneratedError,
    ) as e:
        raise _guard(scenario_id, e) from e
    return Response(
        content=data,
        media_type="model/gltf-binary",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


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
