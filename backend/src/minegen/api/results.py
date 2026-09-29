"""Phase 23C: external simulation results (MineResult 1.0) — import, list,
inspect, delete, export and overlay frames. Results live under
``results/<resultId>/`` beside (never inside) ``derived/``; no route here
generates, regenerates or mutates a mine artifact."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from minegen.api.deps import get_result_service
from minegen.api.errors import ROUTER_DESIGN, guard
from minegen.core.models import ErrorDetail
from minegen.exchange.builder import ExchangeExportError
from minegen.results.errors import ResultError, ResultLimitExceededError, ResultPackageInvalidError
from minegen.results.models import (
    MINE_RESULT_VERSION,
    OperationsFrame,
    ResultDetail,
    ResultGeometryPayload,
    ResultImportPayload,
    ResultListPayload,
    SourceApplication,
    VentilationFrame,
)
from minegen.results.package import MAX_UPLOAD_BYTES
from minegen.services.result_service import ResultService

router = APIRouter(prefix="/scenarios/{scenario_id}/results", tags=["results"])

Service = Annotated[ResultService, Depends(get_result_service)]

_ZIP_TYPES = ("application/zip", "application/x-zip-compressed", "application/octet-stream")


def _fail(scenario_id: str, exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, ResultError | ExchangeExportError):
        return HTTPException(
            status_code=exc.http_status,
            detail=ErrorDetail(code=exc.code, message=str(exc)).model_dump(by_alias=True),
        )
    mapped = guard(scenario_id, exc, router=ROUTER_DESIGN)
    if mapped is None:
        raise exc
    return mapped


async def _upload(request: Request) -> bytes:
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if content_type not in _ZIP_TYPES:
        raise ResultPackageInvalidError(
            f"Content-Type must be application/zip (got {content_type or 'none'!r})",
            subject="upload",
        )
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
        raise ResultLimitExceededError(
            f"upload of {declared} bytes exceeds the {MAX_UPLOAD_BYTES}-byte limit",
            subject="upload",
        )
    data = await request.body()
    if len(data) > MAX_UPLOAD_BYTES:
        raise ResultLimitExceededError(
            f"upload of {len(data)} bytes exceeds the {MAX_UPLOAD_BYTES}-byte limit",
            subject="upload",
        )
    return data


async def _import(
    scenario_id: str, application: SourceApplication, request: Request, svc: ResultService
) -> Response:
    try:
        data = await _upload(request)
        payload = svc.import_result(scenario_id, application, data)
    except Exception as exc:
        raise _fail(scenario_id, exc) from exc
    return Response(
        content=payload.model_dump_json(by_alias=True),
        media_type="application/json",
        status_code=status.HTTP_201_CREATED if payload.created else status.HTTP_200_OK,
        headers={"X-MineResult-Version": MINE_RESULT_VERSION, "Cache-Control": "no-store"},
    )


@router.post("/import/ventsim", response_model=ResultImportPayload)
async def import_ventsim(scenario_id: str, request: Request, svc: Service) -> Response:
    """Import a Ventsim ventilation result package (``application/zip``,
    MineResult 1.0 shape — the round-trip kit of the Ventsim seed filled
    in). The package must be bound to THIS scenario's CURRENT MineExchange
    ``sourceSnapshot``; identity is explicit (edgeId / crosswalk), units are
    canonical or explicitly declared. 201 when stored, 200 when the identical
    result already existed (idempotent)."""
    return await _import(scenario_id, "VENTSIM", request, svc)


@router.post("/import/anylogic", response_model=ResultImportPayload)
async def import_anylogic(scenario_id: str, request: Request, svc: Service) -> Response:
    """Import an AnyLogic operations result package (vehicle samples, edge
    metrics, summary metrics) under the same binding contract."""
    return await _import(scenario_id, "ANYLOGIC", request, svc)


@router.get("", response_model=ResultListPayload)
def list_results(scenario_id: str, svc: Service) -> ResultListPayload:
    """Every stored result with its COMPATIBLE / STALE compatibility against
    the current mine snapshot. Read-only."""
    try:
        return svc.list_results(scenario_id)
    except Exception as exc:
        raise _fail(scenario_id, exc) from exc


@router.get("/{result_id}", response_model=ResultDetail)
def get_result(scenario_id: str, result_id: str, svc: Service) -> ResultDetail:
    """Metadata of one result (manifest, provenance, availability); no
    sample data."""
    try:
        return svc.get_result(scenario_id, result_id)
    except Exception as exc:
        raise _fail(scenario_id, exc) from exc


@router.delete("/{result_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_result(scenario_id: str, result_id: str, svc: Service) -> Response:
    """Delete one stored result folder. Mine artifacts are untouched."""
    try:
        svc.delete_result(scenario_id, result_id)
    except Exception as exc:
        raise _fail(scenario_id, exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{result_id}/export")
def export_result(scenario_id: str, result_id: str, svc: Service) -> Response:
    """The canonical MineResult 1.0 ZIP of a stored result (deterministic,
    byte-identical for the same stored result; itself importable)."""
    try:
        exported = svc.export(scenario_id, result_id)
    except Exception as exc:
        raise _fail(scenario_id, exc) from exc
    return Response(
        content=exported.zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{exported.filename}"',
            "X-MineResult-Version": MINE_RESULT_VERSION,
            "Cache-Control": "no-store",
        },
    )


@router.get("/{result_id}/geometry", response_model=ResultGeometryPayload)
def result_geometry(scenario_id: str, result_id: str, svc: Service) -> ResultGeometryPayload:
    """The source-snapshot edge centerlines the result is bound to (the
    overlay geometry, LOCAL_ENU_Z_UP metres). Refused for a STALE result."""
    try:
        return svc.geometry(scenario_id, result_id)
    except Exception as exc:
        raise _fail(scenario_id, exc) from exc


@router.get("/{result_id}/ventilation", response_model=VentilationFrame)
def ventilation_frame(
    scenario_id: str,
    result_id: str,
    svc: Service,
    metric: Annotated[str, Query()],
    time: Annotated[float | None, Query()] = None,
) -> VentilationFrame:
    """One metric over the edges at one time (hold-last for a dynamic
    result; ``time`` ignored for STATIC). Missing edges are listed, never
    zero-filled. Refused for a STALE result."""
    try:
        return svc.ventilation(scenario_id, result_id, metric=metric, time=time)
    except Exception as exc:
        raise _fail(scenario_id, exc) from exc


@router.get("/{result_id}/operations/frame", response_model=OperationsFrame)
def operations_frame(
    scenario_id: str,
    result_id: str,
    svc: Service,
    time: Annotated[float, Query()],
) -> OperationsFrame:
    """Vehicle positions (same-edge interpolation only) and hold-last edge
    metrics at one time of the result clock. Refused for a STALE result."""
    try:
        return svc.operations(scenario_id, result_id, time=time)
    except Exception as exc:
        raise _fail(scenario_id, exc) from exc
