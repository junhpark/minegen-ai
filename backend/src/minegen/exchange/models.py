"""MineExchange v1 DTOs — the EXTERNAL contract (semantic version 1.0.0).

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
    "ExchangeNetwork",
    "ExchangeNetworkEdge",
    "ExchangeNetworkNode",
    "ExchangeOmission",
    "ExchangeRequiredPath",
    "GeometryQa",
    "GlbFrame",
    "MultiBodyComponent",
    "SourceSnapshot",
]

#: the external contract version (semantic); NOT an internal artifact version
MINE_EXCHANGE_VERSION = "1.0.0"
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
    "SHAFT_STATION_ACCESS",
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
    #: the authoritative id inside the source artifact (never a list index)
    source_id: str | None
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
    #: reserved for later contract extensions (stopes / mining method are
    #: Phase 21A.2, grade / rock-quality descriptors a later 1.x); the v1
    #: enums are not pre-populated with them
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
    #: the exported centerline entity that owns this edge's geometry
    geometry_entity_id: str | None
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
