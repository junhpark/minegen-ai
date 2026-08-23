"""Liveness endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from minegen.config import CANONICAL_COORDINATE_SYSTEM, get_settings
from minegen.core.models import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, response_model_by_alias=True)
def health() -> HealthResponse:
    s = get_settings()
    return HealthResponse(
        status="ok",
        app=s.app_name,
        version=s.version,
        coordinate_system=CANONICAL_COORDINATE_SYSTEM,
    )
