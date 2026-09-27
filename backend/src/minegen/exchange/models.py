"""MineExchange v1 DTOs — the EXTERNAL contract (semantic version 1.1.0).

Internal artifacts (``layout_v2.json``, ``network.json``,
``capability_graph.json``, …) are never exposed as-is: every document in the
bundle is one of the typed models below, projected from the authoritative
MineGen state. ``manifest.json`` is the meaning authority of a bundle — the
coordinate frame, units, provenance, representation semantics and QA facts
of every file are declared there, never inferred from a file name.
"""

from __future__ import annotations

from typing import Any, Literal

from minegen.core.models import ApiModel

__all__ = [
    "COORDINATE_FRAME",
    "GLTF_FRAME",
    "MINE_EXCHANGE_VERSION",
    "NETWORK_DIRECTION_SEMANTICS",
    "CoordinateSystem",
    "ExchangeCapability",
    "ExchangeCapabilityEdge",
    "ExchangeCapabilityNode",
    "ExchangeEgressAdvisory",
    "ExchangeEntity",
    "ExchangeFile",
    "ExchangeManifest",
    "ExchangeMiningMethod",
    "ExchangeNetwork",
    "ExchangeNetworkEdge",
    "ExchangeNetworkNode",
    "ExchangeOmission",
    "ExchangeProductionStopes",
    "ExchangeRequiredPath",
    "ExchangeStope",
    "ExchangeStopesMetrics",
    "GeometryQa",
    "GlbFrame",
    "MultiBodyComponent",
    "SourceSnapshot",
]

#: the external contract version (semantic); NOT an internal artifact version.
#: 1.1.0 (Phase 21A): mining-method semantics + longhole stope export — an
#: ADDITIVE 1.x extension (new files, semantic types, entity kind, omission
#: outcomes); every 1.0.0 meaning, id and coordinate contract is unchanged
MINE_EXCHANGE_VERSION = "1.1.0"
#: MineGen canonical frame: X East, Y North, Z Up, metres (CLAUDE.md rule 3)
COORDINATE_FRAME = "LOCAL_ENU_Z_UP"
#: glTF scene convention after the explicit root transform (x, z, −y)
GLTF_FRAME = "GLTF_Y_UP"
#: rule 69: a stored edge direction is the centerline orientation, never a
#: one-way traffic statement
NETWORK_DIRECTION_SEMANTICS = (
    "edge direction = centerline orientation (graph storage direction); "
    "it does NOT imply one-way traffic; physical connectivity is undirected"
)

SemanticType = Literal[
    "MANIFEST",
    "README",
    "TERRAIN_GRID",
    "TERRAIN_SURFACE",
    "OREBODY_MODEL",
    "OREBODY",
    "FAULT_MODEL",
    "FAULT_SURFACE",
    "EXCAVATION_ENTITIES",
    "EXCAVATION_CENTERLINES",
    "EXCAVATION_SOLID",
    "EXCAVATION_MULTI_BODY",
    "EXCAVATION_RENDER_SURFACE",
    "MINE_NETWORK",
    "MINE_NETWORK_NODES",
    "MINE_NETWORK_EDGES",
    "CAPABILITY",
    # 1.1.0 (Phase 21A)
    "MINING_METHOD",
    "PRODUCTION_STOPES",
    "STOPE_SOLID",
]
Representation = Literal[
    "DOCUMENT",
    "TABLE",
    "NODE_GRID",
    "ESRI_ASCII_GRID",
    "SURFACE_MESH",
    "DERIVED_SURFACE_OF_SOLID",
    "PLANAR_POLYGONS",
    "POLYLINES",
    "CLOSED_LOGICAL_SWEEP",
    "MULTI_BODY_CONCATENATION",
    "RENDER_SURFACE",
    # 1.1.0: the authoritative stope prism mesh itself (never re-derived)
    "AUTHORITATIVE_CLOSED_MESH",
]
EntityKind = Literal[
    "TERRAIN",
    "OREBODY",
    "FAULT",
    "RAMP",
    "RAMP_SEGMENT",
    "LEVEL_ACCESS",
    "DRIFT",
    "DRIFT_PIECE",
    "CROSSCUT",
    "SHAFT",
    "SHAFT_SEGMENT",
    "SHAFT_STATION_ACCESS",
    # 1.1.0: a planned production volume (stopes.json), never a development
    "STOPE",
]


