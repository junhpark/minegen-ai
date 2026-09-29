"""AnyLogic adapter core: MineExchange 1.3 bundle → operational data package.

    anylogic_package/
      adapter_manifest.json
      README.txt
      data/nodes.csv                  MineNetwork nodes
      data/edges.csv                  MineNetwork edges (storage direction ≠ one-way traffic)
      data/centerline_points.csv      XYZ vertices per geometry entity (path shapes)
      data/capabilities.csv           typed may / may-not tags per edge (capability ≠ capacity)
      data/production_units.csv       every production entity of the ACTIVE method, normalized
      data/tasks.csv                  MineTimeline tasks with external target references
      data/development_progress.csv   per-edge excavation progress (chainage, start node, direction)
      data/production_states.csv      one row per production state transition
      templates/simulation_inputs.csv operational parameters — columns only, values BLANK

Requires MineExchange >= 1.3 (the timeline), MINE_NETWORK and MINE_TIMELINE;
production is optional (a development-only timeline exports).
"""

from __future__ import annotations

import json
from typing import Any

from minegen.adapters.bundle_reader import MineExchangeBundle
from minegen.adapters.common import (
    CAPABILITY_PATH,
    CENTERLINES_CSV_PATH,
    MINE_EXCHANGE_1_3,
    NETWORK_PATH,
    PRODUCTION_DOCUMENTS,
    TIMELINE_GROUP,
    TIMELINE_PATH,
    capability_document,
    centerline_points,
    cross_section,
    edge_index,
    identity_mapping,
    mining_method,
    network_document,
    not_provided,
    production_group_states,
    require_group,
    require_mine_exchange,
    shafts_state,
    source_state,
    timeline_document,
)
from minegen.adapters.contracts import AdapterAssumption, AdapterIdentityEntry, AdapterOmission
from minegen.adapters.errors import MineExchangeBundleInvalidError
from minegen.adapters.package import README_PATH, AdapterPackage, PackageBuilder
from minegen.exchange.formats.csv_table import write_csv
from minegen.exchange.models import (
    ExchangeProductionCutFill,
    ExchangeProductionRoomPillar,
    ExchangeProductionStopes,
)

ADAPTER_NAME = "ANYLOGIC"
ADAPTER_VERSION = "0.1.0"
SUPPORTED_MINE_EXCHANGE_VERSIONS = ">=1.3.0,<2.0.0"
PACKAGE_ROOT = "anylogic_package"

NODES_PATH = "data/nodes.csv"
EDGES_PATH = "data/edges.csv"
POINTS_PATH = "data/centerline_points.csv"
CAPABILITIES_PATH = "data/capabilities.csv"
PRODUCTION_PATH = "data/production_units.csv"
TASKS_PATH = "data/tasks.csv"
PROGRESS_PATH = "data/development_progress.csv"
STATES_PATH = "data/production_states.csv"
TEMPLATE_PATH = "templates/simulation_inputs.csv"

STOPES_DOC = PRODUCTION_DOCUMENTS["STOPES"]
CUT_FILL_DOC = PRODUCTION_DOCUMENTS["CUT_FILL"]
ROOM_PILLAR_DOC = PRODUCTION_DOCUMENTS["ROOM_PILLAR"]

#: operational parameters no MineGen authority owns (directive §40): the
#: template carries the COLUMNS only; every value is blank
SIMULATION_INPUT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("fleetSize", "number of haulage units"),
    ("truckType", "haulage unit model / class"),
    ("lhdType", "loader model / class"),
    ("speedLoadedKmh", "loaded travel speed"),
    ("speedEmptyKmh", "empty travel speed"),
    ("gradeSpeedCurve", "speed vs gradient relation"),
    ("loadingTimeMin", "loading cycle time"),
    ("dumpingTimeMin", "dumping cycle time"),
    ("shiftCalendar", "shift / roster calendar"),
    ("trafficPriority", "right-of-way rules on shared edges"),
    ("dispatchLogic", "dispatch / assignment policy"),
    ("crusherCapacityTph", "crusher throughput"),
    ("stockpileCapacityT", "stockpile capacity"),
)


