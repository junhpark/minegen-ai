"""Phase 22A/B: the read-only mine analysis and the planning-economics
assumption document."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from minegen.analysis.economics import EconomicsConfig, EconomicsConfigResponse
from minegen.analysis.layout_comparison import LayoutComparisonPayload
from minegen.analysis.models import MineAnalysisPayload
from minegen.analysis.timeseries import TimeseriesPayload
from minegen.api.deps import get_analysis_service
from minegen.api.errors import ROUTER_DESIGN, guard
from minegen.services.analysis_service import AnalysisService

router = APIRouter(prefix="/scenarios/{scenario_id}/analysis", tags=["analysis"])

Service = Annotated[AnalysisService, Depends(get_analysis_service)]


def _mapped(scenario_id: str, exc: Exception) -> HTTPException:
    mapped = guard(scenario_id, exc, router=ROUTER_DESIGN)
    if mapped is None:
        raise exc
    return mapped


@router.get("")
def get_mine_analysis(scenario_id: str, svc: Service) -> MineAnalysisPayload:
    """Synchronous READ-ONLY projection of the persisted mine state into
    development / production / schedule / ratio / economics sections. No
    job, no generation, no persistence; a missing source is a NOT_AVAILABLE
    section (200), a present but malformed or inconsistent source a typed
    409 (``ANALYSIS_SOURCE_INCONSISTENT`` / ``ARTIFACT_MALFORMED`` /
    ``READ_SNAPSHOT_CHANGED``)."""
    try:
        return svc.analyze(scenario_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise _mapped(scenario_id, exc) from exc


@router.get("/timeseries")
def get_timeseries(
    scenario_id: str,
    svc: Service,
    bucket_days: Annotated[
        float | None,
        Query(
            alias="bucketDays",
            gt=0.0,
            le=36525.0,
            description="Bucket width in days; default = configured cashflowBucketDays, else 30.",
        ),
    ] = None,
) -> TimeseriesPayload:
    """Hardening PR-2 H3 §6: synchronous READ-ONLY bucketed time series of
    excavated development rock, planned mined tonnes, backfill and (when
    configured) cost / revenue / net / cumulative cashflow, from ONE bound
    snapshot. No persistence, no invalidation; a missing source is a
    NOT_AVAILABLE payload (200), a moving source 409 ``READ_SNAPSHOT_CHANGED``."""
    try:
        return svc.timeseries(scenario_id, bucket_days)
    except HTTPException:
        raise
    except Exception as exc:
        raise _mapped(scenario_id, exc) from exc


@router.get("/economics-config")
def get_economics_config(scenario_id: str, svc: Service) -> EconomicsConfigResponse:
    """The user-authored planning economics assumptions of this scenario.
    Absent → ``{configured: false, revision: null, config: null}``."""
    try:
        return svc.economics_config(scenario_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise _mapped(scenario_id, exc) from exc


@router.put("/economics-config")
def put_economics_config(
    scenario_id: str, config: EconomicsConfig, svc: Service
) -> EconomicsConfigResponse:
    """Validate → atomic write of ``economics.json`` → content revision.
    Never touches a mine artifact: no geometry, production or timeline
    invalidation follows an economics change."""
    try:
        return svc.put_economics_config(scenario_id, config)
    except HTTPException:
        raise
    except Exception as exc:
        raise _mapped(scenario_id, exc) from exc


@router.get("/layout-comparison")
def get_layout_comparison(scenario_id: str, svc: Service) -> LayoutComparisonPayload:
    """Phase 22C (rules 204–206): synchronous READ-ONLY comparable layout
    development cost per ranked layout-v2 candidate — persisted main-ramp
    length × ramp rate + persisted level-access length × level-access rate.
    No job, no generation, no persistence, no ranking change; no catalogue →
    NOT_AVAILABLE (200), no ``economics.json`` → NOT_CONFIGURED with the
    geometry facts (200); a malformed catalogue → 409 ``ARTIFACT_MALFORMED``,
    a moving source → 409 ``READ_SNAPSHOT_CHANGED``."""
    try:
        return svc.layout_comparison(scenario_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise _mapped(scenario_id, exc) from exc
