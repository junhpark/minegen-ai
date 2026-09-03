"""World generation, stats, slices and the scene manifest. Thin router."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from minegen.api.deps import get_world_service
from minegen.core.models import ErrorDetail
from minegen.services.scenario_service import ScenarioNotFoundError
from minegen.services.world_service import (
    WorldArtifactIncompatibleError,
    WorldNotGeneratedError,
    WorldService,
)
from minegen.world.warped_vein import WarpedVeinGeometryBudgetError

router = APIRouter(prefix="/scenarios/{scenario_id}", tags=["world"])

Service = Annotated[WorldService, Depends(get_world_service)]


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=ErrorDetail(code=code, message=message).model_dump(by_alias=True),
    )


def _guard(scenario_id: str, exc: Exception) -> HTTPException:
    if isinstance(exc, ScenarioNotFoundError):
        return _error(
            status.HTTP_404_NOT_FOUND,
            "SCENARIO_NOT_FOUND",
            f"scenario '{scenario_id}' does not exist",
        )
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
    raise exc


@router.post("/world/generate")
def generate_world(scenario_id: str, svc: Service) -> dict[str, Any]:
    try:
        return svc.generate(scenario_id)
    except ScenarioNotFoundError as e:
        raise _guard(scenario_id, e) from e
    except WarpedVeinGeometryBudgetError as e:
        # Phase 19: an edited WARPED_VEIN whose derived geometry lattice
        # exceeds the supported budget fails explicitly — never coarsened
        raise _error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "OREBODY_GEOMETRY_BUDGET_EXCEEDED",
            f"scenario '{scenario_id}': {e}",
        ) from e


@router.get("/world")
def get_world(scenario_id: str, svc: Service) -> dict[str, Any]:
    try:
        return svc.stats(scenario_id)
    except (ScenarioNotFoundError, WorldNotGeneratedError) as e:
        raise _guard(scenario_id, e) from e


@router.get("/world/slice")
def get_slice(
    scenario_id: str,
    svc: Service,
    field: Literal["rockQuality", "grade", "faultInfluence", "faultZone"] = "rockQuality",
    axis: Literal["x", "y", "z"] = "z",
    index: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    try:
        return svc.slice(scenario_id, field, axis, index)
    except (ScenarioNotFoundError, WorldNotGeneratedError) as e:
        raise _guard(scenario_id, e) from e
    except IndexError as e:
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "SLICE_OUT_OF_RANGE", str(e)) from e


@router.get("/scene")
def get_scene(scenario_id: str, svc: Service) -> dict[str, Any]:
    try:
        return svc.scene(scenario_id)
    except (ScenarioNotFoundError, WorldNotGeneratedError) as e:
        raise _guard(scenario_id, e) from e
