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

from typing import Any, Literal

from pydantic import Field

from minegen.core.enums import MiningMethodType
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


# --------------------------------------------------------------------------- #
# Phase 21B/C — method-specific production payloads (ONE active production
# artifact; ``derived/stopes.json`` is the compatibility path, its payload
# is the union below, discriminated by ``method``)
# --------------------------------------------------------------------------- #


class LocalBounds(ApiModel):
    """Axis-aligned bounds in the analytic orebody local frame (u strike,
    v down-dip, w thickness normal) — the Phase 21B/C production frame."""

    u_min: float
    u_max: float
    v_min: float
    v_max: float
    w_min: float
    w_max: float


class SolidGeometry(ApiModel):
    """World-space (backend ENU) closed prism mesh: 8 corner vertices as a flat
    ``[x0, y0, z0, …]`` list and 12 outward-wound triangles. Authoritative
    backend geometry; the frontend assembles it verbatim and MineExchange
    exports it verbatim — never re-derived from the bounds."""

    vertices: list[float]
    triangle_indices: list[int]


class ProductionReport(ApiModel):
    """Hard-QA record of one production solid: independent mesh QA
    (finite / indices / degenerate / manifold / watertight / outward) plus
    the analytic ↔ mesh volume agreement and the hard-evaluator sampling."""

    hard_invalid_samples: int
    mesh_closed_solid: bool
    mesh_volume_m3: float = Field(alias="meshVolumeM3")
    volume_agreement: bool
    finite: bool
    valid: bool
    failure_reason: str | None = None


# -- Cut & Fill (Phase 21B) --------------------------------------------------- #


class CutFillLift(ApiModel):
    """One lift of a level interval: an equal partition of the down-dip
    interval between two adjacent levels into ≈ ``liftHeightM`` vertical
    slices, ordered bottom → top."""

    lift_index: int  # 0 = the bottom lift of the whole body, increasing upward
    lower_level_id: str
    upper_level_id: str
    v_min: float
    v_max: float
    vertical_height: float
    cut_ids: list[str]


class CutFillCut(ApiModel):
    id: str
    method: Literal["CUT_AND_FILL"]
    lift_index: int
    cut_index: int
    lower_level_id: str
    upper_level_id: str
    #: the production access CROSSCUT this cut is mined from (levels.json id)
    access_development_id: str
    local_bounds: LocalBounds
    geometry: SolidGeometry
    strike_length: float
    down_dip_span: float
    vertical_height: float
    thickness: float
    geometric_volume_m3: float = Field(alias="geometricVolumeM3")
    tonnes: float
    mean_grade_proxy: float | None  # planning proxy only — NOT a reserve/resource
    planned_state: Literal["PLANNED"] = "PLANNED"
    report: ProductionReport


class CutFillBackfill(ApiModel):
    """Backfill of ONE cut: references the cut's void geometry (1:1), never a
    second copy of the vertices."""

    id: str
    source_cut_id: str
    volume_m3: float = Field(alias="volumeM3")


class CutFillMetrics(ApiModel):
    cut_count: int
    backfill_count: int
    lift_count: int
    level_interval_count: int
    total_geometric_volume_m3: float = Field(alias="totalGeometricVolumeM3")
    total_tonnes: float
    geometric_extraction_fraction_of_orebody: float
    weighted_mean_grade_proxy: float | None
    actual_mean_lift_height: float
    actual_mean_cut_length: float


class CutFillPayload(ApiModel):
    status: Literal["SUCCESS", "FAILED"]
    failure_reason: str | None
    source_revision: str
    method: Literal["CUT_AND_FILL"]
    lifts: list[CutFillLift]
    cuts: list[CutFillCut]
    backfills: list[CutFillBackfill]
    metrics: CutFillMetrics | None


# -- Room & Pillar (Phase 21C) ----------------------------------------------- #


class PlanBounds(ApiModel):
    """Plan-frame (u, v) bounds of one grid cell."""

    u_min: float
    u_max: float
    v_min: float
    v_max: float


class RoomCell(ApiModel):
    """Semantic parent of the extraction stages of one ROOM grid cell; it owns
    no geometry — the extraction units do."""

    id: str
    row_index: int
    column_index: int
    local_plan_bounds: PlanBounds
    #: the production access CROSSCUT (levels.json id) this room is mined from
    access_development_id: str
    extraction_unit_ids: list[str]


