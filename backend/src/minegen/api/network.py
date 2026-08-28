"""Phase 07 MineNetwork endpoints (rules 13, 68–70).

The reserved ``/scenarios/{id}/network`` namespace. Generation is
SYNCHRONOUS: rule 60 reserves async jobs for long-running design operations,
and the RAMP subgraph (14 nodes / 13 edges on the default scenario) is tiny.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from minegen.api.deps import get_design_service
from minegen.core.models import ErrorDetail
from minegen.network.models import NetworkPayload
from minegen.services.design_service import (
    DesignService,
    NetworkNotFoundError,
    SmoothedNotGeneratedError,
    StaleInputsError,
)
from minegen.services.scenario_service import ScenarioNotFoundError
from minegen.services.world_service import WorldNotGeneratedError

router = APIRouter(prefix="/scenarios/{scenario_id}/network", tags=["network"])

Service = Annotated[DesignService, Depends(get_design_service)]


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
    if isinstance(exc, SmoothedNotGeneratedError):
        return _error(
            status.HTTP_409_CONFLICT,
            "SMOOTHED_NOT_GENERATED",
            f"scenario '{scenario_id}' has no smoothed decline; POST …/design/decline/smooth first",
        )
    if isinstance(exc, NetworkNotFoundError):
        return _error(
            404,
            "NETWORK_NOT_GENERATED",
            f"scenario '{scenario_id}' has no network; POST …/network/generate first",
        )
    if isinstance(exc, StaleInputsError):
        return _error(
            status.HTTP_409_CONFLICT,
            "STALE_INPUTS",
            "network inputs changed during generation; retry",
        )
    raise exc


@router.post("/generate")
def generate_network(scenario_id: str, svc: Service) -> NetworkPayload:
    try:
        return svc.generate_network(scenario_id)
    except Exception as exc:
        raise _guard(scenario_id, exc) from exc


@router.get("")
def get_network(scenario_id: str, svc: Service) -> NetworkPayload:
    try:
        return svc.network(scenario_id)
    except Exception as exc:
        raise _guard(scenario_id, exc) from exc