def _cell(value: float | None) -> float | None:
    return value


def _production_rows(
    bundle: MineExchangeBundle, *, adapter: str
) -> tuple[list[tuple[Any, ...]], list[str], str | None]:
    """Every production entity of the ACTIVE method as one generic row:
    entityId, productionKind, sourceId, levelId, accessReference,
    plannedTonnes, geometricVolumeM3, retained, backfill, parentEntityId.
    Pillars are RETAINED material (never production tonnes); backfills are
    semantic records of a cut void (never production tonnes)."""
    rows: list[tuple[Any, ...]] = []
    ids: list[str] = []
    if bundle.has(STOPES_DOC):
        doc = bundle.document(STOPES_DOC, ExchangeProductionStopes)
        for s in doc.stopes:
            rows.append(
                (
                    s.entity_id,
                    "STOPE",
                    s.stope_id,
                    s.lower_level_id,
                    f"{s.lower_access_node_id};{s.upper_access_node_id}",
                    s.tonnes,
                    s.geometric_volume_m3,
                    False,
                    False,
                    None,
                )
            )
            ids.append(s.entity_id)
        return rows, ids, "STOPES"
    if bundle.has(CUT_FILL_DOC):
        cf = bundle.document(CUT_FILL_DOC, ExchangeProductionCutFill)
        for c in cf.cuts:
            rows.append(
                (
                    c.entity_id,
                    "CUT",
                    c.cut_id,
                    c.lower_level_id,
                    c.access_entity_id or c.access_development_id,
                    c.tonnes,
                    c.geometric_volume_m3,
                    False,
                    False,
                    None,
                )
            )
            ids.append(c.entity_id)
        for b in cf.backfills:
            rows.append(
                (
                    b.entity_id,
                    "BACKFILL",
                    b.backfill_id,
                    None,
                    None,
                    None,  # a backfill is never production tonnes
                    b.volume_m3,
                    False,
                    True,
                    b.source_cut_entity_id,
                )
            )
            ids.append(b.entity_id)
        return rows, ids, "CUT_FILL"
    if bundle.has(ROOM_PILLAR_DOC):
        rp = bundle.document(ROOM_PILLAR_DOC, ExchangeProductionRoomPillar)
        room_access = {
            r.entity_id: (r.access_entity_id or r.access_development_id) for r in rp.rooms
        }
        for u in rp.extraction_units:
            rows.append(
                (
                    u.entity_id,
                    "BENCH",
                    u.unit_id,
                    None,
                    room_access.get(u.room_entity_id),
                    u.tonnes,
                    u.geometric_volume_m3,
                    False,
                    False,
                    u.room_entity_id,
                )
            )
            ids.append(u.entity_id)
        for p in rp.pillars:
            rows.append(
                (
                    p.entity_id,
                    "PILLAR",
                    p.pillar_id,
                    None,
                    None,
                    None,  # retained material: never planned tonnes
                    p.geometric_volume_m3,
                    True,
                    False,
                    None,
                )
            )
            ids.append(p.entity_id)
        return rows, ids, "ROOM_PILLAR"
    return rows, ids, None


