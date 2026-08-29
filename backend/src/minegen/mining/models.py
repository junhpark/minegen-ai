"""Phase 09 stope typed contract (rules 75–80).

``derived/stopes.json`` is the validated geometry artifact that OWNS planned
stope geometry (rule 75): the analytic ``TabularOrebody`` local frame
``(u = strike, v = down-dip, w = thickness normal)`` is the geometric source
of truth and the backend owns all engineering geometry (rule 80). A stope is
a production VOLUME, not a development — it never becomes a MineNetwork edge;
its two Phase 08 ``STOPE_ACCESS`` anchors are the link to the network
(rule 76). Volumes/tonnages/grades here are deterministic PLANNING
quantities, never reserve or resource estimates.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from minegen.core.models import ApiModel


class StopeLocalBounds(ApiModel):
    """Axis-aligned bounds in the analytic orebody local frame."""

    u_min: float
    u_max: float
    v_min: float
    v_max: float
    w_min: float
    w_max: float


class StopeGeometry(ApiModel):
    """World-space (backend ENU) prism mesh: 8 corner vertices as a flat
    ``[x0, y0, z0, …]`` list and 12 outward-wound triangles. The frontend
    only assembles this — it never derives stope geometry (rule 80)."""

    vertices: list[float]  # 24 floats
    triangle_indices: list[int]  # 36 ints


class StopeReport(ApiModel):
    upper_anchor_error: float  # max(face error, |u − stationU|) at the terminal
    lower_anchor_error: float
    hard_invalid_samples: int  # world/terrain/cover/zone violations in the prism
    strike_pillar_clearance: float | None = None  # min gap to strike neighbours
    finite: bool
    valid: bool
    failure_reason: str | None = None


class Stope(ApiModel):
    id: str
    method: Literal["LONGHOLE_OPEN_STOPING"]
    station_index: int
    station_u: float
    upper_level_id: str
    lower_level_id: str
    upper_access_node_id: str
    lower_access_node_id: str
    local_bounds: StopeLocalBounds
    geometry: StopeGeometry
    strike_length: float
    down_dip_span: float
    vertical_height: float
    thickness: float
    geometric_volume_m3: float = Field(alias="geometricVolumeM3")
    tonnes: float
    mean_grade_proxy: float | None  # planning proxy only — NOT a reserve/resource
    report: StopeReport
    planned_state: Literal["PLANNED"] = "PLANNED"  # Phase 10 owns transitions


class StopesMetrics(ApiModel):
    stope_count: int
    level_interval_count: int
    stations_per_interval: int
    total_geometric_volume_m3: float = Field(alias="totalGeometricVolumeM3")
    total_tonnes: float
    geometric_extraction_fraction_of_orebody: float
    weighted_mean_grade_proxy: float | None


class StopesPayload(ApiModel):
    status: Literal["SUCCESS", "FAILED"]
    failure_reason: str | None
    source_revision: str
    method: str  # the REQUESTED scenario method, even when unsupported
    stopes: list[Stope]
    metrics: StopesMetrics | None
