"""Phase 23B: external adapter packages (read-only, built from the
MineExchange bundle of the scenario's current state; directive §52)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from minegen.adapters.contracts import AdapterTarget
from minegen.adapters.errors import AdapterError
from minegen.api.deps import get_adapter_service
from minegen.api.errors import ROUTER_DESIGN, guard
from minegen.core.models import ErrorDetail
from minegen.exchange.builder import ExchangeExportError
from minegen.exchange.models import MINE_EXCHANGE_VERSION
from minegen.services.adapter_service import AdapterService

router = APIRouter(prefix="/scenarios/{scenario_id}/export", tags=["export"])

Service = Annotated[AdapterService, Depends(get_adapter_service)]


def _export(scenario_id: str, svc: AdapterService, target: AdapterTarget) -> Response:
    try:
        result = svc.export(scenario_id, target)
    except HTTPException:
        raise
    except (AdapterError, ExchangeExportError) as exc:
        raise HTTPException(
            status_code=exc.http_status,
            detail=ErrorDetail(code=exc.code, message=str(exc)).model_dump(by_alias=True),
        ) from exc
    except Exception as exc:
        mapped = guard(scenario_id, exc, router=ROUTER_DESIGN)
        if mapped is None:
            raise
        raise mapped from exc
    manifest = result.package.manifest
    return Response(
        content=result.package.zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{result.filename}"',
            "X-Adapter-Name": manifest.adapter_name,
            "X-Adapter-Version": manifest.adapter_version,
            "X-MineExchange-Version": MINE_EXCHANGE_VERSION,
            "Cache-Control": "no-store",
        },
    )


@router.post("/ventsim")
def export_ventsim(scenario_id: str, svc: Service) -> Response:
    """``application/zip`` Ventsim geometry / network SEED package (VENTSIM
    adapter over the MineExchange bundle): the full-fidelity centerline DXF,
    node and airway tables, DXF-handle identity map, adapter manifest.
    Requires the centerlines and the MineNetwork (typed 409 otherwise);
    nothing is generated or persisted; no ventilation physics is invented."""
    return _export(scenario_id, svc, "VENTSIM")


@router.post("/anylogic")
def export_anylogic(scenario_id: str, svc: Service) -> Response:
    """``application/zip`` AnyLogic operational data package (ANYLOGIC adapter):
    network / path / capability / production tables and the MineExchange 1.3
    timeline tables, plus a BLANK simulation-inputs template. Requires the
    MineNetwork and the MineTimeline (typed 409 otherwise)."""
    return _export(scenario_id, svc, "ANYLOGIC")


@router.post("/unity")
def export_unity(scenario_id: str, svc: Service) -> Response:
    """``application/zip`` Unity import package (UNITY adapter): every bundle
    GLB normalized to glTF Y-up, entity identity, network, capability and
    timeline documents, import settings. A world-only scenario yields a
    partial package (geology assets only)."""
    return _export(scenario_id, svc, "UNITY")


@router.post("/unreal")
def export_unreal(scenario_id: str, svc: Service) -> Response:
    """``application/zip`` Unreal import package (UNREAL adapter): the same
    normalized assets and semantics as the Unity package with Unreal import
    notes."""
    return _export(scenario_id, svc, "UNREAL")