def build_anylogic_package(bundle: MineExchangeBundle) -> AdapterPackage:
    adapter = ADAPTER_NAME
    require_mine_exchange(
        bundle,
        adapter=adapter,
        minimum=MINE_EXCHANGE_1_3,
        supported=SUPPORTED_MINE_EXCHANGE_VERSIONS,
    )
    require_group(
        bundle, "NETWORK", adapter=adapter, why="the operational package needs the topology"
    )
    require_group(
        bundle,
        TIMELINE_GROUP,
        adapter=adapter,
        why="the operational package needs the MineTimeline",
    )
    for path in (NETWORK_PATH, TIMELINE_PATH, CENTERLINES_CSV_PATH):
        if not bundle.has(path):
            raise MineExchangeBundleInvalidError(
                "required file missing although its group is not omitted",
                adapter=adapter,
                subject=path,
            )
    network = network_document(bundle, adapter=adapter)
    edges = edge_index(network)
    node_ids = {n.id for n in network.nodes}
    points = centerline_points(bundle, adapter=adapter)
    timeline = timeline_document(bundle, adapter=adapter)
    assert timeline is not None  # TIMELINE_PATH present
    capability = capability_document(bundle)
    production_rows, production_ids, production_kind = _production_rows(bundle, adapter=adapter)
    production_id_set = set(production_ids)
    warnings: list[str] = []
    omissions: list[AdapterOmission] = []

    # -- referential integrity of everything the package hands over --------- #
    for e in network.edges:
        if e.geometry_entity_id is not None and e.geometry_entity_id not in points:
            raise MineExchangeBundleInvalidError(
                f"geometry entity {e.geometry_entity_id!r} has no centerline points",
                adapter=adapter,
                source_group="NETWORK",
                subject=e.id,
            )
        if e.geometry_entity_id is None:
            omissions.append(
                AdapterOmission(
                    subject=f"edge:{e.id}",
                    reason_code="NO_GEOMETRY_CONTRACT",
                    detail=(
                        f"edge type {e.type} owns no centerline; it is exported without a "
                        "path shape"
                    ),
                )
            )
    task_ids = {t.task_id for t in timeline.tasks}
    for t in timeline.tasks:
        ref = t.target_reference
        if ref.kind == "NETWORK_EDGE" and ref.id not in edges:
            raise MineExchangeBundleInvalidError(
                f"task target edge {ref.id!r} is not in the network",
                adapter=adapter,
                source_group=TIMELINE_GROUP,
                subject=t.task_id,
            )
        if ref.kind == "ENTITY" and ref.id not in production_id_set:
            raise MineExchangeBundleInvalidError(
                f"task target entity {ref.id!r} is not an exported production unit",
                adapter=adapter,
                source_group=TIMELINE_GROUP,
                subject=t.task_id,
            )
        for dep in t.dependencies:
            if dep not in task_ids:
                raise MineExchangeBundleInvalidError(
                    f"dependency {dep!r} is not a task",
                    adapter=adapter,
                    source_group=TIMELINE_GROUP,
                    subject=t.task_id,
                )
    for d in timeline.developments:
        if d.edge_id not in edges or d.excavation_start_node not in node_ids:
            raise MineExchangeBundleInvalidError(
                "development progress references an unknown edge / node",
                adapter=adapter,
                source_group=TIMELINE_GROUP,
                subject=d.edge_id,
            )
    for s in timeline.production_states:
        if s.entity_id not in production_id_set:
            raise MineExchangeBundleInvalidError(
                "production state references an unknown production entity",
                adapter=adapter,
                source_group=TIMELINE_GROUP,
                subject=s.entity_id,
            )
    if capability is not None:
        for ce in capability.edges:
            if ce.edge_id not in edges:
                raise MineExchangeBundleInvalidError(
                    "capability edge is not a network edge",
                    adapter=adapter,
                    source_group="CAPABILITY",
                    subject=ce.edge_id,
                )

    # -- tables ---------------------------------------------------------------- #
    pkg = PackageBuilder(root=PACKAGE_ROOT, adapter=adapter)
    pkg.add(
        NODES_PATH,
        write_csv(
            ("nodeId", "nodeType", "x", "y", "z", "levelId", "surface"),
            [(n.id, n.type, *n.position, n.level_id, n.surface) for n in network.nodes],
        ).encode("utf-8"),
        target_semantic="NETWORK_NODES",
        source_files=[NETWORK_PATH],
    )
    edge_rows = []
    for e in network.edges:
        w, h, shape = cross_section(e)
        edge_rows.append(
            (
                e.id,
                e.source_node_id,
                e.target_node_id,
                e.type,
                e.geometry_entity_id,
                e.length,
                w,
                h,
                shape,
                e.orientation,
                e.geometry_contract,
            )
        )
    pkg.add(
        EDGES_PATH,
        write_csv(
            (
                "edgeId",
                "sourceNodeId",
                "targetNodeId",
                "edgeType",
                "geometryEntityId",
                "lengthM",
                "widthM",
                "heightM",
                "shape",
                "orientation",
                "geometryContract",
            ),
            edge_rows,
        ).encode("utf-8"),
        target_semantic="NETWORK_EDGES",
        source_files=[NETWORK_PATH],
    )
    owned = {e.geometry_entity_id for e in network.edges if e.geometry_entity_id is not None}
    point_rows = [
        (entity_id, k, float(x), float(y), float(z))
        for entity_id in sorted(owned)
        for k, (x, y, z) in enumerate(points[entity_id].points.tolist())
    ]
    pkg.add(
        POINTS_PATH,
        write_csv(("geometryEntityId", "sequence", "x", "y", "z"), point_rows).encode("utf-8"),
        target_semantic="PATH_SHAPE_POINTS",
        source_files=[CENTERLINES_CSV_PATH],
        source_entity_ids=sorted(owned),
    )
    cap_rows: list[tuple[Any, ...]] = []
    if capability is not None:
        for ce in capability.edges:
            for c in ce.capabilities:
                cap_rows.append((ce.edge_id, c, True, ce.source))
            for c in ce.restrictions:
                cap_rows.append((ce.edge_id, c, False, ce.source))
    pkg.add(
        CAPABILITIES_PATH,
        write_csv(("edgeId", "capability", "allowed", "source"), cap_rows).encode("utf-8"),
        target_semantic="EDGE_CAPABILITIES",
        source_files=[CAPABILITY_PATH] if capability is not None else [],
    )
    pkg.add(
        PRODUCTION_PATH,
        write_csv(
            (
                "entityId",
                "productionKind",
                "sourceId",
                "levelId",
                "accessReference",
                "plannedTonnes",
                "geometricVolumeM3",
                "retained",
                "backfill",
                "parentEntityId",
            ),
            production_rows,
        ).encode("utf-8"),
        target_semantic="PRODUCTION_UNITS",
        source_files=[p for p in (STOPES_DOC, CUT_FILL_DOC, ROOM_PILLAR_DOC) if bundle.has(p)],
        source_entity_ids=production_ids,
    )
    pkg.add(
        TASKS_PATH,
        write_csv(
            (
                "taskId",
                "taskType",
                "targetKind",
                "targetReferenceKind",
                "targetReferenceId",
                "startDay",
                "endDay",
                "durationDays",
                "dependencies",
                "basisQuantity",
                "basisUnit",
                "basisRate",
                "rateUnit",
            ),
            [
                (
                    t.task_id,
                    t.task_type,
                    t.target_kind,
                    t.target_reference.kind,
                    t.target_reference.id,
                    t.start_day,
                    t.end_day,
                    t.duration_days,
                    json.dumps(t.dependencies, separators=(",", ":")),
                    t.basis.quantity,
                    t.basis.quantity_unit,
                    t.basis.rate,
                    t.basis.rate_unit,
                )
                for t in timeline.tasks
            ],
        ).encode("utf-8"),
        target_semantic="TIMELINE_TASKS",
        source_files=[TIMELINE_PATH],
    )
    pkg.add(
        PROGRESS_PATH,
        write_csv(
            (
                "edgeId",
                "geometryEntityId",
                "taskId",
                "progressStartDay",
                "progressEndDay",
                "excavationStartNode",
                "progressDirection",
                "initialState",
                "pointChainageFractions",
            ),
            [
                (
                    d.edge_id,
                    d.geometry_entity_id,
                    d.task_id,
                    d.progress_start_day,
                    d.progress_end_day,
                    d.excavation_start_node,
                    d.progress_direction,
                    d.initial_state,
                    json.dumps(d.point_chainage_fractions, separators=(",", ":")),
                )
                for d in timeline.developments
            ],
        ).encode("utf-8"),
        target_semantic="DEVELOPMENT_PROGRESS",
        source_files=[TIMELINE_PATH],
    )
    state_rows = [
        (s.entity_id, s.target_kind, s.initial_state, i, x.day, x.state)
        for s in timeline.production_states
        for i, x in enumerate(s.transitions)
    ]
    pkg.add(
        STATES_PATH,
        write_csv(
            ("entityId", "targetKind", "initialState", "transitionIndex", "day", "state"),
            state_rows,
        ).encode("utf-8"),
        target_semantic="PRODUCTION_STATES",
        source_files=[TIMELINE_PATH],
    )
    pkg.add(
        TEMPLATE_PATH,
        write_csv(
            tuple(c for c, _ in SIMULATION_INPUT_COLUMNS),
            [tuple(None for _ in SIMULATION_INPUT_COLUMNS)],
        ).encode("utf-8"),
        target_semantic="SIMULATION_INPUTS_TEMPLATE",
        source_files=[],
    )

    method = mining_method(bundle)
    identity = [
        AdapterIdentityEntry(
            target_id=n.id, target_kind="NODE", bundle_node_id=n.id, file=NODES_PATH
        )
        for n in network.nodes
    ] + [
        AdapterIdentityEntry(
            target_id=e.id,
            target_kind="EDGE",
            bundle_edge_id=e.id,
            bundle_entity_id=e.geometry_entity_id,
            file=EDGES_PATH,
        )
        for e in network.edges
    ]
    assumptions: list[AdapterAssumption] = [
        not_provided(kind, what, scope="SIMULATION") for kind, what in SIMULATION_INPUT_COLUMNS
    ]
    assumptions.append(
        not_provided(
            "MODEL_AXIS_MAPPING",
            "AnyLogic space-markup axis orientation / scale for the XYZ centerline points",
            scope="ALL_GEOMETRY",
        )
    )
    manifest_fields: dict[str, Any] = dict(
        adapter_name=ADAPTER_NAME,
        adapter_version=ADAPTER_VERSION,
        target_application="ANYLOGIC",
        supported_mine_exchange_versions=SUPPORTED_MINE_EXCHANGE_VERSIONS,
        source_mine_exchange_version=bundle.version,
        source_scenario_id=bundle.manifest.scenario_id,
        source_scenario_name=bundle.manifest.scenario_name,
        source_snapshot=bundle.manifest.source_snapshot.model_dump(mode="json", by_alias=True),
        coordinate_mapping=identity_mapping(
            "metres, X east / Y north / Z up, right-handed, local synthetic origin; the AnyLogic "
            "space-markup axis mapping and scale are consumer parameters (MODEL_AXIS_MAPPING)"
        ),
        identity_map=identity,
        source_states=[
            source_state(bundle, "NETWORK", consumed=True, detail_when_available="nodes + edges"),
            source_state(
                bundle, "EXCAVATIONS", consumed=True, detail_when_available="centerline points"
            ),
            source_state(
                bundle,
                TIMELINE_GROUP,
                consumed=True,
                detail_when_available="tasks / progress / states",
            ),
            source_state(
                bundle,
                "CAPABILITY",
                consumed=True,
                detail_when_available="typed may / may-not tags per edge",
            ),
            *production_group_states(
                bundle, consumed=True, detail_when_available="production units"
            ),
            shafts_state(bundle, consumed=True, detail_when_available="shaft edges"),
            source_state(bundle, "RENDER_GLB", consumed=False, detail_when_available=""),
            source_state(bundle, "FIELD_LATTICE", consumed=False, detail_when_available=""),
        ],
        assumptions=assumptions,
        warnings=warnings,
        omissions=omissions,
        details={
            "nodeCount": len(network.nodes),
            "edgeCount": len(network.edges),
            "centerlinePointCount": len(point_rows),
            "capabilityRowCount": len(cap_rows),
            "productionKind": production_kind,
            "productionUnitCount": len(production_rows),
            "retainedPillarCount": sum(1 for r in production_rows if r[7] is True),
            "backfillRecordCount": sum(1 for r in production_rows if r[8] is True),
            "taskCount": len(timeline.tasks),
            "developmentProgressCount": len(timeline.developments),
            "productionStateCount": len(timeline.production_states),
            "timelineStartDay": timeline.start_day,
            "timelineEndDay": timeline.end_day,
            "miningMethod": (method or {}).get("requestedMethod"),
            "directionSemantics": network.direction_semantics,
        },
    )
    pkg.add(
        README_PATH,
        _readme(manifest_fields),
        target_semantic="README",
        source_files=["manifest.json"],
    )
    return pkg.finish(manifest_fields)