class CoordinateSystem(ApiModel):
    name: Literal["LOCAL_ENU_Z_UP"] = "LOCAL_ENU_Z_UP"
    axes: list[str] = ["EAST", "NORTH", "UP"]
    axis_order: list[str] = ["X", "Y", "Z"]
    vertical_axis: Literal["Z"] = "Z"
    handedness: Literal["RIGHT_HANDED"] = "RIGHT_HANDED"
    unit: Literal["metre"] = "metre"
    #: no real survey CRS exists for the synthetic world (never a fake EPSG)
    crs: Literal["LOCAL_SYNTHETIC"] = "LOCAL_SYNTHETIC"


class GlbFrame(ApiModel):
    """How a GLB in the bundle relates to the canonical frame: the vertices
    are STORED in ``storedVertexFrame``; ``transformMatrix`` (glTF
    column-major, 16 values) is the root node transform that maps them into
    ``sceneFrame``; ``sourceFrame`` is the frame of the authoritative
    geometry. ``null`` matrix = identity (no root transform)."""

    stored_vertex_frame: str
    scene_frame: str
    source_frame: str = COORDINATE_FRAME
    transform_matrix: list[float] | None


class GeometryQa(ApiModel):
    """Mesh facts measured by the exporter (``null`` where meaningless)."""

    closed: bool | None = None
    watertight: bool | None = None
    manifold: bool | None = None
    unioned: bool | None = None
    overlapping_at_junctions: bool | None = None
    closed_components: bool | None = None
    printability_guaranteed: bool | None = None
    engineering_solid_ready: bool | None = None
    junction_apertures: bool | None = None
    triangle_count: int | None = None
    vertex_count: int | None = None
    signed_volume_m3: float | None = None


class MultiBodyComponent(ApiModel):
    entity_id: str
    first_triangle: int
    triangle_count: int


class ExchangeFile(ApiModel):
    path: str
    sha256: str
    media_type: str
    semantic_type: SemanticType
    representation: Representation
    source_entity_ids: list[str]
    source_artifact: str | None
    source_revision: str | None
    coordinate_frame: str
    derived: bool
    geometry: GeometryQa | None = None
    glb: GlbFrame | None = None
    components: list[MultiBodyComponent] | None = None
    #: DXF handle → entity id (deterministic; the manifest mapping is the
    #: identity authority, the layer is the kind)
    dxf_entities: list[dict[str, str]] | None = None
    notes: list[str] = []


class ExchangeEntity(ApiModel):
    entity_id: str
    kind: EntityKind
    level_id: str | None = None
    source_artifact: str | None
    #: the authoritative id inside the source artifact (never a list index);
    #: ``null`` for a SYNTHETIC aggregate (ramp:main, drift:<level>) that has
    #: no single authoritative id — its members are listed in
    #: ``sourceMemberIds`` instead of a selector; the shaft aggregate is an
    #: authoritative record and carries its ``shaftId``
    source_id: str | None
    #: aggregate entities only: the authoritative member ids (segment ids,
    #: drift piece ids, shaft segment ids) in their persisted order
    source_member_ids: list[str] | None = None
    parent_entity_id: str | None = None
    files: list[str]


class ExchangeOmission(ApiModel):
    group: Literal[
        "EXCAVATIONS",
        "NETWORK",
        "CAPABILITY",
        "RENDER_GLB",
        "SHAFTS",
        "STOPES",
        "TIMELINE",
        "FIELD_LATTICE",
    ]
    reason_code: Literal["ARTIFACT_ABSENT", "NOT_IN_V1", "SOURCE_NOT_SUCCESS"]
    detail: str
    source_artifact: str | None


