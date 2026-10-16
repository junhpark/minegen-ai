"""FastAPI application entry point.

Run locally:  uvicorn minegen.main:app --reload --app-dir src
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from minegen import __version__
from minegen.api import (
    adapters,
    analysis,
    demos,
    design,
    exchange,
    health,
    infrastructure,
    jobs,
    network,
    results,
    scenarios,
    world,
)
from minegen.api.demo_guard import refuse_demo_writes
from minegen.api.deps import get_demo_materializer
from minegen.config import get_settings
from minegen.services.demo_materializer import DemoMaterializer
from minegen.services.scenario_migration import UnsupportedSchemaVersionError

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


async def unsupported_schema_handler(_: Request, exc: Exception) -> JSONResponse:
    """A persisted document newer than this backend is a typed 422, never a
    500 and never a silent downgrade (Phase 18 migration contract)."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": {"code": "SCENARIO_SCHEMA_UNSUPPORTED", "message": str(exc)}},
    )


def create_app(
    *, autobake: bool | None = None, materializer: DemoMaterializer | None = None
) -> FastAPI:
    """The application. ``autobake`` (default: ``Settings.demos_autobake``)
    decides whether the lifespan starts the demo materializer of PR #54
    review B1 — the demo baker's own in-process application and the test
    suite pass ``False``; ``materializer`` injects one (tests)."""
    settings = get_settings()
    enabled = settings.demos_autobake if autobake is None else autobake

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # PR #54 review B1: bake the demo mines the catalogue does not list,
        # in a daemon thread, once per process; never in the tests, the e2e
        # or the baker itself (they pass / configure autobake off)
        if enabled:
            (materializer or get_demo_materializer()).start()
        yield

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "Generative underground mine design research platform. "
            "All coordinates are ENU Z-up meters."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        # Phase 23C: a browser may read the download filename and the version
        # headers of the export / result routes only when they are exposed
        expose_headers=[
            "Content-Disposition",
            "X-MineExchange-Version",
            "X-Adapter-Name",
            "X-Adapter-Version",
            "X-MineResult-Version",
        ],
        allow_headers=["*"],
    )

    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(UnsupportedSchemaVersionError, unsupported_schema_handler)

    api = APIRouter(prefix=API_PREFIX)
    api.include_router(health.router)
    api.include_router(demos.router)
    # hardening PR-2 H4: every scenario-scoped router refuses writes to a
    # baked demo through ONE dependency (api/demo_guard.py)
    demo_guard = [Depends(refuse_demo_writes)]
    api.include_router(scenarios.router, dependencies=demo_guard)
    api.include_router(world.router, dependencies=demo_guard)
    api.include_router(design.router, dependencies=demo_guard)
    api.include_router(network.router, dependencies=demo_guard)
    api.include_router(infrastructure.router, dependencies=demo_guard)
    api.include_router(jobs.router)
    api.include_router(exchange.router, dependencies=demo_guard)
    api.include_router(adapters.router, dependencies=demo_guard)
    api.include_router(analysis.router, dependencies=demo_guard)
    api.include_router(results.router, dependencies=demo_guard)
    app.include_router(api)
    app.include_router(jobs.ws_router)
    return app


app = create_app()
