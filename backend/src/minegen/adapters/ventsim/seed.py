"""Ventsim seed adapter core: MineExchange bundle → Ventsim seed package.

Representation (``docs/external-adapters.md`` §11.4 Q1, decided here): ONE
3-D DXF ``POLYLINE`` per MineNetwork edge whose vertices are the edge's
OWNING authoritative centerline (MineExchange ``excavations/centerlines.csv``
— every edge owns exactly one exported centerline entity and its two
topology nodes are that polyline's end points), optionally Douglas–Peucker
simplified with an explicit tolerance (end points always kept). Two DXF
polylines that meet at a network node therefore share the vertex
coordinate, which is what Ventsim's Convert Centrelines joins. The layer is
the network EDGE TYPE. DXF carries geometry only, so the authoritative
length and the cross-section dimensions travel in ``airways.csv`` keyed by
the deterministic DXF handle (the identity map), for assignment after
conversion.

Never done here: no polyline is moved, re-sampled, re-designed or invented
(a RAISE edge, the one type without an owning centerline, is a typed
omission); no ventilation property is guessed — resistance, friction, fans,
regulators, heat and contaminants are ``NOT_PROVIDED``; no coordinate is
re-based except by the explicit ``originOffset``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.adapters.bundle_reader import MineExchangeBundle, require_version
from minegen.adapters.contracts import (
    AdapterAssumption,
    AdapterCoordinateMapping,
    AdapterGeneratedFile,
    AdapterOmission,
    AdapterReport,
    AdapterSourceState,
)
from minegen.adapters.errors import (
    AdapterConversionFailedError,
    MineExchangeBundleInvalidError,
    RequiredSourceAbsentError,
)
from minegen.adapters.package import write_package
from minegen.adapters.polyline import polyline_length, simplify_polyline
from minegen.adapters.ventsim.config import (
    DEFAULT_SIMPLIFICATION_TOLERANCE_M,
    VentsimSeedConfig,
)
from minegen.core.models import ApiModel
from minegen.exchange.bundle import sha256_hex
from minegen.exchange.formats.csv_table import read_csv, write_csv
from minegen.exchange.formats.dxf import DxfDocument, DxfPolyline, sanitize_layer, write_dxf
from minegen.exchange.formats.json_document import dumps
from minegen.exchange.models import (
    COORDINATE_FRAME,
    ExchangeNetwork,
    ExchangeNetworkEdge,
    ExchangeNetworkNode,
)

FloatArray = npt.NDArray[np.float64]

ADAPTER_NAME = "VENTSIM_SEED"
ADAPTER_VERSION = "0.1.0"
TARGET_APPLICATION = "VENTSIM"
SUPPORTED_MINE_EXCHANGE_VERSIONS = ">=1.2.0,<2.0.0"
_MIN_VERSION = (1, 2, 0)
_BELOW_MAJOR = 2
PACKAGE_ROOT = "ventsim_seed"

NETWORK_PATH = "topology/network.json"
CENTERLINES_PATH = "excavations/centerlines.csv"
CENTERLINES_HEADER = ("entityId", "kind", "levelId", "sequence", "x", "y", "z")

DXF_PATH = "airways.dxf"
AIRWAYS_PATH = "airways.csv"
NODES_PATH = "nodes.csv"
IDENTITY_MAP_PATH = "identity_map.json"
REPORT_PATH = "adapter_report.json"
README_PATH = "README.txt"

#: an edge's centerline end points must coincide with its topology nodes;
#: the network builder welds at 1e-6 m (rule 156 / STATION_MERGE_TOLERANCE),
#: 1e-4 m absorbs the JSON / CSV float round trips and stays three orders
#: below any Ventsim relevance — a larger gap is a conversion refusal
ENDPOINT_WELD_TOLERANCE_M = 1e-4
#: the bundle's authoritative edge length must be the length of the owning
#: polyline it declares (both are derived from the same points upstream)
LENGTH_CONSISTENCY_REL_TOLERANCE = 1e-6

REQUIRED_GROUPS: tuple[str, ...] = ("EXCAVATIONS", "NETWORK")
#: bundle groups the 0.1.0 seed has no mapping for (§6: UNSUPPORTED_BY_ADAPTER)
UNSUPPORTED_GROUPS: tuple[tuple[str, str], ...] = (
    ("TERRAIN", "reference graphics are not emitted by the 0.1.0 seed"),
    ("OREBODY", "reference graphics are not emitted by the 0.1.0 seed"),
    ("FAULTS", "reference graphics are not emitted by the 0.1.0 seed"),
    ("CAPABILITY", "no ventilation semantics; not mapped by the 0.1.0 seed"),
    ("MINING_METHOD", "metadata only; not mapped by the 0.1.0 seed"),
    ("PRODUCTION", "stope / cut / room solids are not airways; not mapped by the 0.1.0 seed"),
)
#: Ventsim inputs no MineGen authority owns (§11.2 MISSING, gap class C)
NOT_PROVIDED_PROPERTIES: tuple[tuple[str, str], ...] = (
    ("AIRWAY_RESISTANCE", "airway resistance / friction factor"),
    ("AIRWAY_ROUGHNESS", "wall roughness / shock losses"),
    ("FANS", "fan placement and fan curves"),
    ("REGULATORS_AND_DOORS", "regulators, doors, stoppings"),
    ("HEAT_SOURCES", "heat loads (rock, diesel, electrical)"),
    ("CONTAMINANT_SOURCES", "gas / dust / diesel emission sources"),
    ("AIR_DENSITY_AND_SURFACE_CONDITIONS", "air density, surface temperature / pressure"),
)
_TARGET_SEMANTIC_BY_PATH: dict[str, str] = {
    DXF_PATH: "VENTSIM_CENTERLINES_FOR_CONVERT",
    AIRWAYS_PATH: "AIRWAY_ATTRIBUTE_TABLE",
    NODES_PATH: "NETWORK_NODE_TABLE",
    IDENTITY_MAP_PATH: "IDENTITY_MAP",
    README_PATH: "README",
}
_MEDIA_BY_SUFFIX: dict[str, str] = {
    "dxf": "application/dxf",
    "csv": "text/csv",
    "json": "application/json",
    "txt": "text/plain",
}


class VentsimAirwayMetrics(ApiModel):
    airway_count: int
    airway_count_by_type: dict[str, int]
    node_count: int
    surface_node_count: int
    vertex_count_authoritative: int
    vertex_count_delivered: int
    total_authoritative_length_m: float
    total_delivered_length_m: float
    #: max over airways of |delivered − authoritative| (simplification only)
    max_length_deviation_m: float
    #: measured maximum distance of any removed point from its delivered polyline
    max_simplification_deviation_m: float
    max_endpoint_weld_m: float
    airways_without_cross_section: int


class VentsimSeedReport(AdapterReport):
    config: VentsimSeedConfig
    effective_simplification_tolerance_m: float
    airway_metrics: VentsimAirwayMetrics
    identity_map_file: str


@dataclass(frozen=True)
class VentsimSeedPackage:
    zip_bytes: bytes
    report: VentsimSeedReport


@dataclass(frozen=True)
class _Centerline:
    kind: str
    level_id: str | None
    points: FloatArray


@dataclass(frozen=True)
class _Airway:
    edge: ExchangeNetworkEdge
    entity_id: str
    entity_kind: str
    level_id: str | None
    layer: str
    delivered: FloatArray  # target coordinates (offset applied)
    authoritative_vertex_count: int
    authoritative_length: float
    delivered_length: float
    simplification_deviation: float
    endpoint_weld: float
    width: float | None
    height: float | None
    shape: str | None


# --------------------------------------------------------------------------- #
# bundle consumption
# --------------------------------------------------------------------------- #


def _require_group(bundle: MineExchangeBundle, group: str) -> None:
    om = bundle.omission(group)
    if om is not None:
        raise RequiredSourceAbsentError(
            f"bundle group {group} is {om.reason_code} ({om.detail}); the Ventsim seed "
            "needs the excavation centerlines and the MineNetwork topology"
        )


def _source_states(bundle: MineExchangeBundle) -> list[AdapterSourceState]:
    states: list[AdapterSourceState] = []
    for group in REQUIRED_GROUPS:
        states.append(
            AdapterSourceState(
                group=group,
                state="AVAILABLE",
                bundle_reason_code=None,
                detail="consumed: the airway polylines and the topology",
            )
        )
    shafts = bundle.omission("SHAFTS")
    if shafts is not None:
        states.append(
            AdapterSourceState(
                group="SHAFTS",
                state="ABSENT" if shafts.reason_code == "ARTIFACT_ABSENT" else "SOURCE_NOT_SUCCESS",
                bundle_reason_code=shafts.reason_code,
                detail=shafts.detail,
            )
        )
    for group, detail in UNSUPPORTED_GROUPS:
        states.append(
            AdapterSourceState(
                group=group, state="UNSUPPORTED_BY_ADAPTER", bundle_reason_code=None, detail=detail
            )
        )
    timeline = bundle.omission("TIMELINE")
    states.append(
        AdapterSourceState(
            group="TIMELINE",
            state="ABSENT",
            bundle_reason_code=timeline.reason_code if timeline is not None else None,
            detail=(
                timeline.detail
                if timeline is not None
                else "the bundle carries no timeline; a staged model needs MineExchange 1.3"
            ),
        )
    )
    return states


def _centerlines(bundle: MineExchangeBundle) -> dict[str, _Centerline]:
    header, rows = read_csv(bundle.text(CENTERLINES_PATH))
    if tuple(header) != CENTERLINES_HEADER:
        raise MineExchangeBundleInvalidError(
            f"{CENTERLINES_PATH} header {header} is not {list(CENTERLINES_HEADER)}"
        )
    kinds = {e.entity_id: e.kind for e in bundle.manifest.entities}
    grouped: dict[str, list[list[str]]] = {}
    for row in rows:
        if len(row) != len(CENTERLINES_HEADER):
            raise MineExchangeBundleInvalidError(f"{CENTERLINES_PATH}: malformed row {row}")
        grouped.setdefault(row[0], []).append(row)
    out: dict[str, _Centerline] = {}
    for entity_id, entity_rows in grouped.items():
        if entity_id not in kinds:
            raise MineExchangeBundleInvalidError(
                f"{CENTERLINES_PATH} names entity {entity_id!r} that the manifest does not list"
            )
        kind = entity_rows[0][1]
        if kind != kinds[entity_id]:
            raise MineExchangeBundleInvalidError(
                f"{CENTERLINES_PATH}: entity {entity_id!r} kind {kind!r} disagrees with the "
                f"manifest ({kinds[entity_id]!r})"
            )
        try:
            seq = [int(r[3]) for r in entity_rows]
            pts = np.asarray([[float(r[4]), float(r[5]), float(r[6])] for r in entity_rows])
        except ValueError as exc:
            raise MineExchangeBundleInvalidError(
                f"{CENTERLINES_PATH}: entity {entity_id!r} has a non-numeric row: {exc}"
            ) from exc
        if seq != list(range(len(seq))) or len(seq) < 2:
            raise MineExchangeBundleInvalidError(
                f"{CENTERLINES_PATH}: entity {entity_id!r} sequence is not contiguous from 0 "
                "with at least two points"
            )
        if not np.all(np.isfinite(pts)):
            raise MineExchangeBundleInvalidError(
                f"{CENTERLINES_PATH}: entity {entity_id!r} has non-finite coordinates"
            )
        level = entity_rows[0][2] or None
        out[entity_id] = _Centerline(kind=kind, level_id=level, points=pts)
    return out


def _cross_section(edge: ExchangeNetworkEdge) -> tuple[float | None, float | None, str | None]:
    cs = edge.cross_section
    if not isinstance(cs, dict):
        return None, None, None
    width = cs.get("width")
    height = cs.get("height")
    shape = cs.get("shape")
    w = float(width) if isinstance(width, int | float) and np.isfinite(width) else None
    h = float(height) if isinstance(height, int | float) and np.isfinite(height) else None
    return w, h, (str(shape) if shape is not None else None)


def _airway(
    edge: ExchangeNetworkEdge,
    centerlines: dict[str, _Centerline],
    nodes: dict[str, ExchangeNetworkNode],
    tolerance: float,
    offset: FloatArray,
) -> _Airway:
    assert edge.geometry_entity_id is not None
    cl = centerlines.get(edge.geometry_entity_id)
    if cl is None:
        raise MineExchangeBundleInvalidError(
            f"network edge {edge.id!r} references geometry entity "
            f"{edge.geometry_entity_id!r} that has no centerline in {CENTERLINES_PATH}"
        )
    try:
        a = np.asarray(nodes[edge.source_node_id].position, dtype=np.float64)
        b = np.asarray(nodes[edge.target_node_id].position, dtype=np.float64)
    except KeyError as exc:
        raise MineExchangeBundleInvalidError(
            f"network edge {edge.id!r} references unknown node {exc.args[0]!r}"
        ) from exc
    pts = cl.points
    weld = max(float(np.linalg.norm(pts[0] - a)), float(np.linalg.norm(pts[-1] - b)))
    if weld > ENDPOINT_WELD_TOLERANCE_M:
        # the storage direction is the centerline orientation (rule 69); a
        # reversed or detached polyline is never silently flipped or snapped
        raise AdapterConversionFailedError(
            f"network edge {edge.id!r}: centerline end points are {weld:.6f} m from its "
            f"topology nodes {edge.source_node_id!r} → {edge.target_node_id!r} "
            f"(tolerance {ENDPOINT_WELD_TOLERANCE_M} m)"
        )
    auth_len = polyline_length(pts)
    if abs(auth_len - edge.length) > LENGTH_CONSISTENCY_REL_TOLERANCE * max(1.0, edge.length):
        raise MineExchangeBundleInvalidError(
            f"network edge {edge.id!r} declares length {edge.length} m but its owning "
            f"centerline measures {auth_len} m"
        )
    kept, deviation = simplify_polyline(pts, tolerance)
    delivered = kept + offset[None, :]
    width, height, shape = _cross_section(edge)
    return _Airway(
        edge=edge,
        entity_id=edge.geometry_entity_id,
        entity_kind=cl.kind,
        level_id=cl.level_id,
        layer=sanitize_layer(edge.type),
        delivered=delivered,
        authoritative_vertex_count=int(pts.shape[0]),
        authoritative_length=auth_len,
        delivered_length=polyline_length(kept),
        simplification_deviation=deviation,
        endpoint_weld=weld,
        width=width,
        height=height,
        shape=shape,
    )


# --------------------------------------------------------------------------- #
# package files
# --------------------------------------------------------------------------- #


def _airways_csv(airways: list[_Airway], handles: dict[str, str]) -> bytes:
    header = (
        "dxfHandle",
        "airwayId",
        "edgeType",
        "layer",
        "sourceNodeId",
        "targetNodeId",
        "geometryEntityId",
        "entityKind",
        "levelId",
        "orientation",
        "authoritativeLengthM",
        "deliveredLengthM",
        "lengthDeviationM",
        "vertexCountAuthoritative",
        "vertexCountDelivered",
        "widthM",
        "heightM",
        "profileShape",
    )
    rows = [
        (
            handles[a.edge.id],
            a.edge.id,
            a.edge.type,
            a.layer,
            a.edge.source_node_id,
            a.edge.target_node_id,
            a.entity_id,
            a.entity_kind,
            a.level_id,
            a.edge.orientation,
            a.authoritative_length,
            a.delivered_length,
            abs(a.delivered_length - a.authoritative_length),
            a.authoritative_vertex_count,
            int(a.delivered.shape[0]),
            a.width,
            a.height,
            a.shape,
        )
        for a in airways
    ]
    return write_csv(header, rows).encode("utf-8")


def _nodes_csv(nodes: list[ExchangeNetworkNode], offset: FloatArray) -> bytes:
    rows = []
    for n in nodes:
        p = np.asarray(n.position, dtype=np.float64) + offset
        rows.append((n.id, n.type, float(p[0]), float(p[1]), float(p[2]), n.level_id, n.surface))
    return write_csv(("nodeId", "type", "x", "y", "z", "levelId", "surface"), rows).encode("utf-8")


def _identity_map(
    airways: list[_Airway],
    handles: dict[str, str],
    nodes: list[ExchangeNetworkNode],
    offset: FloatArray,
) -> bytes:
    doc = {
        "adapterName": ADAPTER_NAME,
        "adapterVersion": ADAPTER_VERSION,
        "dxfFile": DXF_PATH,
        "semantics": (
            "dxfHandle is the deterministic handle of the 3-D POLYLINE in airways.dxf; "
            "airwayId == the MineExchange network edge id; nodes carry their target "
            "(offset-applied) coordinates — Ventsim assigns its own ids at conversion"
        ),
        "airways": [
            {
                "dxfHandle": handles[a.edge.id],
                "airwayId": a.edge.id,
                "bundleEdgeId": a.edge.id,
                "bundleEntityId": a.entity_id,
                "layer": a.layer,
            }
            for a in airways
        ],
        "nodes": [
            {
                "nodeId": n.id,
                "type": n.type,
                "position": [float(v) for v in (np.asarray(n.position, dtype=np.float64) + offset)],
                "surface": n.surface,
            }
            for n in nodes
        ],
    }
    return dumps(doc)


def _readme(report: VentsimSeedReport) -> bytes:
    m = report.airway_metrics
    t = report.coordinate_mapping.translation
    lines = [
        f"Ventsim SEED package — {ADAPTER_NAME} {ADAPTER_VERSION} "
        f"(MineExchange {report.source_mine_exchange_version}, scenario "
        f"{report.source_scenario_id} '{report.source_scenario_name}')",
        "",
        "This is a GEOMETRY / NETWORK SEED for a Ventsim airway model, not a ventilation model.",
        "It carries MineGen's development topology; every ventilation property (resistance,",
        "friction, fans, regulators, heat, contaminants, air density) is NOT PROVIDED and must",
        "be entered in Ventsim. adapter_report.json is the meaning authority of this package.",
        "",
        "Files",
        f"  {DXF_PATH}          one 3-D POLYLINE per MineNetwork edge; layer = edge type",
        f"  {AIRWAYS_PATH}          airway attribute table keyed by DXF handle",
        "                      (authoritative / delivered length, width, height, profile shape)",
        f"  {NODES_PATH}            junction table (id, type, x, y, z, levelId, surface)",
        f"  {IDENTITY_MAP_PATH}   DXF handle <-> MineExchange edge / entity ids",
        f"  {REPORT_PATH} adapter report (source states, assumptions, omissions, metrics)",
        "",
        "Coordinates",
        f"  Frame {report.coordinate_mapping.source_frame} (X east, Y north, Z up), metres,",
        "  LOCAL SYNTHETIC origin (no real-world georeference).",
        f"  Origin offset applied: ({t[0]}, {t[1]}, {t[2]}) m.",
        "  Ventsim imports a DXF in the Ventsim file's CURRENT units and coordinates — set the",
        "  Ventsim file to metres before importing; do not let Ventsim rescale.",
        "",
        "Import steps (Ventsim DESIGN, documented DXF path)",
        f"  1. File > Import > DXF: {DXF_PATH}; choose to convert centrelines to airways",
        "     (or import as reference and use Add > Convert on the polylines).",
        "  2. Ventsim builds a chain of airways between consecutive polyline vertices; the",
        "     polylines share their end vertices at every MineNetwork node, so the chains join.",
        f"  3. Apply the airway dimensions from {AIRWAYS_PATH} (widthM / heightM / profileShape)",
        "     to the converted airways of each layer — DXF cannot carry them.",
        "  4. Enter fans, resistances / friction factors, regulators and sources yourself.",
        "",
        "Delivered geometry",
        f"  {m.airway_count} airways, {m.node_count} nodes ({m.surface_node_count} surface),",
        f"  simplification tolerance {report.effective_simplification_tolerance_m} m "
        f"({m.vertex_count_authoritative} -> {m.vertex_count_delivered} vertices,",
        f"  max deviation {m.max_simplification_deviation_m:.4f} m,",
        f"  max airway length deviation {m.max_length_deviation_m:.4f} m).",
        "  Use authoritativeLengthM from the attribute table where the true length matters.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def _generated(files: dict[str, bytes], sources: list[str]) -> list[AdapterGeneratedFile]:
    return [
        AdapterGeneratedFile(
            path=path,
            media_type=_MEDIA_BY_SUFFIX[path.rsplit(".", 1)[-1]],
            target_semantic=_TARGET_SEMANTIC_BY_PATH[path],
            source_entity_ids=[],
            source_files=sources,
            sha256=sha256_hex(data),
        )
        for path, data in sorted(files.items())
    ]


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #


def build_ventsim_seed(
    bundle: MineExchangeBundle, config: VentsimSeedConfig | None = None
) -> VentsimSeedPackage:
    cfg = config if config is not None else VentsimSeedConfig()
    manifest = bundle.manifest
    require_version(
        manifest.mine_exchange_version,
        minimum=_MIN_VERSION,
        below_major=_BELOW_MAJOR,
        supported=SUPPORTED_MINE_EXCHANGE_VERSIONS,
    )
    for group in REQUIRED_GROUPS:
        _require_group(bundle, group)
    if not bundle.has(NETWORK_PATH) or not bundle.has(CENTERLINES_PATH):
        raise MineExchangeBundleInvalidError(
            f"the bundle records no EXCAVATIONS / NETWORK omission but {NETWORK_PATH} or "
            f"{CENTERLINES_PATH} is missing"
        )
    network = bundle.document(NETWORK_PATH, ExchangeNetwork)
    centerlines = _centerlines(bundle)
    nodes_by_id: dict[str, ExchangeNetworkNode] = {}
    for n in network.nodes:
        if n.id in nodes_by_id:
            raise MineExchangeBundleInvalidError(f"{NETWORK_PATH}: duplicate node id {n.id!r}")
        if len(n.position) != 3 or not np.all(np.isfinite(n.position)):
            raise MineExchangeBundleInvalidError(f"{NETWORK_PATH}: node {n.id!r} position")
        nodes_by_id[n.id] = n

    tolerance = (
        DEFAULT_SIMPLIFICATION_TOLERANCE_M
        if cfg.simplification_tolerance_m is None
        else float(cfg.simplification_tolerance_m)
    )
    offset = np.asarray(cfg.origin_offset, dtype=np.float64)

    airways: list[_Airway] = []
    omissions: list[AdapterOmission] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for edge in network.edges:
        if edge.id in seen:
            raise MineExchangeBundleInvalidError(f"{NETWORK_PATH}: duplicate edge id {edge.id!r}")
        seen.add(edge.id)
        if edge.geometry_contract == "NONE" or edge.geometry_entity_id is None:
            omissions.append(
                AdapterOmission(
                    subject=f"edge:{edge.id}",
                    reason_code="NO_GEOMETRY_CONTRACT",
                    detail=(
                        f"edge type {edge.type} carries no owning centerline in the bundle; "
                        "no airway geometry is invented for it"
                    ),
                )
            )
            continue
        airways.append(_airway(edge, centerlines, nodes_by_id, tolerance, offset))
    if not airways:
        raise RequiredSourceAbsentError(
            "the network carries no edge with an owning centerline; nothing to seed"
        )
    no_cs = [a.edge.id for a in airways if a.width is None or a.height is None]
    if no_cs:
        warnings.append(
            f"{len(no_cs)} airway(s) carry no cross-section in the bundle "
            f"(first: {no_cs[0]!r}); their widthM / heightM are blank — NOT_PROVIDED"
        )

    # -- DXF + identity ------------------------------------------------------ #
    text, mapping = write_dxf(
        DxfDocument(polylines=[DxfPolyline(a.edge.id, a.layer, a.delivered) for a in airways])
    )
    handles = {m["entityId"]: m["handle"] for m in mapping}
    if len(handles) != len(airways):
        raise AdapterConversionFailedError("DXF handle mapping is not one per airway")

    # -- report -------------------------------------------------------------- #
    by_type: dict[str, int] = {}
    for a in airways:
        by_type[a.edge.type] = by_type.get(a.edge.type, 0) + 1
    metrics = VentsimAirwayMetrics(
        airway_count=len(airways),
        airway_count_by_type=dict(sorted(by_type.items())),
        node_count=len(network.nodes),
        surface_node_count=sum(1 for n in network.nodes if n.surface),
        vertex_count_authoritative=sum(a.authoritative_vertex_count for a in airways),
        vertex_count_delivered=sum(int(a.delivered.shape[0]) for a in airways),
        total_authoritative_length_m=float(sum(a.authoritative_length for a in airways)),
        total_delivered_length_m=float(sum(a.delivered_length for a in airways)),
        max_length_deviation_m=float(
            max(abs(a.delivered_length - a.authoritative_length) for a in airways)
        ),
        max_simplification_deviation_m=float(max(a.simplification_deviation for a in airways)),
        max_endpoint_weld_m=float(max(a.endpoint_weld for a in airways)),
        airways_without_cross_section=len(no_cs),
    )
    assumptions: list[AdapterAssumption] = [
        AdapterAssumption(
            kind="SIMPLIFICATION_TOLERANCE",
            state="ADAPTER_DEFAULT_EXPLICIT",
            value=tolerance,
            unit="m",
            scope="ALL_AIRWAYS",
            source=(
                f"{ADAPTER_NAME} {ADAPTER_VERSION} documented default "
                f"{DEFAULT_SIMPLIFICATION_TOLERANCE_M} m (docs/external-adapters.md §11.4 Q1); "
                "3-D Douglas-Peucker, end points kept"
            ),
            user_override=cfg.simplification_tolerance_m is not None,
            note=(
                "a representation tolerance, not an engineering change: every delivered "
                "vertex is an authoritative point; 0 delivers the polyline verbatim"
            ),
        ),
        AdapterAssumption(
            kind="DIMENSION_DELIVERY_POLICY",
            state="ADAPTER_DEFAULT_EXPLICIT",
            value=cfg.dimension_delivery_policy,
            unit=None,
            scope="ALL_AIRWAYS",
            source=f"{ADAPTER_NAME} {ADAPTER_VERSION} (docs/external-adapters.md §11.2)",
            user_override=False,
            note=(
                "DXF carries geometry only; width / height / profile shape come from the "
                "bundle and are assigned after Convert Centrelines from airways.csv"
            ),
        ),
        *[
            AdapterAssumption(
                kind=kind,
                state="NOT_PROVIDED",
                value=None,
                unit=None,
                scope="ALL_AIRWAYS",
                source="no MineGen authority (docs/external-adapters.md §11.2, gap class C)",
                user_override=None,
                note=f"{what}: entered by the user in Ventsim",
            )
            for kind, what in NOT_PROVIDED_PROPERTIES
        ],
    ]
    mapping_note = (
        "same axes and unit as the source; the translation is the explicit originOffset. "
        "Ventsim imports the DXF in the Ventsim file's current units — the file must be "
        "metric (vendor manual)"
    )
    report_base: dict[str, Any] = dict(
        adapter_name=ADAPTER_NAME,
        adapter_version=ADAPTER_VERSION,
        supported_mine_exchange_versions=SUPPORTED_MINE_EXCHANGE_VERSIONS,
        target_application=TARGET_APPLICATION,
        source_mine_exchange_version=manifest.mine_exchange_version,
        source_scenario_id=manifest.scenario_id,
        source_scenario_name=manifest.scenario_name,
        source_snapshot=manifest.source_snapshot.model_dump(mode="json", by_alias=True),
        coordinate_mapping=AdapterCoordinateMapping(
            source_frame=COORDINATE_FRAME,
            target_frame=COORDINATE_FRAME,
            unit="metre",
            unit_factor=1.0,
            translation=[float(v) for v in offset],
            note=mapping_note,
        ),
        source_states=_source_states(bundle),
        assumptions=assumptions,
        omissions=omissions,
        warnings=warnings,
        config=cfg,
        effective_simplification_tolerance_m=tolerance,
        airway_metrics=metrics,
        identity_map_file=IDENTITY_MAP_PATH,
    )
    files: dict[str, bytes] = {
        DXF_PATH: text.encode("ascii"),
        AIRWAYS_PATH: _airways_csv(airways, handles),
        NODES_PATH: _nodes_csv(network.nodes, offset),
        IDENTITY_MAP_PATH: _identity_map(airways, handles, network.nodes, offset),
    }
    sources = ["manifest.json", NETWORK_PATH, CENTERLINES_PATH]
    # the README quotes the metrics, so it is built from a report WITHOUT it
    # and then hashed into the final report's generatedFiles like every file
    draft = VentsimSeedReport(generated_files=_generated(files, sources), **report_base)
    files[README_PATH] = _readme(draft)
    report = VentsimSeedReport(generated_files=_generated(files, sources), **report_base)
    files[REPORT_PATH] = dumps(report.model_dump(mode="json", by_alias=True))
    return VentsimSeedPackage(zip_bytes=write_package(PACKAGE_ROOT, files), report=report)


def build_ventsim_seed_from_bundle_bytes(
    data: bytes, config: VentsimSeedConfig | None = None
) -> VentsimSeedPackage:
    """Adapter entry over a MineExchange ZIP (the API composes this with the
    exporter; an offline bundle is adapted the same way)."""
    from minegen.adapters.bundle_reader import read_mine_exchange_bundle

    return build_ventsim_seed(read_mine_exchange_bundle(data), config)
