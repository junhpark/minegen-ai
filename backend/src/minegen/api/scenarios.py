"""Scenario CRUD. Thin router: no algorithms here (CLAUDE.md rule 5)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from minegen.api.deps import get_scenario_store, get_world_service
from minegen.core.models import (
    ErrorDetail,
    Scenario,
    ScenarioCreate,
    ScenarioRealizeRequest,
    ScenarioSummary,
)
from minegen.services.scenario_realizer import ScenarioRealizationError, realize_scenario
from minegen.services.scenario_service import ScenarioNotFoundError, ScenarioStore
from minegen.services.world_service import WorldService

router = APIRouter(prefix="/scenarios", tags=["scenarios"])

Store = Annotated[ScenarioStore, Depends(get_scenario_store)]
World = Annotated[WorldService, Depends(get_world_service)]


def _not_found(scenario_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=ErrorDetail(
            code="SCENARIO_NOT_FOUND", message=f"scenario '{scenario_id}' does not exist"
        ).model_dump(by_alias=True),
    )


@router.post("/realize", response_model=ScenarioCreate, response_model_by_alias=True)
def realize(body: ScenarioRealizeRequest) -> ScenarioCreate:
    """Phase 17: deterministic preset+seed realization. NON-persistent —
    returns a fully resolved ScenarioCreate for the client to inspect and
    then submit to the ordinary create endpoint (rule 119)."""
    try:
        return realize_scenario(body.preset, body.seed, body.fault_count)
    except ScenarioRealizationError as exc:
        raise HTTPException(
            status_code=422,
            detail=ErrorDetail(code="SCENARIO_REALIZATION_INVALID", message=str(exc)).model_dump(
                by_alias=True
            ),
        ) from exc


@router.post(
    "", response_model=Scenario, response_model_by_alias=True, status_code=status.HTTP_201_CREATED
)
def create_scenario(payload: ScenarioCreate, store: Store) -> Scenario:
    return store.create(payload)


@router.get("", response_model=list[ScenarioSummary], response_model_by_alias=True)
def list_scenarios(store: Store) -> list[ScenarioSummary]:
    return store.list()


@router.get("/{scenario_id}", response_model=Scenario, response_model_by_alias=True)
def get_scenario(scenario_id: str, store: Store) -> Scenario:
    try:
        return store.get(scenario_id)
    except ScenarioNotFoundError as e:
        raise _not_found(scenario_id) from e


@router.put("/{scenario_id}", response_model=Scenario, response_model_by_alias=True)
def replace_scenario(
    scenario_id: str, payload: ScenarioCreate, store: Store, world: World
) -> Scenario:
    """Replacing the document invalidates every derived artefact
    (world arrays, derived/*). Downstream phases add their own derived
    products under derived/, so this one call stays the single choke point."""
    try:
        updated = store.replace(scenario_id, payload)
        world.invalidate(scenario_id)
        return updated
    except ScenarioNotFoundError as e:
        raise _not_found(scenario_id) from e
