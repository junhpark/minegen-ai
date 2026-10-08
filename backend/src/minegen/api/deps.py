"""FastAPI dependencies."""

from __future__ import annotations

from functools import lru_cache

from minegen.config import get_settings
from minegen.services.adapter_service import AdapterService
from minegen.services.analysis_service import AnalysisService
from minegen.services.demo_service import DemoService
from minegen.services.design_service import DesignService
from minegen.services.exchange_service import ExchangeService
from minegen.services.infrastructure_service import InfrastructureService
from minegen.services.job_service import JobService
from minegen.services.result_service import ResultService
from minegen.services.scenario_service import ScenarioStore
from minegen.services.world_service import WorldService


@lru_cache
def get_scenario_store() -> ScenarioStore:
    settings = get_settings()
    # hardening PR-2 H4: baked demos are resolved in place, read-only
    return ScenarioStore(settings.scenarios_dir, demo_root=settings.demos_dir)


@lru_cache
def get_demo_service() -> DemoService:
    return DemoService(get_scenario_store(), get_settings().demos_dir)


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


@lru_cache
def get_exchange_service() -> ExchangeService:
    return ExchangeService(get_scenario_store(), get_world_service())


@lru_cache
def get_analysis_service() -> AnalysisService:
    return AnalysisService(get_scenario_store())


@lru_cache
def get_adapter_service() -> AdapterService:
    return AdapterService(get_exchange_service())


@lru_cache
def get_result_service() -> ResultService:
    return ResultService(get_scenario_store(), get_exchange_service())
