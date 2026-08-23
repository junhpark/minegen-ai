"""Phase 02 orchestrator: Scenario → SyntheticWorld.

    Scenario
      ↓ terrain surface            (world/terrain.py)
      ↓ analytic orebody           (world/orebody.py)
      ↓ block grid                 (world/voxel_grid.py)
      ↓ grade field                (world/geology.py)
      ↓ rock-quality field         (world/geology.py)
      ↓ fault distance/zone fields (world/geology.py)
      ↓ block model assembly       (world/block_model.py)

Every random field uses the scenario seed with a distinct sub-stream, so the
whole world is reproducible from the scenario document alone (rule 7).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from minegen.core.models import Scenario, ScenarioCreate
from minegen.world.block_model import BlockModel, assemble_block_model, build_block_grid
from minegen.world.geology import (
    FaultPlane,
    compute_fault_fields,
    generate_grade_field,
    generate_rock_quality,
)
from minegen.world.orebody import Orebody, build_orebody
from minegen.world.terrain import Terrain, generate_terrain


@dataclass
class SyntheticWorld:
    terrain: Terrain
    orebody: Orebody
    faults: list[FaultPlane]
    block_model: BlockModel

    def stats(self, scenario: ScenarioCreate) -> dict[str, Any]:
        bm = self.block_model.stats(scenario.orebody.density)
        return {
            "terrain": {
                "nx": self.terrain.nx,
                "ny": self.terrain.ny,
                "spacing": self.terrain.spacing,
                "zMin": self.terrain.z_min,
                "zMax": self.terrain.z_max,
            },
            "orebody": self.orebody.to_dict(),
            "faults": len(self.faults),
            "blockModel": bm,
        }


def generate_world(scenario: Scenario | ScenarioCreate) -> SyntheticWorld:
    seed = scenario.seed
    terrain = generate_terrain(scenario.world, scenario.terrain, seed)
    orebody = build_orebody(scenario.orebody)
    grid = build_block_grid(
        scenario.world,
        scenario.block_model,
        scenario.terrain.base_elevation,
        scenario.terrain.relief,
    )

    rq_cfg = scenario.geology.rock_quality
    rock_quality, _ = generate_rock_quality(grid, rq_cfg, seed)
    grade = generate_grade_field(
        grid,
        mean_grade=scenario.orebody.mean_grade,
        variability=scenario.orebody.grade_variability,
        correlation_length_xy=scenario.orebody.grade_correlation_length_xy,
        correlation_length_z=scenario.orebody.grade_correlation_length_z,
        seed=seed,
    )
    faults = [FaultPlane.from_config(f) for f in scenario.geology.faults]
    fault_fields = compute_fault_fields(grid, faults)

    block_model = assemble_block_model(grid, terrain, orebody, grade, rock_quality, fault_fields)
    return SyntheticWorld(terrain=terrain, orebody=orebody, faults=faults, block_model=block_model)
