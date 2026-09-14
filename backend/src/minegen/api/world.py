"""World generation, stats, slices and the scene manifest. Thin router."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from minegen.api.deps import get_world_service
from minegen.api.errors import ROUTER_WORLD, guard
from minegen.core.models import ErrorDetail
from minegen.services.scenario_service import ScenarioNotFoundError
from minegen.services.world_service import WorldService
from minegen.world.warped_vein import WarpedVeinGeometryBudgetError

router = APIRouter(prefix="/scenarios/{scenario_id}", tags=["world"])

Service = Annotated[WorldService, Depends(get_world_service)]


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=ErrorDetail(code=code, message=message).model_dump(by_alias=True),
    )


def _fail(scenario_id: str, exc: Exception) -> HTTPException:
    """The wire answer of ``api/errors.guard`` for this router, or the
    unchanged ``raise exc`` fall-through.

    AC-01F: this is where ``SCENE_ARTIFACT_INVALID`` reaches the client — 409
    with every invalid artifact of the refused snapshot in
    ``detail.artifacts[]`` (A14) — and where ``READ_SNAPSHOT_CHANGED`` will
    (A9: the scene's bounded snapshot retry is commit 3)."""
    mapped = guard(scenario_id, exc, router=ROUTER_WORLD)
    if mapped is None:
        raise exc
    return mapped


@router.post("/world/generate")
def generate_world(scenario_id: str, svc: Service) -> dict[str, Any]:
    try:
        return svc.generate(scenario_id)
    except ScenarioNotFoundError as e:
        raise _fail(scenario_id, e) from e
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
    except HTTPException:
        raise
    except Exception as e:
        raise _fail(scenario_id, e) from e


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
    except IndexError as e:
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "SLICE_OUT_OF_RANGE", str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise _fail(scenario_id, e) from e


@router.get("/scene")
def get_scene(scenario_id: str, svc: Service) -> dict[str, Any]:
    try:
        return svc.scene(scenario_id)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail(scenario_id, e) from e
