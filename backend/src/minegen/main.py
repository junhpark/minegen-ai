"""FastAPI application entry point.

Run locally:  uvicorn minegen.main:app --reload --app-dir src
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from minegen import __version__
from minegen.api import design, health, scenarios, world
from minegen.config import get_settings

API_PREFIX = "/api/v1"


def _sanitize_validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    """Strip the echoed ``input`` (which may contain NaN/inf and would make the
    422 body itself non-JSON) and stringify ``ctx`` values."""
    out: list[dict[str, Any]] = []
    for raw in exc.errors():
        e = dict(raw)
        e.pop("input", None)
        e.pop("url", None)
        ctx = e.get("ctx")
        if isinstance(ctx, dict):
            e["ctx"] = {k: str(v) for k, v in ctx.items()}
        out.append(e)
    return out


async def validation_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "detail": {
                "code": "VALIDATION_ERROR",
                "message": "request failed schema validation",
                "errors": _sanitize_validation_errors(exc),
            }
        },
    )


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "Generative underground mine design research platform. "
            "All coordinates are ENU Z-up meters."
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    api = APIRouter(prefix=API_PREFIX)
    api.include_router(health.router)
    api.include_router(scenarios.router)
    api.include_router(world.router)
    api.include_router(design.router)
    app.include_router(api)
    return app


app = create_app()
