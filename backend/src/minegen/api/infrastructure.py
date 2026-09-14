"""Phase 11 infrastructure API (rules 87–92). Thin: algorithms live in
``minegen/infrastructure``, persistence in ``InfrastructureService``."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from minegen.api.deps import get_infrastructure_service
from minegen.api.errors import ROUTER_INFRASTRUCTURE, guard
from minegen.infrastructure.models import CommunicationPayload, SensorPayload
from minegen.services.infrastructure_service import InfrastructureService

router = APIRouter(prefix="/scenarios/{scenario_id}/infrastructure", tags=["infrastructure"])

Service = Annotated[InfrastructureService, Depends(get_infrastructure_service)]


def _fail(scenario_id: str, exc: Exception) -> HTTPException:
    """The wire answer of ``api/errors.guard`` for this router, or the
    unchanged ``raise exc`` fall-through — which this router did NOT have:
    its catch-all answered ``500 {"code": "INTERNAL_ERROR", "message":
    str(exc)}``, so the same ``ShaftsStaleError`` that is a typed 409 on
    ``/network/generate`` arrived here as a 500 with the engineering message
    leaked into the body (Stage A I-6). The catch-all is gone; an exception no
    router maps is a bare 500 exactly as on the other three."""
    mapped = guard(scenario_id, exc, router=ROUTER_INFRASTRUCTURE)
    if mapped is None:
        raise exc
    return mapped


@router.post("/communication")
def generate_communication(scenario_id: str, svc: Service) -> CommunicationPayload:
    """Phase 11 (rules 87–92): synchronous deterministic connected
    communication placement baseline."""
    try:
        return svc.generate_communication(scenario_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise _fail(scenario_id, exc) from exc


@router.get("/communication")
def get_communication(scenario_id: str, svc: Service) -> CommunicationPayload:
    try:
        return svc.communication(scenario_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise _fail(scenario_id, exc) from exc


@router.post("/sensors")
def generate_sensors(scenario_id: str, svc: Service) -> SensorPayload:
    """Phase 12 (rules 93–98): synchronous deterministic monitoring-placement
    baseline. Does NOT require communication.json (siblings, rule 97)."""
    try:
        return svc.generate_sensors(scenario_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise _fail(scenario_id, exc) from exc


@router.get("/sensors")
def get_sensors(scenario_id: str, svc: Service) -> SensorPayload:
    try:
        return svc.sensors(scenario_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise _fail(scenario_id, exc) from exc
