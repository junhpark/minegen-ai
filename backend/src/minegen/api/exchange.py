"""Phase 23A: MineExchange bundle download (read-only projection)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from minegen.api.deps import get_exchange_service
from minegen.api.errors import ROUTER_DESIGN, guard
from minegen.core.models import ErrorDetail
from minegen.exchange.builder import ExchangeExportError
from minegen.exchange.models import MINE_EXCHANGE_VERSION
from minegen.services.exchange_service import ExchangeService

router = APIRouter(prefix="/scenarios/{scenario_id}/export", tags=["export"])

Service = Annotated[ExchangeService, Depends(get_exchange_service)]


@router.post("/mine-exchange")
def export_mine_exchange(scenario_id: str, svc: Service) -> Response:
    """``application/zip`` MineExchange v1 bundle of the scenario's current
    authoritative state. Nothing is generated or persisted; a world is the
    only prerequisite (absent design artifacts are manifest omissions).
    The generation time travels in a non-authoritative header only — the
    semantic manifest carries no wall-clock value (deterministic bundle)."""
    try:
        result = svc.export(scenario_id)
    except HTTPException:
        raise
    except ExchangeExportError as exc:
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
        content=result.zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{result.filename}"',
            "X-MineExchange-Version": MINE_EXCHANGE_VERSION,
            "X-MineExchange-Generated-At": datetime.now(UTC).isoformat(timespec="seconds"),
            "Cache-Control": "no-store",
        },
    )
