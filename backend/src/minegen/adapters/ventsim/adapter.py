"""Ventsim seed adapter core: MineExchange bundle → Ventsim seed package.

    ventsim_package/
      adapter_manifest.json
      README.txt
      geometry/mine_centerlines.dxf   the bundle's excavations/centerlines.dxf, VERBATIM
      network/nodes.csv               every MineNetwork node
      network/airways.csv             one row per network edge with geometry
      identity/entity_map.csv         DXF handle ↔ entity ↔ edge

Representation (directive §24): the bundle DXF is the geometry authority and
is copied byte for byte — one 3-D POLYLINE per exported centerline entity,
layer = entity kind, full fidelity, no simplification. Every network edge
owns exactly one centerline entity whose end points ARE its topology nodes,
so polylines meeting at a node share the vertex Ventsim's Convert
Centrelines joins. DXF handles come from the MANIFEST (``files[].dxfEntities``),
never from parsing the file. The adapter verifies (never repairs) that each
edge's polyline ends on its nodes and that the declared edge length is the
polyline length — a disagreement is a typed refusal.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from minegen.adapters.bundle_reader import MineExchangeBundle
from minegen.adapters.common import (
    CENTERLINES_CSV_PATH,
    CENTERLINES_DXF_PATH,
    MINE_EXCHANGE_1_2,
    NETWORK_PATH,
    TIMELINE_GROUP,
    centerline_points,
    cross_section,
    identity_mapping,
    network_document,
    node_index,
    not_provided,
    polyline_length,
    production_group_states,
    require_group,
    require_mine_exchange,
    shafts_state,
    source_state,
)
from minegen.adapters.contracts import AdapterIdentityEntry, AdapterOmission
from minegen.adapters.errors import AdapterConversionFailedError, MineExchangeBundleInvalidError
from minegen.adapters.package import README_PATH, AdapterPackage, PackageBuilder
from minegen.exchange.formats.csv_table import write_csv

ADAPTER_NAME = "VENTSIM"
ADAPTER_VERSION = "0.1.0"
SUPPORTED_MINE_EXCHANGE_VERSIONS = ">=1.2.0,<2.0.0"
PACKAGE_ROOT = "ventsim_package"

DXF_PATH = "geometry/mine_centerlines.dxf"
NODES_PATH = "network/nodes.csv"
AIRWAYS_PATH = "network/airways.csv"
ENTITY_MAP_PATH = "identity/entity_map.csv"

#: an edge's centerline end points must coincide with its topology nodes
#: (the network builder welds at 1e-6 m); 1e-4 m absorbs the JSON / CSV
#: float round trips — a larger gap is a conversion refusal, never a snap
ENDPOINT_WELD_TOLERANCE_M = 1e-4
LENGTH_CONSISTENCY_REL_TOLERANCE = 1e-6

#: Ventsim inputs no MineGen authority owns (directive §26): never written,
#: never defaulted
NOT_PROVIDED_PROPERTIES: tuple[tuple[str, str], ...] = (
    ("AIRWAY_FRICTION_FACTOR", "airway friction factor / wall roughness"),
    ("AIRWAY_RESISTANCE", "airway resistance / shock losses"),
    ("FANS", "fan placement and fan curves"),
    ("REGULATORS_AND_DOORS", "regulators, doors, stoppings, leakage"),
    ("HEAT_SOURCES", "heat loads (rock, diesel, electrical)"),
    ("DIESEL_AND_CONTAMINANT_SOURCES", "diesel emissions, gas / dust sources"),
    ("AIRFLOW_AND_PRESSURE", "airflow / pressure boundary conditions and air density"),
)


def build_ventsim_package(bundle: MineExchangeBundle) -> AdapterPackage:
    adapter = ADAPTER_NAME
    require_mine_exchange(
        bundle,
        adapter=adapter,
        minimum=MINE_EXCHANGE_1_2,
        supported=SUPPORTED_MINE_EXCHANGE_VERSIONS,
    )
    require_group(bundle, "EXCAVATIONS", adapter=adapter, why="the seed needs the centerlines")
    require_group(bundle, "NETWORK", adapter=adapter, why="the seed needs the MineNetwork topology")
    for path in (CENTERLINES_DXF_PATH, CENTERLINES_CSV_PATH, NETWORK_PATH):
        if not bundle.has(path):
            raise MineExchangeBundleInvalidError(
                "required file missing although its group is not omitted",
                adapter=adapter,
                subject=path,
            )
    network = network_document(bundle, adapter=adapter)
    centerlines = centerline_points(bundle, adapter=adapter)
    handles = bundle.dxf_handles(CENTERLINES_DXF_PATH)
    handle_of_entity: dict[str, str] = {}
    for dxf_handle, row in handles.items():
        entity_id: str = row.get("entityId") or ""
        if entity_id in handle_of_entity:
            raise MineExchangeBundleInvalidError(
                "entity carries two DXF handles in the manifest",
                adapter=adapter,
                subject=entity_id,
            )
        handle_of_entity[entity_id] = dxf_handle
    nodes = node_index(network)

    airways: list[tuple[Any, ...]] = []
    edge_of_entity: dict[str, str] = {}
    omissions: list[AdapterOmission] = []
    warnings: list[str] = []
    by_type: dict[str, int] = {}
    max_weld = 0.0
    for e in network.edges:
        if e.geometry_contract == "NONE" or e.geometry_entity_id is None:
            omissions.append(
                AdapterOmission(
                    subject=f"edge:{e.id}",
                    reason_code="NO_GEOMETRY_CONTRACT",
                    detail=(
                        f"edge type {e.type} carries no owning centerline in the bundle; no "
                        "airway geometry is invented for it"
                    ),
                )
            )
            continue
        cl = centerlines.get(e.geometry_entity_id)
        handle = handle_of_entity.get(e.geometry_entity_id)
        if cl is None or handle is None:
            raise MineExchangeBundleInvalidError(
                f"geometry entity {e.geometry_entity_id!r} has no centerline / DXF handle",
                adapter=adapter,
                source_group="NETWORK",
                subject=e.id,
            )
        if e.geometry_entity_id in edge_of_entity:
            raise MineExchangeBundleInvalidError(
                f"geometry entity {e.geometry_entity_id!r} is owned by two edges",
                adapter=adapter,
                source_group="NETWORK",
                subject=e.id,
            )
        edge_of_entity[e.geometry_entity_id] = e.id
        a = np.asarray(nodes[e.source_node_id].position, dtype=np.float64)
        b = np.asarray(nodes[e.target_node_id].position, dtype=np.float64)
        weld = max(
            float(np.linalg.norm(cl.points[0] - a)), float(np.linalg.norm(cl.points[-1] - b))
        )
        max_weld = max(max_weld, weld)
        if weld > ENDPOINT_WELD_TOLERANCE_M:
            raise AdapterConversionFailedError(
                f"centerline end points are {weld:.6f} m from the topology nodes "
                f"{e.source_node_id!r} -> {e.target_node_id!r} (tolerance "
                f"{ENDPOINT_WELD_TOLERANCE_M} m); never snapped or reversed",
                adapter=adapter,
                source_group="NETWORK",
                subject=e.id,
            )
        length = polyline_length(cl.points)
        if abs(length - e.length) > LENGTH_CONSISTENCY_REL_TOLERANCE * max(1.0, e.length):
            raise MineExchangeBundleInvalidError(
                f"declared length {e.length} m but the owning centerline measures {length} m",
                adapter=adapter,
                source_group="NETWORK",
                subject=e.id,
            )
        width, height, shape = cross_section(e)
        if width is None or height is None:
            warnings.append(
                f"edge {e.id!r} carries no cross-section in the bundle; widthM / heightM are "
                "blank (NOT_PROVIDED)"
            )
        by_type[e.type] = by_type.get(e.type, 0) + 1
        airways.append(
            (
                e.id,
                e.geometry_entity_id,
                e.source_node_id,
                e.target_node_id,
                e.type,
                e.length,
                width,
                height,
                shape,
                e.orientation,
                handle,
                cl.level_id,
                int(cl.points.shape[0]),
            )
        )
    if not airways:
        raise AdapterConversionFailedError(
            "the network carries no edge with an owning centerline; nothing to seed",
            adapter=adapter,
            source_group="NETWORK",
        )

    pkg = PackageBuilder(root=PACKAGE_ROOT, adapter=adapter)
    dxf_entry = bundle.file_entry(CENTERLINES_DXF_PATH)
    pkg.add(
        DXF_PATH,
        bundle.file(CENTERLINES_DXF_PATH),
        target_semantic="VENTSIM_CENTERLINES_FOR_CONVERT",
        source_files=[CENTERLINES_DXF_PATH],
        source_entity_ids=list(dxf_entry.source_entity_ids),
    )
    pkg.add(
        NODES_PATH,
        write_csv(
            ("nodeId", "nodeType", "x", "y", "z", "levelId", "surface"),
            [(n.id, n.type, *n.position, n.level_id, n.surface) for n in network.nodes],
        ).encode("utf-8"),
        target_semantic="AIRWAY_JUNCTION_TABLE",
        source_files=[NETWORK_PATH],
    )
    pkg.add(
        AIRWAYS_PATH,
        write_csv(
            (
                "edgeId",
                "geometryEntityId",
                "sourceNodeId",
                "targetNodeId",
                "edgeType",
                "lengthM",
                "widthM",
                "heightM",
                "shape",
                "orientation",
                "dxfHandle",
                "levelId",
                "vertexCount",
            ),
            airways,
        ).encode("utf-8"),
        target_semantic="AIRWAY_ATTRIBUTE_TABLE",
        source_files=[NETWORK_PATH, CENTERLINES_CSV_PATH, "manifest.json"],
    )
    identity_rows = []
    identity: list[AdapterIdentityEntry] = []
    for handle in sorted(handles, key=lambda h: int(h, 16)):
        row = handles[handle]
        entity_id = row.get("entityId", "")
        entity = bundle.entities.get(entity_id)
        edge_id = edge_of_entity.get(entity_id)
        identity_rows.append(
            (
                handle,
                row.get("layer"),
                row.get("entityType"),
                entity_id,
                entity.kind if entity is not None else None,
                entity.level_id if entity is not None else None,
                edge_id,
            )
        )
        identity.append(
            AdapterIdentityEntry(
                target_id=handle,
                target_kind="DXF_HANDLE",
                bundle_entity_id=entity_id,
                bundle_edge_id=edge_id,
                file=DXF_PATH,
            )
        )
    pkg.add(
        ENTITY_MAP_PATH,
        write_csv(
            ("dxfHandle", "layer", "dxfEntityType", "entityId", "entityKind", "levelId", "edgeId"),
            identity_rows,
        ).encode("utf-8"),
        target_semantic="IDENTITY_MAP",
        source_files=["manifest.json", NETWORK_PATH],
    )

    manifest_fields: dict[str, Any] = dict(
        adapter_name=ADAPTER_NAME,
        adapter_version=ADAPTER_VERSION,
        target_application="VENTSIM",
        supported_mine_exchange_versions=SUPPORTED_MINE_EXCHANGE_VERSIONS,
        source_mine_exchange_version=bundle.version,
        source_scenario_id=bundle.manifest.scenario_id,
        source_scenario_name=bundle.manifest.scenario_name,
        source_snapshot=bundle.manifest.source_snapshot.model_dump(mode="json", by_alias=True),
        coordinate_mapping=identity_mapping(
            "metres, X east / Y north / Z up, local synthetic origin. Ventsim imports a DXF in "
            "the Ventsim file's CURRENT units and coordinates (vendor manual): the Ventsim file "
            "must be metric; no re-basing is applied"
        ),
        identity_map=identity,
        source_states=[
            source_state(
                bundle, "EXCAVATIONS", consumed=True, detail_when_available="centerline DXF + CSV"
            ),
            source_state(bundle, "NETWORK", consumed=True, detail_when_available="nodes + edges"),
            shafts_state(
                bundle,
                consumed=True,
                detail_when_available="shaft axes / station drives are SHAFT / "
                "SHAFT_STATION_ACCESS airways",
            ),
            *[
                source_state(bundle, g, consumed=False, detail_when_available="")
                for g in ("CAPABILITY", "RENDER_GLB")
            ],
            *production_group_states(bundle, consumed=False, detail_when_available=""),
            source_state(bundle, TIMELINE_GROUP, consumed=False, detail_when_available=""),
            source_state(bundle, "FIELD_LATTICE", consumed=False, detail_when_available=""),
        ],
        assumptions=[
            not_provided(kind, what, scope="ALL_AIRWAYS") for kind, what in NOT_PROVIDED_PROPERTIES
        ],
        warnings=warnings,
        omissions=omissions,
        details={
            "airwayCount": len(airways),
            "airwayCountByType": dict(sorted(by_type.items())),
            "nodeCount": len(network.nodes),
            "surfaceNodeCount": sum(1 for n in network.nodes if n.surface),
            "dxfPolylineCount": len(handles),
            "maxEndpointWeldM": max_weld,
            "geometryFidelity": "FULL (bundle DXF copied verbatim; no simplification)",
            "dimensionDelivery": (
                "network/airways.csv (handoff / QA table; DXF carries geometry only)"
            ),
        },
    )
    pkg.add(
        README_PATH,
        _readme(manifest_fields, len(airways), len(network.nodes)),
        target_semantic="README",
        source_files=["manifest.json"],
    )
    return pkg.finish(manifest_fields)


def _readme(fields: dict[str, Any], airway_count: int, node_count: int) -> bytes:
    lines = [
        f"Ventsim SEED package — {ADAPTER_NAME} adapter {ADAPTER_VERSION} over MineExchange "
        f"{fields['source_mine_exchange_version']} (scenario {fields['source_scenario_id']} "
        f"'{fields['source_scenario_name']}')",
        "",
        "This is a GEOMETRY / NETWORK SEED for a Ventsim airway model, not a ventilation model.",
        "It carries MineGen's development topology; friction factors, resistances, fans,",
        "regulators, doors, leakage, heat, diesel emissions, airflow and pressure have no",
        "MineGen authority and are NOT PROVIDED — configure them in Ventsim.",
        "adapter_manifest.json is the meaning authority of this package.",
        "",
        "Files",
        f"  {DXF_PATH}   the MineExchange centerline DXF, byte for byte: one 3-D",
        "                                  POLYLINE per excavation entity, layer = kind (RAMP,",
        "                                  LEVEL_ACCESS, DRIFT, CROSSCUT, SHAFT), $INSUNITS = 6",
        f"  {NODES_PATH}                 MineNetwork nodes (id, type, x, y, z, levelId, surface)",
        f"  {AIRWAYS_PATH}               one row per network edge: authoritative length, width,",
        "                                  height, profile shape, orientation, DXF handle, level",
        f"  {ENTITY_MAP_PATH}          DXF handle <-> excavation entity <-> network edge",
        "",
        "Coordinates: metres, X east, Y north, Z up, LOCAL SYNTHETIC origin (no georeference).",
        "Ventsim imports a DXF in the Ventsim file's CURRENT units and coordinates — set the",
        "Ventsim file to metres before importing; do not let Ventsim rescale.",
        "",
        "Documented Ventsim workflow (Ventsim DESIGN user guide, Import)",
        f"  1. File > Import > DXF: {DXF_PATH}",
        "  2. Import the centrelines (as reference graphics or directly as airways).",
        "  3. Convert centrelines to airways (at import, or Add > Convert on the polylines).",
        "     Consecutive polyline vertices become a chain of airways; polylines share their",
        "     end vertices at every MineNetwork node, so the chains join.",
        "  4. Verify the metric / local coordinate basis of the imported geometry.",
        f"  5. Use {AIRWAYS_PATH} to assign / check airway dimensions (widthM, heightM,",
        "     shape) per DXF handle / layer. The CSV is an authoritative handoff / QA table —",
        "     applying attributes inside Ventsim is the documented USER workflow; no official",
        "     automated attribute import is claimed.",
        "  6. Configure ventilation physics (friction, fans, regulators, sources) in Ventsim.",
        "",
        f"Delivered: {airway_count} airways over {node_count} nodes, full-fidelity centerlines.",
        "No proprietary Ventsim project file (.vsm) is produced.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")
