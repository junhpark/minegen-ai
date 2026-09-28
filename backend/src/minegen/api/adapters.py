"""Phase 23B.1: external adapter packages (read-only, built from the
MineExchange bundle of the scenario's current state)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from minegen.adapters.errors import AdapterError
from minegen.adapters.ventsim import ADAPTER_NAME, ADAPTER_VERSION, VentsimSeedConfig
from minegen.api.deps import get_adapter_service
from minegen.api.errors import ROUTER_DESIGN, guard
from minegen.core.models import ErrorDetail
from minegen.exchange.builder import ExchangeExportError
from minegen.exchange.models import MINE_EXCHANGE_VERSION
from minegen.services.adapter_service import AdapterService

router = APIRouter(prefix="/scenarios/{scenario_id}/export", tags=["export"])

Service = Annotated[AdapterService, Depends(get_adapter_service)]


@router.post("/ventsim-seed")
def export_ventsim_seed(
    scenario_id: str, svc: Service, config: VentsimSeedConfig | None = None
) -> Response:
    """``application/zip`` Ventsim SEED package: the MineExchange bundle of the
    scenario's current authoritative state translated by the VENTSIM_SEED
    adapter (one DXF polyline per network edge, airway attribute table,
    node table, identity map, adapter report). Requires the excavation
    centerlines and the MineNetwork in the bundle (409 REQUIRED_SOURCE_ABSENT
    otherwise); nothing is generated or persisted. The optional JSON body is
    the explicit adapter configuration (defaults are recorded in the
    report as ADAPTER_DEFAULT_EXPLICIT)."""
    try:
        result = svc.ventsim_seed(scenario_id, config)
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
    return Response(
        content=result.package.zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{result.filename}"',
            "X-Adapter-Name": ADAPTER_NAME,
            "X-Adapter-Version": ADAPTER_VERSION,
            "X-MineExchange-Version": MINE_EXCHANGE_VERSION,
            "Cache-Control": "no-store",
        },
    )
