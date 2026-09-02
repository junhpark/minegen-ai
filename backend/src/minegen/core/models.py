"""Pydantic domain schemas used at the API boundary.

Conventions
-----------
* Coordinates are ENU Z-up meters (``docs/coordinate-system.md``).
* Wire format is camelCase; Python attribute names are snake_case.
* These are *boundary* models. Bulk numerical data (spatial field arrays,
  cost fields, meshes) live in NumPy arrays and are never expanded into lists
  of these objects (CLAUDE.md rule 6).
"""

from __future__ import annotations

import math
import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from minegen.core.enums import AssetType, MiningMethodType, OrebodyType, ScenarioPreset


class ApiModel(BaseModel):
    """Base for every schema crossing the API boundary."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        # Rule 34: API/domain floats are finite. NaN / ±inf are rejected at the
        # boundary; +inf exists only inside numerical cost fields (Phase 03).
        allow_inf_nan=False,
    )


# --------------------------------------------------------------------------- #
# Geometry primitives
# --------------------------------------------------------------------------- #


class Point3D(ApiModel):
    x: float
    y: float
    z: float

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)

    def distance_to(self, other: Point3D) -> float:
        return math.dist(self.as_tuple(), other.as_tuple())


class Vector3D(Point3D):
    """Same shape as Point3D; semantic marker for directions."""


class BoundingBox(ApiModel):
    min: Point3D
    max: Point3D

    @model_validator(mode="after")
    def _check_order(self) -> BoundingBox:
        if self.min.x > self.max.x or self.min.y > self.max.y or self.min.z > self.max.z:
            raise ValueError("bounding box min must be <= max on every axis")
        return self

    def contains(self, p: Point3D) -> bool:
        return (
            self.min.x <= p.x <= self.max.x
            and self.min.y <= p.y <= self.max.y
            and self.min.z <= p.z <= self.max.z
        )


# --------------------------------------------------------------------------- #
# Scenario configuration
# --------------------------------------------------------------------------- #

PositiveFloat = Annotated[float, Field(gt=0)]
NonNegativeFloat = Annotated[float, Field(ge=0)]
Fraction = Annotated[float, Field(ge=0, le=1)]


class WorldConfig(ApiModel):
    """Extent of the synthetic world.

    * Horizontal origin is at the center: x ∈ [−size_x/2, +size_x/2],
      y ∈ [−size_y/2, +size_y/2].
    * ``depth`` is the **model depth below the terrain reference elevation**
      (``TerrainConfig.base_elevation``), rule 35. With base_elevation = 300
      and depth = 600 the model bottom is at z = −300. Terrain relief may
      push the actual bounding-box top above the reference elevation.
    """

    size_x: PositiveFloat = 1200.0
    size_y: PositiveFloat = 1200.0
    depth: PositiveFloat = 600.0

    def bottom_elevation(self, reference_elevation: float) -> float:
        return reference_elevation - self.depth

    def bounds(self, reference_elevation: float, top_z: float | None = None) -> BoundingBox:
        """Bounding box from the model bottom to ``top_z`` (defaults to the
        reference elevation; pass the actual terrain maximum once known)."""
        top = reference_elevation if top_z is None else top_z
        return BoundingBox(
            min=Point3D(
                x=-self.size_x / 2,
                y=-self.size_y / 2,
                z=self.bottom_elevation(reference_elevation),
            ),
            max=Point3D(x=self.size_x / 2, y=self.size_y / 2, z=top),
        )


class TerrainConfig(ApiModel):
    grid_spacing: PositiveFloat = 10.0
    base_elevation: float = 300.0
    relief: NonNegativeFloat = 100.0
    octaves: Annotated[int, Field(ge=1, le=8)] = 4


class OrebodyConfig(ApiModel):
    """Tabular orebody (v0.1). ``height`` is the down-dip length
    (CLAUDE.md rule 28), not the vertical extent."""

    orebody_type: OrebodyType = OrebodyType.TABULAR
    center: Point3D
    strike_deg: Annotated[float, Field(ge=0, lt=360)]
    dip_deg: Annotated[float, Field(gt=0, le=90)]
    length: PositiveFloat
    height: PositiveFloat
    thickness: PositiveFloat
    mean_grade: NonNegativeFloat = 4.0
    grade_variability: NonNegativeFloat = 0.3
    # Spatial continuity of grade is a property of the mineralization, not of
    # the host rock mass, so it is parameterized separately from rock quality.
    grade_correlation_length_xy: PositiveFloat = 80.0
    grade_correlation_length_z: PositiveFloat = 40.0
    density: PositiveFloat = 2.8

    @property
    def vertical_extent(self) -> float:
        return self.height * math.sin(math.radians(self.dip_deg))


class FaultConfig(ApiModel):
    """Synthetic planar fault with a core zone and a damage zone
    (CLAUDE.md rule 27).

    Widths are **perpendicular half-widths measured from the fault plane**
    (rule 36). For signed distance ``d`` to the plane::

        |d| <= core_half_width                      → core
        core_half_width < |d| <= influence_half_width → damage zone
        otherwise                                   → undisturbed rock

    The total disturbed thickness is therefore ``2 × influence_half_width``.
    """

    origin: Point3D
    strike_deg: Annotated[float, Field(ge=0, lt=360)]
    dip_deg: Annotated[float, Field(gt=0, le=90)]
    core_half_width: PositiveFloat = 2.5
    influence_half_width: PositiveFloat = 20.0
    core_penalty: NonNegativeFloat = 50.0
    damage_zone_penalty: NonNegativeFloat = 10.0

    @model_validator(mode="after")
    def _check_widths(self) -> FaultConfig:
        if self.influence_half_width < self.core_half_width:
            raise ValueError("influence_half_width must be >= core_half_width")
        return self


class RockQualityConfig(ApiModel):
    """Parameters of the seeded spatially-correlated rock-quality field
    (0–100 scale, RMR/Q-like but dimensionless and synthetic)."""

    mean: Annotated[float, Field(ge=0, le=100)] = 65.0
    std: NonNegativeFloat = 12.0
    correlation_length_xy: PositiveFloat = 80.0
    correlation_length_z: PositiveFloat = 40.0
    minimum: Annotated[float, Field(ge=0, le=100)] = 20.0
    maximum: Annotated[float, Field(ge=0, le=100)] = 90.0

    @model_validator(mode="after")
    def _check_range(self) -> RockQualityConfig:
        if self.maximum <= self.minimum:
            raise ValueError("maximum must be > minimum")
        if not (self.minimum <= self.mean <= self.maximum):
            raise ValueError("mean must lie within [minimum, maximum]")
        return self


class GeologyConfig(ApiModel):
    """Container for every synthetic geological field. Future members:
    water, lithology, alteration, joint sets, in-situ stress."""

    rock_quality: RockQualityConfig = Field(default_factory=RockQualityConfig)
    faults: list[FaultConfig] = Field(default_factory=list)


class FieldSamplingConfig(ApiModel):
    """NUMERICAL sampling resolution of the synthetic spatial fields
    (Phase 18, rule 127): the lattice spacing on which rock quality, grade
    and fault measurements are generated and interpolated. It is sampling
    support only — never a block size, an SMU, an ore block or any mining
    unit. The 10 m default keeps the Phase-17 numerical behaviour."""

    spacing_x: PositiveFloat = 10.0
    spacing_y: PositiveFloat = 10.0
    spacing_z: PositiveFloat = 10.0

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.spacing_x, self.spacing_y, self.spacing_z)


class RampConstraints(ApiModel):
    """Engineering constraints for the chained Hybrid-A* decline generator.

    ``max_gradient`` is vertical/horizontal (0.12 = 12 %)."""

    max_gradient: Annotated[float, Field(gt=0, le=0.25)] = 0.12
    min_turn_radius: PositiveFloat = 18.0
    tunnel_width: PositiveFloat = 5.0
    tunnel_height: PositiveFloat = 5.0
    clearance: NonNegativeFloat = 3.0
    footwall_access_offset: NonNegativeFloat = 20.0  # rule 29
    level_drift_gradient: Annotated[float, Field(ge=0, le=0.05)] = 0.0  # rule 30


class RestrictedZone(ApiModel):
    """Axis-aligned no-go box (v0.1). Points inside are invalid for design."""

    name: str = "restricted"
    min: Point3D
    max: Point3D

    @model_validator(mode="after")
    def _check_order(self) -> RestrictedZone:
        if self.min.x > self.max.x or self.min.y > self.max.y or self.min.z > self.max.z:
            raise ValueError("restricted zone min must be <= max on every axis")
        return self


class DeclineSearchConfig(ApiModel):
    """Chained Hybrid-A* settings (rules 47–55)."""

    xy_resolution: PositiveFloat = 5.0
    z_resolution: PositiveFloat = 1.0
    heading_bins: Annotated[int, Field(ge=8, le=72)] = 16
    # Chain-level bounded backtracking (rule 66 launchability follow-through):
    # when a level has no feasible candidate, the nearest ancestor level with
    # an untried candidate advances to its next deterministic pick and the
    # chain below is re-searched. Each accepted backtrack consumes one unit;
    # exhausting the budget fails the level explicitly.
    max_chain_backtracks: Annotated[int, Field(ge=0, le=200)] = 24
    grade_fractions: list[Annotated[float, Field(ge=0, le=1)]] = Field(
        default_factory=lambda: [0.0, 0.5, 1.0]
    )
    max_sample_spacing: PositiveFloat = 2.0
    goal_shot_radius_primitives: PositiveFloat = 5.0
    goal_shot_max_heading_change_deg: Annotated[float, Field(gt=0, le=90)] = 45.0
    vertical_tolerance: NonNegativeFloat = 0.5
    max_expansions_per_candidate: Annotated[int, Field(ge=100, le=5_000_000)] = 250_000
    max_candidates_per_level: Annotated[int, Field(ge=1, le=25)] = 5
    tie_break_bucket_primitives: NonNegativeFloat = 2.0
    # Added to every turning primitive's cost (in units of one straight
    # primitive at minimum cost). Keeps declines from zig-zagging; h ignores it.
    turn_penalty_factor: NonNegativeFloat = 0.5
    tie_break_mode: Literal["horizontal", "docking", "cone"] = "cone"
    # "cone" mode: while descending, prefer states on a ring of this many
    # minimum radii around the access target (a spiral-decline layout prior)
    standoff_radius_factor: PositiveFloat = 3.0
    # Weighted A*: f = g + ε·h with the admissible h (rule 25). ε = 1 is plain
    # A*; ε > 1 bounds suboptimality by ε and is what makes long descents
    # tractable when real cost/m exceeds the minimum used by h.
    heuristic_weight: Annotated[float, Field(ge=1.0, le=5.0)] = 2.0
    max_search_seconds: PositiveFloat | None = None
    allow_reverse_grade: bool = False  # reserved (rule 49)

    @model_validator(mode="after")
    def _check(self) -> DeclineSearchConfig:
        if not self.grade_fractions:
            raise ValueError("grade_fractions must not be empty")
        if self.allow_reverse_grade:
            raise ValueError("allow_reverse_grade is reserved for a future version")
        return self


class SmoothingConfig(ApiModel):
    """Phase 05 smoothing + revalidation parameters (rules 61–63)."""

    control_spacing: PositiveFloat = 5.0
    output_spacing: PositiveFloat = 2.0
    bending_weight: NonNegativeFloat = 1.0
    fidelity_weight: NonNegativeFloat = 0.1
    step_size: PositiveFloat = 0.03
    max_iterations: Annotated[int, Field(ge=1, le=10_000)] = 200
    max_deviation_from_raw: PositiveFloat = 10.0
    max_repairs: Annotated[int, Field(ge=0, le=10)] = 3
    repair_blend_factor: Annotated[float, Field(gt=0, lt=1)] = 0.5
    radius_numerical_tolerance: NonNegativeFloat = 0.05
    grade_numerical_tolerance: NonNegativeFloat = 1e-5
    max_field_cost_increase_pct: NonNegativeFloat = 5.0


class DesignConfig(ApiModel):
    """Phase 03 parameters: cost weights, exclusions and access-target
    lattice. Cost units are dimensionless 'cost per metre' with base 1.0;
    monetary calibration is out of scope for v0.1."""

    base_cost_per_m: PositiveFloat = 1.0
    rock_penalty_weight: NonNegativeFloat = 2.0
    orebody_exclusion_buffer: NonNegativeFloat = 5.0
    # Soft sterilization penalty decays from the hard buffer over this range.
    # buffer + range = 20 m = the default footwall access offset, so level
    # access targets at the design offset are neutral; closer is discouraged.
    orebody_sterilization_weight: NonNegativeFloat = 5.0
    orebody_sterilization_range: PositiveFloat = 15.0

    minimum_surface_cover: NonNegativeFloat = 0.0
    restricted_zones: list[RestrictedZone] = Field(default_factory=list)

    top_mining_margin: NonNegativeFloat = 10.0
    bottom_mining_margin: NonNegativeFloat = 10.0
    candidate_count: Annotated[int, Field(ge=1, le=25)] = 5
    candidate_along_strike_span: NonNegativeFloat = 100.0
    portal_footwall_distance: PositiveFloat = 350.0
    search: DeclineSearchConfig = Field(default_factory=DeclineSearchConfig)
    smoothing: SmoothingConfig = Field(default_factory=SmoothingConfig)


class TunnelProfile(ApiModel):
    """Horseshoe SHAPE + meshing parameters only (rules 65/67).

    Tunnel width and height come exclusively from ``RampConstraints`` —
    duplicating them here caused two dimension sources; Phase 06 removed the
    old ``width``/``crown_radius`` fields. The circular crown radius is
    DERIVED from (width, height, wall_height):
    ``rise = height − wall_height``, ``R_c = (a² + rise²) / (2·rise)`` with
    ``a = width / 2`` — never an independent input."""

    wall_height: PositiveFloat = 2.5
    arch_segments: Annotated[int, Field(ge=2, le=64)] = 16
    ring_max_spacing: PositiveFloat = 2.0
    ring_max_turn_deg: PositiveFloat = 7.0
    crease_angle_deg: Annotated[float, Field(gt=0, lt=180)] = 40.0

    @model_validator(mode="before")
    @classmethod
    def _drop_deprecated_dimensions(cls, data: Any) -> Any:
        """Deprecated migration: pre-Phase-06 scenarios persisted ``width`` and
        ``crownRadius`` here; both are ignored — dimensions come exclusively
        from ``RampConstraints`` and the crown radius is derived (rule 65/67)."""
        if isinstance(data, dict):
            for legacy in ("width", "crownRadius", "crown_radius"):
                data.pop(legacy, None)
        return data


class MiningConfig(ApiModel):
    method: MiningMethodType = MiningMethodType.LONGHOLE_OPEN_STOPING
    sublevel_interval: PositiveFloat = 25.0
    stope_length: PositiveFloat = 30.0
    minimum_pillar: NonNegativeFloat = 5.0


# --------------------------------------------------------------------------- #
# Scenario document
# --------------------------------------------------------------------------- #


class CommunicationConfig(ApiModel):
    """Phase 11 communication planning parameters (rules 87–92). All
    defaults are explicitly SYNTHETIC planning/demo assumptions — not
    measured RF parameters, vendor specifications, or regulatory
    thresholds. Coverage/backhaul ranges are NETWORK-GEODESIC tunnel
    distances (rule 88), never Euclidean through-rock distances."""

    asset_type: AssetType = AssetType.MESH_ROUTER
    candidate_spacing_m: PositiveFloat = 40.0
    demand_spacing_m: PositiveFloat = 20.0
    coverage_range_m: PositiveFloat = 100.0
    backhaul_range_m: PositiveFloat = 120.0
    required_coverage_fraction: float = Field(default=1.0, gt=0.0, le=1.0)

    @model_validator(mode="after")
    def _candidate_lattice_can_chain(self) -> CommunicationConfig:
        # guarantees the deterministic candidate lattice can, in principle,
        # maintain a backhaul chain along every continuously developed edge
        if self.candidate_spacing_m > self.backhaul_range_m:
            raise ValueError(
                "candidateSpacingM must be <= backhaulRangeM so the candidate "
                "lattice can maintain a backhaul chain along every edge"
            )
        return self


class SensorConfig(ApiModel):
    """Phase 12 sensor placement parameters (rules 93–98). All defaults are
    explicitly SYNTHETIC planning/demo assumptions. ``monitoring_range_m``
    is the maximum allowed MineNetwork PATH distance between a monitoring
    demand and a selected sensor under the layout proxy (rule 95) — it is
    NOT a manufacturer's detection range, gas transport radius or
    probability-of-detection model."""

    asset_type: AssetType = AssetType.GAS_SENSOR
    candidate_spacing_m: PositiveFloat = 40.0
    demand_spacing_m: PositiveFloat = 20.0
    monitoring_range_m: PositiveFloat = 60.0
    required_coverage_fraction: float = Field(default=1.0, gt=0.0, le=1.0)

    @model_validator(mode="after")
    def _candidate_lattice_feasible(self) -> SensorConfig:
        # simple feasibility guarantee for the deterministic candidate
        # lattice on continuously represented tunnel edges
        if self.candidate_spacing_m > 2.0 * self.monitoring_range_m:
            raise ValueError(
                "candidateSpacingM must be <= 2 * monitoringRangeM so the "
                "candidate lattice can cover continuously developed edges"
            )
        return self


class InfrastructureConfig(ApiModel):
    """Phase 11+ infrastructure planning configuration."""

    communication: CommunicationConfig = Field(default_factory=CommunicationConfig)
    sensors: SensorConfig = Field(default_factory=SensorConfig)


class ScheduleConfig(ApiModel):
    """Phase 10 temporal planning parameters (rule 82). Transparent
    configurable SYNTHETIC baseline defaults for a research/demo timeline —
    NOT calibrated productivity claims. The timeline is expressed in
    relative continuous days from startDay 0; no calendars/shifts."""

    ramp_advance_m_per_day: PositiveFloat = 4.0
    drift_advance_m_per_day: PositiveFloat = 5.0
    crosscut_advance_m_per_day: PositiveFloat = 4.0
    stope_preparation_days: PositiveFloat = 5.0
    stoping_tonnes_per_day: PositiveFloat = 1000.0
    mucking_tonnes_per_day: PositiveFloat = 1500.0
    backfill_m3_per_day: PositiveFloat = Field(default=500.0, alias="backfillM3PerDay")
    backfill_cure_days: PositiveFloat = 7.0


class ScenarioCreate(ApiModel):
    """Payload for ``POST /scenarios``. Every field has a default so an empty
    body produces a valid baseline scenario."""

    name: str = "Untitled synthetic mine"
    seed: int = 42
    world: WorldConfig = Field(default_factory=WorldConfig)
    terrain: TerrainConfig = Field(default_factory=TerrainConfig)
    orebody: OrebodyConfig = Field(
        default_factory=lambda: OrebodyConfig(
            center=Point3D(x=200.0, y=100.0, z=0.0),
            strike_deg=35.0,
            dip_deg=70.0,
            length=600.0,
            height=350.0,
            thickness=12.0,
            mean_grade=4.2,
        )
    )
    geology: GeologyConfig = Field(default_factory=GeologyConfig)
    field_sampling: FieldSamplingConfig = Field(default_factory=FieldSamplingConfig)
    portal: Point3D | None = Field(
        default=None,
        description="Portal location on the terrain surface. If None, Phase 03 picks one.",
    )
    ramp: RampConstraints = Field(default_factory=RampConstraints)
    design: DesignConfig = Field(default_factory=DesignConfig)
    tunnel_profile: TunnelProfile = Field(default_factory=TunnelProfile)
    mining: MiningConfig = Field(default_factory=MiningConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    infrastructure: InfrastructureConfig = Field(default_factory=InfrastructureConfig)

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_block_model(cls, data: Any) -> Any:
        """Schema v1 → v2 (Phase 18): the persisted ``blockModel {dx, dy, dz}``
        becomes ``fieldSampling {spacingX, spacingY, spacingZ}``. The numbers
        are identical — only the semantics changed from mining-block size to
        numerical field spacing. A document carrying BOTH keys is rejected
        (``extra="forbid"`` sees the leftover legacy key)."""
        if isinstance(data, dict) and "fieldSampling" not in data and "field_sampling" not in data:
            legacy = data.pop("blockModel", None)
            if legacy is None:
                legacy = data.pop("block_model", None)
            if isinstance(legacy, dict):
                data = dict(data)
                data["fieldSampling"] = {
                    "spacingX": legacy.get("dx", 10.0),
                    "spacingY": legacy.get("dy", 10.0),
                    "spacingZ": legacy.get("dz", 10.0),
                }
        return data


class ScenarioRealizeRequest(ApiModel):
    """Body of the NON-persistent ``POST /scenarios/realize`` (Phase 17):
    the response is a fully resolved ScenarioCreate the client may inspect,
    edit and then submit to the existing ``POST /scenarios``."""

    preset: ScenarioPreset = ScenarioPreset.BASELINE
    seed: int = 42
    fault_count: Annotated[int, Field(ge=0, le=6)] | None = None


#: persisted-document schema version. 1 = Phase 02–17 (``blockModel``);
#: 2 = Phase 18 (``fieldSampling``, spatial-field arrays.npz).
SCENARIO_SCHEMA_VERSION = 2


class Scenario(ScenarioCreate):
    """Persisted scenario document."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    schema_version: int = SCENARIO_SCHEMA_VERSION


class ScenarioSummary(ApiModel):
    id: str
    name: str
    seed: int


class HealthResponse(ApiModel):
    status: str
    app: str
    version: str
    coordinate_system: str


class ErrorDetail(ApiModel):
    code: str
    message: str