def _readme(fields: dict[str, Any]) -> bytes:
    d = fields["details"]
    lines = [
        f"AnyLogic operational data package — {ADAPTER_NAME} adapter {ADAPTER_VERSION} over "
        f"MineExchange {fields['source_mine_exchange_version']} (scenario "
        f"{fields['source_scenario_id']} '{fields['source_scenario_name']}')",
        "",
        "A normalized DATA CONTRACT for an AnyLogic operational model: mine topology, path",
        "shapes, capabilities, production units and the MineGen planning timeline. The",
        "package decides NOTHING about haulage — fleet, speeds, cycle times, calendars,",
        "priorities, dispatch and capacities are blank template columns for you to fill.",
        "adapter_manifest.json is the meaning authority of this package.",
        "",
        "Files (data/)",
        "  nodes.csv                 nodeId, nodeType, x, y, z, levelId, surface",
        "  edges.csv                 edgeId, sourceNodeId, targetNodeId, edgeType,",
        "                            geometryEntityId, lengthM, widthM, heightM, shape,",
        "                            orientation, geometryContract",
        "                            edge direction = storage / centerline orientation — NOT",
        "                            one-way traffic; physical connectivity is undirected",
        "  centerline_points.csv     geometryEntityId, sequence, x, y, z — path shapes (e.g.",
        "                            MarkupSegmentLine(x, y, z) in network-by-code)",
        "  capabilities.csv          edgeId, capability, allowed, source — typed may / may-not",
        "                            tags; capability is NOT capacity (no flow rate is implied)",
        "  production_units.csv      entityId, productionKind (STOPE | CUT | BACKFILL | BENCH |",
        "                            PILLAR), sourceId, levelId, accessReference, plannedTonnes,",
        "                            geometricVolumeM3, retained, backfill, parentEntityId —",
        "                            pillars are RETAINED material (no tonnes); a backfill is the",
        "                            semantic record of a cut void (never production tonnes)",
        "  tasks.csv                 the MineTimeline tasks: targetReferenceKind / Id resolve to",
        "                            edges.csv / production_units.csv; dependencies = JSON list",
        "  development_progress.csv  per edge: progress window, excavationStartNode,",
        "                            progressDirection (+1 / -1 along the point order),",
        "                            pointChainageFractions = JSON list aligned with the points",
        "  production_states.csv     one row per state transition; state(day) = latest",
        "                            transition whose day <= day (exact boundary), initialState",
        "                            before the first",
        "templates/simulation_inputs.csv  columns only — every value blank (no silent default)",
        "",
        "Coordinates: metres, X east / Y north / Z up, right-handed, local synthetic origin.",
        "Map them to your model's space-markup axes and scale explicitly.",
        "",
        "Documented AnyLogic workflow",
        "  1. Import the CSV tables into the built-in database (Text File / Excel import) or",
        "     read them with the Text File element.",
        "  2. Build the network programmatically at startup ('Create network by code'):",
        "     nodes from nodes.csv, paths from centerline_points.csv per geometryEntityId,",
        "     connected by edges.csv.",
        "  3. Use tasks.csv / development_progress.csv / production_states.csv as the",
        "     planning baseline (synthetic earliest-start schedule in days, never a forecast).",
        "  4. Fill templates/simulation_inputs.csv with your operational assumptions.",
        "",
        f"Delivered: {d['nodeCount']} nodes, {d['edgeCount']} edges, {d['taskCount']} tasks, "
        f"{d['productionUnitCount']} production rows ({d['retainedPillarCount']} retained "
        f"pillars, {d['backfillRecordCount']} backfill records), timeline days "
        f"{d['timelineStartDay']}..{d['timelineEndDay']}.",
        "No AnyLogic project file (.alp) is produced.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")
