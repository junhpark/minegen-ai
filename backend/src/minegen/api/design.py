"""Phase 03 design endpoints: cost evaluation probe and access targets."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import Field

from minegen.api.deps import get_design_service
from minegen.core.models import ApiModel, ErrorDetail
from minegen.services.design_service import (
    DeclineNotGeneratedError,
    DesignService,
    TargetsNotGeneratedError,
)
from minegen.services.scenario_service import ScenarioNotFoundError
from minegen.services.world_service import WorldNotGeneratedError

router = APIRouter(prefix="/scenarios/{scenario_id}/design", tags=["design"])

Service = Annotated[DesignService, Depends(get_design_service)]


class EvaluateRequest(ApiModel):
    points: Annotated[list[list[float]], Field(min_length=1, max_length=200_000)]


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=ErrorDetail(code=code, message=message).model_dump(by_alias=True),
    )


def _guard(scenario_id: str, exc: Exception) -> HTTPException:
    if isinstance(exc, ScenarioNotFoundError):
        return _error(404, "SCENARIO_NOT_FOUND", f"scenario '{scenario_id}' does not exist")
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
    raise exc


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
    except (ScenarioNotFoundError, WorldNotGeneratedError) as e:
        raise _guard(scenario_id, e) from e


@router.get("/targets")
def get_targets(scenario_id: str, svc: Service) -> dict[str, Any]:
    try:
        return svc.targets(scenario_id)
    except (ScenarioNotFoundError, WorldNotGeneratedError, TargetsNotGeneratedError) as e:
        raise _guard(scenario_id, e) from e


@router.post("/decline")
def generate_decline(
    scenario_id: str,
    svc: Service,
    max_levels: Annotated[int | None, Query(ge=1, le=200, alias="maxLevels")] = None,
) -> dict[str, Any]:
    """Chained Hybrid-A* decline (raw centerline, Phase 04). Synchronous:
    the default scenario takes on the order of a minute. Async jobs are
    planned (SRS §52)."""
    try:
        return svc.generate_decline(scenario_id, max_levels)
    except (ScenarioNotFoundError, WorldNotGeneratedError, TargetsNotGeneratedError) as e:
        raise _guard(scenario_id, e) from e


@router.get("/decline")
def get_decline(scenario_id: str, svc: Service) -> dict[str, Any]:
    try:
        return svc.decline(scenario_id)
    except (ScenarioNotFoundError, WorldNotGeneratedError, DeclineNotGeneratedError) as e:
        raise _guard(scenario_id, e) from e
