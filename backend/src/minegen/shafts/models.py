"""Phase 20C.2B shaft artifact contract (rules 182–184).

``derived/shafts.json`` is the validated geometry artifact that OWNS every
shaft: collar, axis segments, bottom, level stations and the station
access drives. It is the only owner of that geometry — MineNetwork references
it through ``GeometryRef{artifact: "shafts.json", segmentIndex}`` into the
flat ``centerlines`` list and never duplicates a polyline (rule 68).

The persisted payload is exactly the deterministic camelCase serialization
of these models. Capability semantics (who may use a shaft for what) live in
``capability_graph.json`` (rule 185), never here.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from minegen.core.enums import Capability, ShaftRole
from minegen.core.models import ApiModel


class ShaftFailureCode(StrEnum):
    """Typed shaft-planning failures (directive §19). Geometry-level
    causes wrap the shared ``RejectionReason`` gates of the design cost
    evaluator; no gate is re-implemented."""

    SHAFT_COLLAR_OUT_OF_BOUNDS = "SHAFT_COLLAR_OUT_OF_BOUNDS"
    SHAFT_TERRAIN_INVALID = "SHAFT_TERRAIN_INVALID"
    SHAFT_BOTTOM_OUT_OF_BOUNDS = "SHAFT_BOTTOM_OUT_OF_BOUNDS"
    SHAFT_OREBODY_INTERSECTION = "SHAFT_OREBODY_INTERSECTION"
    SHAFT_RESTRICTED_ZONE_INTERSECTION = "SHAFT_RESTRICTED_ZONE_INTERSECTION"
    SHAFT_CLEARANCE_VIOLATION = "SHAFT_CLEARANCE_VIOLATION"
    SHAFT_STATION_LEVEL_MISMATCH = "SHAFT_STATION_LEVEL_MISMATCH"
    SHAFT_STATION_CONNECTION_INFEASIBLE = "SHAFT_STATION_CONNECTION_INFEASIBLE"
    SHAFT_NO_SERVICEABLE_LEVELS = "SHAFT_NO_SERVICEABLE_LEVELS"
    SHAFT_GEOMETRY_INVALID = "SHAFT_GEOMETRY_INVALID"


class Centerline(ApiModel):
    points: list[float]  # flat [x0, y0, z0, x1, …] — same shape as Phase 05/08


class ShaftCenterline(ApiModel):
    """One owned polyline. ``id`` equals the MineNetwork edge id derived from
    it, so a ``geometryRef.segmentIndex`` resolves in one lookup."""

    id: str
    shaft_id: str
    kind: Literal["SHAFT_SEGMENT", "STATION_ACCESS"]
    level_id: str | None = None
    centerline: Centerline
    length3d: float = Field(alias="length3d")


class ConnectionTarget(ApiModel):
    """The EXISTING level-development node a station drive reaches (rule
    183): the LEVEL_ENTRY or a drift breakpoint (station JUNCTION) of the
    served level, identified by its along-backbone coordinate ``u`` so the
    network builder welds the drive onto the node it already creates."""

    node_kind: Literal["LEVEL_ENTRY", "JUNCTION"]
    level_id: str
    station_u: float
    position: tuple[float, float, float]
    plan_distance_to_axis: float


class StationConnectionReport(ApiModel):
    length3d: float = Field(alias="length3d")
    horizontal_length: float
    mean_gradient_signed: float
    max_abs_gradient: float
    centerline_invalid_samples: int
    envelope_hard_violations: int
    envelope_above_terrain: int
    field_cost: float
    rejection_counts: dict[str, int] = Field(default_factory=dict)


class ShaftStation(ApiModel):
    station_id: str
    level_id: str
    elevation: float
    point: tuple[float, float, float]
    connection_target: ConnectionTarget | None
    #: index into ``ShaftsPayload.centerlines`` of the station drive
    access_centerline_index: int | None
    report: StationConnectionReport | None
    status: Literal["OK", "FAILED"]
    failure_code: ShaftFailureCode | None = None
    failure_reason: str | None = None


class ShaftProfile(ApiModel):
    shape: Literal["CIRCULAR"] = "CIRCULAR"
    diameter: float
    analytic_area: float


class ShaftValidation(ApiModel):
    """Explicit hard-validation record of the shaft AXIS and its circular
    excavation envelope (rule 183)."""

    axis_samples: int
    axis_invalid_samples: int
    envelope_samples: int
    envelope_invalid_samples: int
    envelope_above_terrain_below_collar_zone: int
    sample_spacing: float
    rejection_counts: dict[str, int] = Field(default_factory=dict)
    valid: bool


class ShaftMetrics(ApiModel):
    depth: float  # collar z − bottom z
    station_count: int
    total_shaft_length3d: float = Field(alias="totalShaftLength3d")
    total_station_access_length3d: float = Field(alias="totalStationAccessLength3d")
    nominal_excavation_volume: float  # π (d/2)² × depth


class Shaft(ApiModel):
    shaft_id: str
    role: ShaftRole
    #: declared capability set (rule 185) — copied from the spec so the
    #: capability builder reads ONE persisted source per shaft
    capabilities: list[Capability]
    profile: ShaftProfile
    collar: tuple[float, float, float]
    collar_source: Literal["EXPLICIT", "DEFAULT_DERIVED"]
    bottom: tuple[float, float, float]
    stations: list[ShaftStation]
    #: indices into ``ShaftsPayload.centerlines`` of the axis segments in
    #: collar → bottom order (collar→STN₁, STN₁→STN₂, …, STNₙ→bottom)
    segment_indices: list[int]
    validation: ShaftValidation | None
    metrics: ShaftMetrics | None
    status: Literal["OK", "FAILED"]
    failure_code: ShaftFailureCode | None = None
    failure_reason: str | None = None


class ShaftsMetrics(ApiModel):
    shaft_count: int
    station_count: int
    total_shaft_length3d: float = Field(alias="totalShaftLength3d")
    total_station_access_length3d: float = Field(alias="totalStationAccessLength3d")
    planning_seconds: float


class ShaftsPayload(ApiModel):
    status: Literal["SUCCESS", "FAILED"]
    failure_reason: str | None
    source_revision: str
    #: revision of the ``levels.json`` the stations were connected to
    levels_revision: str
    shafts: list[Shaft]
    #: flat owned-polyline list — the ``geometryRef.segmentIndex`` space
    centerlines: list[ShaftCenterline]
    metrics: ShaftsMetrics | None
