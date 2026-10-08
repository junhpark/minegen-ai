"""Baked demo catalogue (hardening PR-2 H4). Thin router: the index is read
and validated by ``services/demo_service.py``; a demo is OPENED through the
ordinary scenario routes (the store resolves its id in place, read-only)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from minegen.api.deps import get_demo_service
from minegen.api.errors import error_response
from minegen.services.demo_service import DemoCatalog, DemoIndexMalformedError, DemoService

router = APIRouter(prefix="/demos", tags=["demos"])

Service = Annotated[DemoService, Depends(get_demo_service)]


@router.get("", response_model=DemoCatalog, response_model_by_alias=True)
def list_demos(svc: Service) -> DemoCatalog:
    try:
        return svc.catalog()
    except DemoIndexMalformedError as exc:
        raise error_response(exc.http_status, exc.code, str(exc)) from exc
