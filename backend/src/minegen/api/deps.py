"""FastAPI dependencies."""

from __future__ import annotations

from functools import lru_cache

from minegen.config import get_settings
from minegen.services.design_service import DesignService
from minegen.services.infrastructure_service import InfrastructureService
from minegen.services.job_service import JobService
from minegen.services.scenario_service import ScenarioStore
from minegen.services.world_service import WorldService


@lru_cache
def get_scenario_store() -> ScenarioStore:
    return ScenarioStore(get_settings().scenarios_dir)


@lru_cache
def get_world_service() -> WorldService:
    return WorldService(get_scenario_store())


@lru_cache
def get_design_service() -> DesignService:
    return DesignService(get_scenario_store(), get_world_service())


@lru_cache
def get_infrastructure_service() -> InfrastructureService:
    return InfrastructureService(get_scenario_store(), get_design_service())


@lru_cache
def get_job_service() -> JobService:
    return JobService()