class SourceSnapshot(ApiModel):
    scenario_revision: str
    arrays_revision: str
    active_ramp_source: Literal["LEGACY", "LAYOUT_V2"]
    #: file revision of every artifact the bundle was projected from
    artifact_revisions: dict[str, str]


class ExchangeManifest(ApiModel):
    mine_exchange_version: str
    scenario_id: str
    scenario_name: str
    coordinate_system: CoordinateSystem
    units: dict[str, str]
    source_snapshot: SourceSnapshot
    entities: list[ExchangeEntity]
    files: list[ExchangeFile]
    omissions: list[ExchangeOmission]
    #: reserved for later contract extensions (grade / rock-quality
    #: descriptors, future production entities once they exist); the enums
    #: are never pre-populated with meanings that have no authority yet
    extensions: dict[str, Any] = {}
    notes: list[str] = []


# --------------------------------------------------------------------------- #
# topology (geometry ≠ topology ≠ capability, rule 185)
# --------------------------------------------------------------------------- #


class ExchangeNetworkNode(ApiModel):
    id: str
    type: str
    position: list[float]
    level_id: str | None
    surface: bool


class ExchangeNetworkEdge(ApiModel):
    id: str
    type: str
    source_node_id: str
    target_node_id: str
    #: the exported centerline entity that owns this edge's geometry —
    #: resolved through the canonical ``resolve_owning_centerline`` and
    #: verified to be an exported entity; ``null`` ONLY for an edge type with
    #: no owning-centerline contract (``geometryContract = NONE``: RAISE)
    geometry_entity_id: str | None
    geometry_contract: Literal["OWNING_CENTERLINE", "NONE"] = "OWNING_CENTERLINE"
    length: float
    orientation: str
    cross_section: dict[str, Any] | None


class ExchangeNetwork(ApiModel):
    mine_exchange_version: str
    semantic_type: Literal["MINE_NETWORK"] = "MINE_NETWORK"
    coordinate_frame: str = COORDINATE_FRAME
    direction_semantics: str = NETWORK_DIRECTION_SEMANTICS
    source_artifact: str
    source_revision: str
    nodes: list[ExchangeNetworkNode]
    edges: list[ExchangeNetworkEdge]


# --------------------------------------------------------------------------- #
# semantics (capability — a planning layer, never a legal one)
# --------------------------------------------------------------------------- #


class ExchangeCapabilityEdge(ApiModel):
    edge_id: str
    capabilities: list[str]
    restrictions: list[str]
    source: str


class ExchangeCapabilityNode(ApiModel):
    node_id: str
    supports: list[str]
    surface: bool


class ExchangeRequiredPath(ApiModel):
    id: str
    capability: str
    source_node_id: str
    target_node_id: str
    rule: str
    physical_reachable: bool
    capability_reachable: bool
    satisfied: bool


class ExchangeEgressAdvisory(ApiModel):
    capability: str
    criterion: str
    required_routes: int
    advisory_only: Literal[True] = True
    surface_node_ids: list[str]
    per_node: list[dict[str, Any]]
    note: str = "design advisory only — not a statutory or regulatory compliance determination"


class ExchangeCapability(ApiModel):
    mine_exchange_version: str
    semantic_type: Literal["CAPABILITY"] = "CAPABILITY"
    source_artifact: str
    source_revision: str
    capability_semantics: str = (
        "typed may / may-not tags per network edge (planning semantics); "
        "capability ≠ capacity, and never a legal certification"
    )
    capabilities: list[str]
    edges: list[ExchangeCapabilityEdge]
    nodes: list[ExchangeCapabilityNode]
    surface_node_ids: list[str]
    required_paths: list[ExchangeRequiredPath]
    egress_advisory: ExchangeEgressAdvisory | None
    validation: dict[str, Any] | None


# --------------------------------------------------------------------------- #
# mining method + production (1.1.0, Phase 21A)
# --------------------------------------------------------------------------- #


