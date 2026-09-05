"""Phase 07 MineNetwork typed contract (rules 13, 68–70).

This is the graph contract later phases consume: the persisted
``derived/network.json`` and the ``/network`` API responses are exactly the
deterministic camelCase serialization of these models — never a raw NetworkX
serialization. ``networkx`` stays strictly the in-memory topology engine.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from minegen.core.models import ApiModel


class NodeType(StrEnum):
    PORTAL = "PORTAL"
    LEVEL_ENTRY = "LEVEL_ENTRY"
    JUNCTION = "JUNCTION"  # reserved (Phase 08+)
    STOPE_ACCESS = "STOPE_ACCESS"  # reserved (Phase 09+)
    RAMP_JUNCTION = "RAMP_JUNCTION"  # Phase 20B: turnout on the main ramp
    RAMP_END = "RAMP_END"  # Phase 20B: main-ramp terminal below the last turnout


class EdgeType(StrEnum):
    RAMP = "RAMP"
    LEVEL_ACCESS = "LEVEL_ACCESS"  # Phase 20B: RAMP_JUNCTION → LEVEL_ENTRY branch
    DRIFT = "DRIFT"  # reserved (Phase 08+)
    CROSSCUT = "CROSSCUT"  # reserved (Phase 08+)
    RAISE = "RAISE"  # reserved
    SHAFT = "SHAFT"  # reserved


class CrossSection(ApiModel):
    width: float
    height: float
    analytic_area: float


class GeometryRef(ApiModel):
    """Reference into the validated centerline artifact that owns the
    development (rule 68); the network never duplicates the polyline."""

    artifact: str
    segment_index: int


class SimulationSlots(ApiModel):
    """Typed RESERVED simulation attributes (architecture §4): later phases
    fill these; until then the only legal value per slot is ``null``."""

    haulage: None = None
    ventilation: None = None
    communication: None = None
    rock_risk: None = None


class NetworkNode(ApiModel):
    id: str
    type: NodeType
    position: tuple[float, float, float]
    level_id: str | None = None
    candidate_id: str | None = None
    elevation: float | None = None
    station_index: int | None = None  # Phase 08 crosscut station k
    #: Phase 20B RAMP_JUNCTION: chainage along the main ramp (m)
    chainage: float | None = None
    station_u: float | None = None  # strike coordinate of the station


class NetworkEdge(ApiModel):
    id: str
    type: EdgeType
    from_node: str
    to_node: str
    # explicit alias: the established artifact contract uses "length3d"
    # (matching the Phase 06 report), not to_camel's "length3D"
    length3d: float = Field(alias="length3d")
    mean_gradient_signed: float  # Δz / horizontal length; negative = descending
    max_abs_gradient: float  # always ≥ 0
    cross_section: CrossSection
    effective_source: Literal["SMOOTHED", "RAW_FALLBACK", "ANALYTIC", "PARAMETRIC_V2"]
    field_cost: float
    geometry_ref: GeometryRef
    simulation: SimulationSlots


class NetworkMetrics(ApiModel):
    node_count: int
    edge_count: int
    level_count: int
    junction_count: int = 0
    #: Phase 20B
    ramp_junction_count: int = 0
    level_access_edge_count: int = 0
    total_level_access_length3d: float = Field(alias="totalLevelAccessLength3d", default=0.0)
    stope_access_count: int = 0
    drift_edge_count: int = 0
    crosscut_edge_count: int = 0
    total_ramp_length3d: float = Field(alias="totalRampLength3d")
    total_drift_length3d: float = Field(alias="totalDriftLength3d", default=0.0)
    total_crosscut_length3d: float = Field(alias="totalCrosscutLength3d", default=0.0)
    minimum_elevation: float
    vertical_drop_from_portal: float


class NetworkValidation(ApiModel):
    max_node_sync_error: float
    max_edge_length_sync_error: float = 0.0  # recomputed vs declared (rule 13)
    sync_tolerance: float
    synchronized: bool
    connected: bool
    connected_components: int


class SurfacePathEntry(ApiModel):
    node_id: str
    level_id: str
    independent_surface_paths: int
    meets_criterion: bool


class SurfacePathAdvisory(ApiModel):
    """Design-redundancy advisory only — no statutory or regulatory
    compliance claim (rule 70)."""

    criterion: str
    required_paths: int
    advisory_only: bool
    per_node: list[SurfacePathEntry]


class NetworkPayload(ApiModel):
    status: Literal["SUCCESS", "FAILED"]
    failure_reason: str | None
    source_revision: str
    nodes: list[NetworkNode]
    edges: list[NetworkEdge]
    metrics: NetworkMetrics | None
    validation: NetworkValidation | None
    surface_path_advisory: list[SurfacePathAdvisory]
