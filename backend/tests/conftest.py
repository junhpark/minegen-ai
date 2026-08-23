from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from minegen.api.deps import (
    get_design_service,
    get_job_service,
    get_scenario_store,
    get_world_service,
)
from minegen.core.models import (
    BlockModelConfig,
    FaultConfig,
    GeologyConfig,
    OrebodyConfig,
    Point3D,
    Scenario,
    ScenarioCreate,
    TerrainConfig,
    WorldConfig,
)
from minegen.main import create_app
from minegen.services.design_service import DesignService
from minegen.services.job_service import JobService
from minegen.services.scenario_service import ScenarioStore
from minegen.services.world_service import WorldService


@pytest.fixture
def store(tmp_path: Path) -> ScenarioStore:
    return ScenarioStore(tmp_path / "scenarios")


@pytest.fixture
def world_service(store: ScenarioStore) -> WorldService:
    return WorldService(store)


@pytest.fixture
def design_service(store: ScenarioStore, world_service: WorldService) -> DesignService:
    return DesignService(store, world_service)


@pytest.fixture
def job_service() -> Iterator[JobService]:
    svc = JobService(max_workers=2)
    yield svc
    svc.shutdown()


@pytest.fixture
def client(
    store: ScenarioStore,
    world_service: WorldService,
    design_service: DesignService,
    job_service: JobService,
) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_scenario_store] = lambda: store
    app.dependency_overrides[get_world_service] = lambda: world_service
    app.dependency_overrides[get_design_service] = lambda: design_service
    app.dependency_overrides[get_job_service] = lambda: job_service
    # the WebSocket handler resolves the registry without DI; point it at the same instance
    import minegen.api.jobs as jobs_module

    jobs_module.get_job_service = lambda: job_service  # type: ignore[assignment]
    with TestClient(app) as c:
        yield c


def small_scenario(seed: int = 42, with_fault: bool = True) -> Scenario:
    """Fast world (≈ 40×40×30 blocks) for algorithm tests."""
    faults = (
        [
            FaultConfig(
                origin=Point3D(x=-60.0, y=-80.0, z=0.0),
                strike_deg=120.0,
                dip_deg=65.0,
                core_half_width=2.5,
                influence_half_width=20.0,
            )
        ]
        if with_fault
        else []
    )
    return Scenario(
        **ScenarioCreate(
            name="small",
            seed=seed,
            world=WorldConfig(size_x=400, size_y=400, depth=250),
            terrain=TerrainConfig(grid_spacing=10, base_elevation=100, relief=40, octaves=3),
            orebody=OrebodyConfig(
                center=Point3D(x=40.0, y=20.0, z=-50.0),
                strike_deg=35.0,
                dip_deg=70.0,
                length=200.0,
                height=120.0,
                thickness=12.0,
                mean_grade=4.2,
                grade_variability=0.3,
            ),
            geology=GeologyConfig(faults=faults),
            block_model=BlockModelConfig(dx=10, dy=10, dz=10),
        ).model_dump()
    )
