"""MineResult 1.0 — the canonical external-simulation RESULT contract
(Phase 23C, rules 213–218).

A MineResult is an OBSERVATION of the mine made by an external application
over a MineExchange bundle: it is bound to the exact ``sourceSnapshot`` of
that bundle and to stable MineExchange ids (network edge ids), it lives
outside ``derived/*`` and it is never a design, topology, production,
timeline or economics authority. MineExchange stays at 1.3.0 — results are
not a mine description.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from minegen.core.models import ApiModel
from minegen.exchange.models import SourceSnapshot

MINE_RESULT_VERSION = "1.0.0"

ResultDomain = Literal["VENTILATION", "OPERATIONS"]
SourceApplication = Literal["VENTSIM", "ANYLOGIC"]
TimeAxisKind = Literal["STATIC", "ELAPSED_SECONDS", "MINE_DAY"]
Compatibility = Literal["COMPATIBLE", "STALE"]
Placement = Literal["SAMPLE", "INTERPOLATED"]

#: canonical SI units per ventilation metric (directive §27 / §30); every
#: imported value is stored in these units, converted only through an
#: EXPLICIT declaration in the package manifest
VENTILATION_METRICS: dict[str, str] = {
    "airflowM3s": "m3/s",
    "velocityMs": "m/s",
    "pressurePa": "Pa",
    "pressureLossPa": "Pa",
    "temperatureDryC": "degC",
    "temperatureWetC": "degC",
    "airDensityKgM3": "kg/m3",
}
#: directive §28: positive airflow = MineNetwork edge sourceNodeId → targetNodeId
AIRFLOW_SIGN_CONVENTION = (
    "positive airflow flows from the MineNetwork edge sourceNodeId toward its targetNodeId; "
    "negative flows targetNodeId -> sourceNodeId. The edge direction is the sign reference "
    "axis only, never a traffic direction."
)
#: operations edge metrics (directive §39) with their canonical units
OPERATIONS_EDGE_METRICS: dict[str, str] = {
    "utilization": "fraction",
    "queueCount": "count",
    "haulageTonnesPerHour": "t/h",
    "travelTimeSeconds": "s",
}
#: known summary metrics promoted to typed fields (directive §40); anything
#: else is recorded by name only and carries no authority
OPERATIONS_SUMMARY_METRICS: dict[str, str] = {
    "totalHauledTonnes": "t",
    "meanCycleTimeSeconds": "s",
    "meanUtilization": "fraction",
    "simulatedDurationSeconds": "s",
    "vehicleCount": "count",
}
TIME_AXIS_UNITS: dict[str, str | None] = {
    "STATIC": None,
    "ELAPSED_SECONDS": "s",
    "MINE_DAY": "day",
}


# --------------------------------------------------------------------------- #
# the import package manifest (result_manifest.json — written by the round-trip
# kit, completed by the user / the external tool)
# --------------------------------------------------------------------------- #


class PackageTimeAxis(ApiModel):
    kind: TimeAxisKind


class ResultUnitConversion(ApiModel):
    """An EXPLICIT declaration that ``metric`` is delivered in ``sourceUnit``
    and maps to the canonical unit as ``canonical = value × factor + offset``.
    Without it a non-canonical unit is RESULT_UNIT_UNSUPPORTED — never
    inferred."""

    metric: str
    source_unit: str
    factor: float
    offset: float = 0.0


class ResultPackageManifest(ApiModel):
    mine_result_version: str
    result_domain: ResultDomain
    source_application: SourceApplication
    source_application_version: str | None = None
    source_adapter: str
    source_adapter_version: str
    source_mine_exchange_version: str
    source_scenario_id: str
    source_snapshot: SourceSnapshot
    run_label: str = ""
    description: str = ""
    time_axis: PackageTimeAxis
    #: declared unit per metric column (canonical, or converted through
    #: ``unitConversions``); a metric column without a declared unit is
    #: refused
    units: dict[str, str] = Field(default_factory=dict)
    unit_conversions: list[ResultUnitConversion] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# the stored / exported MineResult manifest
# --------------------------------------------------------------------------- #


class ResultTimeAxis(ApiModel):
    kind: TimeAxisKind
    unit: str | None
    sample_count: int
    start: float | None
    end: float | None


class ResultFile(ApiModel):
    path: str
    sha256: str
    media_type: str
    semantic: str


class ResultMetricAvailability(ApiModel):
    name: str
    unit: str
    available: bool
    sample_count: int
    min: float | None
    max: float | None


class ResultProvenance(ApiModel):
    source_application: SourceApplication
    source_application_version: str
    source_adapter_name: str
    source_adapter_version: str
    source_mine_exchange_version: str
    source_scenario_id: str
    #: SHA-256 of the ZIP the user imported (the raw evidence, kept as source.zip)
    original_file_sha256: str
    imported_file_names: list[str]


class ResultCounts(ApiModel):
    edge_count: int
    time_count: int
    sample_count: int
    vehicle_count: int = 0
    edge_metric_sample_count: int = 0


class ResultSummaryMetric(ApiModel):
    name: str
    value: float
    unit: str


class MineResultManifest(ApiModel):
    mine_result_version: str
    result_id: str
    result_domain: ResultDomain
    source_application: SourceApplication
    source_adapter: str
    source_adapter_version: str
    source_mine_exchange_version: str
    source_scenario_id: str
    source_snapshot: SourceSnapshot
    run_label: str
    description: str
    time_axis: ResultTimeAxis
    files: list[ResultFile]
    metrics: list[ResultMetricAvailability]
    summary_metrics: list[ResultSummaryMetric]
    counts: ResultCounts
    provenance: ResultProvenance
    import_source_sha256: str
    normalized_sha256: str
    sign_convention: str | None
    notes: list[str]


# --------------------------------------------------------------------------- #
# API payloads
# --------------------------------------------------------------------------- #


class ResultSummary(ApiModel):
    result_id: str
    domain: ResultDomain
    source_application: SourceApplication
    run_label: str
    description: str
    compatibility: Compatibility
    source_snapshot: SourceSnapshot
    time_axis: ResultTimeAxis
    metrics: list[ResultMetricAvailability]
    counts: ResultCounts
    mine_result_version: str


class ResultDetail(ResultSummary):
    provenance: ResultProvenance
    summary_metrics: list[ResultSummaryMetric]
    files: list[ResultFile]
    sign_convention: str | None
    notes: list[str]
    import_source_sha256: str
    normalized_sha256: str


class ResultListPayload(ApiModel):
    scenario_id: str
    results: list[ResultSummary]


class ResultImportPayload(ApiModel):
    """``created`` is False when an identical result (same deterministic
    resultId) was already stored: the import is idempotent and the existing
    folder is kept untouched."""

    created: bool
    result: ResultDetail


class ResultEdgeGeometry(ApiModel):
    edge_id: str
    edge_type: str
    source_node_id: str
    target_node_id: str
    #: LOCAL_ENU_Z_UP metres, the MineExchange centerline of the SOURCE
    #: snapshot (chainage 0 = first point = sourceNodeId side)
    points: list[list[float]]


class ResultGeometryPayload(ApiModel):
    result_id: str
    coordinate_frame: str
    edges: list[ResultEdgeGeometry]


class EdgeValue(ApiModel):
    edge_id: str
    value: float


class VentilationFrame(ApiModel):
    result_id: str
    metric: str
    unit: str
    time_axis_kind: TimeAxisKind
    #: the requested time (None for STATIC)
    time: float | None
    #: the SOURCE sample time actually shown (hold-last; None for STATIC)
    sample_time: float | None
    values: list[EdgeValue]
    #: edges of the result without a value at this sample (never zero-filled)
    missing_edge_ids: list[str]
    min: float | None
    max: float | None
    sign_convention: str | None


class OperationsVehicle(ApiModel):
    agent_id: str
    agent_kind: str | None
    x: float
    y: float
    z: float
    edge_id: str
    chainage_fraction: float
    status: str | None
    load_tonnes: float | None
    #: INTERPOLATED (same-edge linear between two samples) or SAMPLE (held)
    placement: Placement


class OperationsEdgeMetric(ApiModel):
    edge_id: str
    sample_time: float
    utilization: float | None
    queue_count: int | None
    haulage_tonnes_per_hour: float | None
    travel_time_seconds: float | None


class OperationsFrame(ApiModel):
    result_id: str
    time_axis_kind: TimeAxisKind
    time: float
    vehicles: list[OperationsVehicle]
    edge_metrics: list[OperationsEdgeMetric]


def json_ready(model: ApiModel) -> dict[str, Any]:
    return model.model_dump(mode="json", by_alias=True)
