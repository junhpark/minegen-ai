"""Phase 11 infrastructure API (rules 87–92). Thin: algorithms live in
``minegen/infrastructure``, persistence in ``InfrastructureService``."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from minegen.api.deps import get_infrastructure_service
from minegen.infrastructure.models import CommunicationPayload, SensorPayload
from minegen.services.design_service import (
    LevelsNotGeneratedError,
    NetworkNotFoundError,
    SmoothedNotGeneratedError,
    StaleInputsError,
)
from minegen.services.infrastructure_service import (
    CommunicationNotGeneratedError,
    InfrastructureService,
    SensorsNotGeneratedError,
)
from minegen.services.scenario_service import ScenarioNotFoundError

router = APIRouter(prefix="/scenarios/{scenario_id}/infrastructure", tags=["infrastructure"])

Service = Annotated[InfrastructureService, Depends(get_infrastructure_service)]


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _guard(scenario_id: str, exc: Exception) -> HTTPException:
    if isinstance(exc, ScenarioNotFoundError):
        return _error(404, "SCENARIO_NOT_FOUND", f"scenario '{scenario_id}' does not exist")
    if isinstance(exc, NetworkNotFoundError):
        return _error(
            status.HTTP_409_CONFLICT,
            "NETWORK_NOT_GENERATED",
            f"scenario '{scenario_id}' has no MineNetwork; POST …/network/generate first",
        )
    if isinstance(exc, SmoothedNotGeneratedError):
        return _error(
            status.HTTP_409_CONFLICT,
            "SMOOTHED_NOT_GENERATED",
            f"scenario '{scenario_id}' has no smoothed decline; POST …/design/smooth first",
        )
    if isinstance(exc, LevelsNotGeneratedError):
        return _error(
            status.HTTP_409_CONFLICT,
            "LEVELS_NOT_GENERATED",
            f"scenario '{scenario_id}' has no levels; POST …/design/levels first",
        )
    if isinstance(exc, SensorsNotGeneratedError):
        return _error(
            status.HTTP_409_CONFLICT,
            "SENSORS_NOT_GENERATED",
            f"scenario '{scenario_id}' has no sensor plan; POST …/infrastructure/sensors first",
        )
    if isinstance(exc, CommunicationNotGeneratedError):
        return _error(
            status.HTTP_409_CONFLICT,
            "COMMUNICATION_NOT_GENERATED",
            f"scenario '{scenario_id}' has no communication plan; "
            "POST …/infrastructure/communication first",
        )
    if isinstance(exc, StaleInputsError):
        return _error(
            status.HTTP_409_CONFLICT,
            "STALE_INPUTS",
            "inputs changed while generating; retry",
        )
    return _error(500, "INTERNAL_ERROR", str(exc))


@router.post("/communication")
def generate_communication(scenario_id: str, svc: Service) -> CommunicationPayload:
    """Phase 11 (rules 87–92): synchronous deterministic connected
    communication placement baseline."""
    try:
        return svc.generate_communication(scenario_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise _guard(scenario_id, exc) from exc


@router.get("/communication")
def get_communication(scenario_id: str, svc: Service) -> CommunicationPayload:
    try:
        return svc.communication(scenario_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise _guard(scenario_id, exc) from exc


@router.post("/sensors")
def generate_sensors(scenario_id: str, svc: Service) -> SensorPayload:
    """Phase 12 (rules 93–98): synchronous deterministic monitoring-placement
    baseline. Does NOT require communication.json (siblings, rule 97)."""
    try:
        return svc.generate_sensors(scenario_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise _guard(scenario_id, exc) from exc


@router.get("/sensors")
def get_sensors(scenario_id: str, svc: Service) -> SensorPayload:
    try:
        return svc.sensors(scenario_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise _guard(scenario_id, exc) from exc