class ExchangeMiningParameters(ApiModel):
    sublevel_interval: float
    stope_length: float
    minimum_pillar: float


class ExchangeProductionDevelopmentStatus(ApiModel):
    """The production-development intent recorded in ``levels.json`` —
    IMPLEMENTED / UNSUPPORTED_METHOD — or NOT_GENERATED when no levels
    artifact (or none declaring it) exists. Its geometry is the exported
    CROSSCUT entities; nothing is duplicated here."""

    status: Literal["IMPLEMENTED", "UNSUPPORTED_METHOD", "NOT_GENERATED"]
    reason: str | None = None
    source_artifact: str | None
    source_revision: str | None
    #: exported crosscut entity ids (the longhole production development)
    entity_ids: list[str]


class ExchangeProductionStatus(ApiModel):
    status: Literal["SUCCESS", "FAILED", "NOT_GENERATED"]
    failure_reason: str | None = None
    source_artifact: str | None
    source_revision: str | None
    stope_count: int
    #: exported STOPE entity ids in bundle order
    entity_ids: list[str]


class ExchangeMiningMethod(ApiModel):
    """``semantics/mining_method.json`` — what was REQUESTED, whether MineGen
    implements it, the configured parameters and references to the
    production development / production entities that exist. Projected from
    ``scenario.json`` + ``levels.json`` + ``stopes.json``; a disagreement
    between those authorities is a typed export refusal, never normalized."""

    mine_exchange_version: str
    semantic_type: Literal["MINING_METHOD"] = "MINING_METHOD"
    requested_method: str
    display_name: str
    implementation_status: Literal["IMPLEMENTED", "UNSUPPORTED_METHOD"]
    parameters: ExchangeMiningParameters
    production_development: ExchangeProductionDevelopmentStatus
    production: ExchangeProductionStatus
    scenario_revision: str
    notes: list[str] = []


class ExchangeStopeBounds(ApiModel):
    u_min: float
    u_max: float
    v_min: float
    v_max: float
    w_min: float
    w_max: float


class ExchangeStope(ApiModel):
    """One planned longhole stope: the authoritative ``stopes.json`` record
    (identity, level pair, access anchors, station, planning quantities) and
    the exported solid files. Volumes / tonnes / grade proxy are planning
    quantities, never reserves or resources."""

    entity_id: str
    stope_id: str
    method: str
    station_index: int
    station_u: float
    upper_level_id: str
    lower_level_id: str
    upper_access_node_id: str
    lower_access_node_id: str
    local_bounds: ExchangeStopeBounds
    strike_length: float
    down_dip_span: float
    vertical_height: float
    thickness: float
    geometric_volume_m3: float
    tonnes: float
    mean_grade_proxy: float | None
    planned_state: str
    files: list[str]


class ExchangeStopesMetrics(ApiModel):
    """External projection of the internal stope metrics (PR #46 review
    B2): an explicit typed 1.1 contract, never the internal ``StopesMetrics``
    document passed through — an internal refactor cannot change this file
    without a MineExchange version change. Planning quantities only, never
    reserves or resources."""

    stope_count: int
    level_interval_count: int
    stations_per_interval: int
    total_geometric_volume_m3: float
    total_tonnes: float
    geometric_extraction_fraction_of_orebody: float
    weighted_mean_grade_proxy: float | None


class ExchangeProductionStopes(ApiModel):
    """``production/stopes.json`` — the semantic document of the exported
    stopes (authority: ``stopes.json``); geometry lives in the per-stope
    solid files, one closed prism each, never unioned."""

    mine_exchange_version: str
    semantic_type: Literal["PRODUCTION_STOPES"] = "PRODUCTION_STOPES"
    coordinate_frame: str = COORDINATE_FRAME
    source_artifact: str
    source_revision: str
    method: str
    stopes: list[ExchangeStope]
    metrics: ExchangeStopesMetrics | None
    notes: list[str] = []
