"""Phase 02/18 orchestrator: Scenario → SyntheticWorld.

    Scenario
      ↓ terrain surface                 (world/terrain.py)
      ↓ authoritative orebody solid     (world/orebody.py)
      ↓ numerical field lattice         (world/field_grid.py)
      ↓ grade field                     (world/geology.py)
      ↓ rock-quality field              (world/geology.py)
      ↓ fault distance/zone fields      (world/geology.py)
      ↓ terrain boundary policy         (world/spatial_fields.py)
      ↓ SpatialFieldSet

Every random field uses the scenario seed with a distinct sub-stream, so the
whole world is reproducible from the scenario document alone (rule 7). The
sub-stream keys are FROZEN (rule 121); Phase 18 changed the storage
abstraction, not a single random draw.

There is no block model: the lattice is sampling support for the fields
(rule 127), the orebody solid alone defines mineralized membership
(rule 129) and no world-level statistic claims resources, reserves or
in-situ ore tonnage (rule 131).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from minegen.core.models import FieldSamplingConfig, Scenario, ScenarioCreate, WorldConfig
from minegen.world.field_grid import FieldGrid
from minegen.world.geology import (
    FaultPlane,
    compute_fault_fields,
    generate_grade_field,
    generate_rock_quality,
)
from minegen.world.orebody import Orebody, build_orebody
from minegen.world.spatial_fields import (
    COLUMN_TOP_FILL,
    TERRAIN_SUPPORT_THRESHOLD,
    RegularScalarField,
    SpatialFieldSet,
    column_top_fill,
    terrain_support_fraction,
)
from minegen.world.terrain import Terrain, generate_terrain


@dataclass
class SyntheticWorld:
    terrain: Terrain
    orebody: Orebody
    faults: list[FaultPlane]
    fields: SpatialFieldSet

    def stats(self, scenario: ScenarioCreate) -> dict[str, Any]:
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
            "fields": self.fields.stats(),
        }


def build_field_grid(
    world: WorldConfig, cfg: FieldSamplingConfig, reference_elevation: float, relief: float
) -> FieldGrid:
    """Lattice from the model bottom (``reference_elevation − depth``, rule
    35) to ``reference_elevation + relief``.

    The top comes from *configuration*, not from the realized terrain, so the
    lattice shape is identical for every seed of the same scenario and seed-
    to-seed field comparisons are element-wise meaningful."""
    bottom = world.bottom_elevation(reference_elevation)
    top = reference_elevation + relief
    return FieldGrid.from_extent(
        (-world.size_x / 2, -world.size_y / 2, bottom),
        (world.size_x / 2, world.size_y / 2, top),
        cfg.as_tuple(),
    )


def generate_world(scenario: Scenario | ScenarioCreate) -> SyntheticWorld:
    seed = scenario.seed
    terrain = generate_terrain(scenario.world, scenario.terrain, seed)
    orebody = build_orebody(scenario.orebody)
    grid = build_field_grid(
        scenario.world,
        scenario.field_sampling,
        scenario.terrain.base_elevation,
        scenario.terrain.relief,
    )

    rock_quality, _ = generate_rock_quality(grid, scenario.geology.rock_quality, seed)
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

    support = terrain_support_fraction(grid, terrain)
    supported = support >= TERRAIN_SUPPORT_THRESHOLD
    fields = SpatialFieldSet(
        grid=grid,
        rock_quality=RegularScalarField(
            "rock_quality",
            grid,
            column_top_fill(rock_quality, supported),
            {"boundaryPolicy": COLUMN_TOP_FILL, "semantics": "synthetic RMR-like 0-100"},
        ),
        grade=RegularScalarField(
            "grade",
            grid,
            grade,
            {"semantics": "synthetic planning field; the orebody solid decides membership"},
        ),
        fault_signed_distance=RegularScalarField(
            "fault_signed_distance", grid, fault_fields.signed_distance
        ),
        fault_zone=RegularScalarField("fault_zone", grid, fault_fields.zone),
        fault_influence=RegularScalarField("fault_influence", grid, fault_fields.influence),
        terrain_support=support,
        meta={"terrainSupportThreshold": TERRAIN_SUPPORT_THRESHOLD},
    )
    return SyntheticWorld(terrain=terrain, orebody=orebody, faults=faults, fields=fields)
