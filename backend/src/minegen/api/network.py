"""Phase 07 MineNetwork endpoints (rules 13, 68–70).

The reserved ``/scenarios/{id}/network`` namespace. Generation is
SYNCHRONOUS: rule 60 reserves async jobs for long-running design operations,
and the full RAMP + DRIFT + CROSSCUT graph rebuild (455 nodes / 454 edges on
the default scenario) completes in a few seconds.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from minegen.api.deps import get_design_service
from minegen.api.errors import ROUTER_NETWORK, guard
from minegen.network.models import NetworkPayload
from minegen.services.design_service import DesignService

router = APIRouter(prefix="/scenarios/{scenario_id}/network", tags=["network"])

Service = Annotated[DesignService, Depends(get_design_service)]


def _fail(scenario_id: str, exc: Exception) -> HTTPException:
    """The wire answer of ``api/errors.guard`` for this router, or the
    unchanged ``raise exc`` fall-through. AC-01F: the recorded 404
    ``NETWORK_NOT_GENERATED`` drift (I-8) is preserved by the router override,
    not normalized (A6 defers that to AC-01I)."""
    mapped = guard(scenario_id, exc, router=ROUTER_NETWORK)
    if mapped is None:
        raise exc
    return mapped


@router.post("/generate")
def generate_network(scenario_id: str, svc: Service) -> NetworkPayload:
    try:
        return svc.generate_network(scenario_id)
    except Exception as exc:
        raise _fail(scenario_id, exc) from exc


@router.get("")
def get_network(scenario_id: str, svc: Service) -> NetworkPayload:
    try:
        return svc.network(scenario_id)
    except Exception as exc:
        raise _fail(scenario_id, exc) from exc