ExtractionStage = Literal["HEADING", "BENCH_1", "BENCH_2"]


class RoomExtractionUnit(ApiModel):
    id: str
    room_id: str
    stage: ExtractionStage
    bench_index: int  # 0 = HEADING, 1 = BENCH_1, 2 = BENCH_2
    local_bounds: LocalBounds
    geometry: SolidGeometry
    geometric_volume_m3: float = Field(alias="geometricVolumeM3")
    tonnes: float
    mean_grade_proxy: float | None
    planned_state: Literal["PLANNED"] = "PLANNED"
    report: ProductionReport


class Pillar(ApiModel):
    """RETAINED in-situ material solid — never an excavation, never a
    MineNetwork edge, never a geotechnical certification. ``tonnesEquivalent``
    is the planning mass proxy of the material left in place, not a
    recoverable reserve."""

    id: str
    row_index: int
    column_index: int
    local_bounds: LocalBounds
    geometry: SolidGeometry
    geometric_volume_m3: float = Field(alias="geometricVolumeM3")
    tonnes_equivalent: float
    mean_grade_proxy: float | None
    report: ProductionReport


class RoomPillarMetrics(ApiModel):
    room_count: int
    extraction_unit_count: int
    pillar_count: int
    heading_count: int
    bench_count: int
    total_mined_volume_m3: float = Field(alias="totalMinedVolumeM3")
    total_pillar_volume_m3: float = Field(alias="totalPillarVolumeM3")
    panel_volume_m3: float = Field(alias="panelVolumeM3")
    total_mined_tonnes: float
    #: mined / panel geometry fraction — a planning geometry fraction, never a
    #: recovery prediction
    geometric_extraction_fraction: float
    weighted_mean_grade_proxy: float | None


class RoomPillarPayload(ApiModel):
    status: Literal["SUCCESS", "FAILED"]
    failure_reason: str | None
    source_revision: str
    method: Literal["ROOM_AND_PILLAR"]
    rooms: list[RoomCell]
    extraction_units: list[RoomExtractionUnit]
    pillars: list[Pillar]
    metrics: RoomPillarMetrics | None


#: the ACTIVE production payload — exactly one per scenario, discriminated by
#: ``method``. ``StopesPayload`` is the Longhole payload AND the historic typed
#: FAILED boundary of the reserved methods (``method`` = the requested one).
ProductionPayload = StopesPayload | CutFillPayload | RoomPillarPayload

_PRODUCTION_PAYLOAD_CLASSES: dict[MiningMethodType, type[ApiModel]] = {
    MiningMethodType.LONGHOLE_OPEN_STOPING: StopesPayload,
    MiningMethodType.CUT_AND_FILL: CutFillPayload,
    MiningMethodType.ROOM_AND_PILLAR: RoomPillarPayload,
    MiningMethodType.SUBLEVEL_CAVING: StopesPayload,
    MiningMethodType.SHRINKAGE_STOPING: StopesPayload,
}


def production_payload_class(method: MiningMethodType) -> type[ApiModel]:
    """The typed payload class the persisted production artifact of ``method``
    must satisfy (a STRUCTURAL contract of the artifact — the registry, not
    this table, decides whether a method is implemented)."""
    return _PRODUCTION_PAYLOAD_CLASSES[method]


def parse_production_payload(raw: Any) -> ProductionPayload:
    """READ ≠ TRUST structural parse of the active production artifact: the
    document's own ``method`` selects the typed class; a payload whose shape
    does not satisfy that class is a ``ValueError`` (the reader reports
    ARTIFACT_MALFORMED). No method fallback, no cross-method normalization."""
    if not isinstance(raw, dict):
        raise ValueError("production payload is not a JSON object")
    try:
        method = MiningMethodType(str(raw.get("method")))
    except ValueError as err:
        raise ValueError(f"unknown production method {raw.get('method')!r}") from err
    cls = production_payload_class(method)
    payload = cls.model_validate(raw)
    if not isinstance(payload, StopesPayload | CutFillPayload | RoomPillarPayload):
        raise ValueError("production payload class is not a production payload")
    return payload
