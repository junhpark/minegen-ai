"""MineExchange bundle projection (pure): validated inputs → files + manifest
facts. Nothing here reads the file system, runs a search or persists.

Bundle tree (``mine_exchange/``)::

    manifest.json  README.txt
    terrain/     terrain_grid.csv  terrain.asc  terrain_surface.{stl,obj,glb}
    orebody/     orebody.json  orebody.{stl,obj,glb}
    geology/     faults.json  faults.dxf  faults.glb
    excavations/ entities.json  centerlines.csv  centerlines.dxf
                 solids/<entity>.stl  mine_multibody.stl  render/{tunnel,development}.glb
    topology/    network.json  nodes.csv  edges.csv
    semantics/   capability.json
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from minegen.core.artifacts import (
    CAPABILITY_GRAPH_ARTIFACT,
    DEVELOPMENT_MESH_ARTIFACT,
    NETWORK_ARTIFACT,
    TUNNEL_MESH_ARTIFACT,
)
from minegen.core.models import Scenario
from minegen.exchange.formats.asc import write_esri_ascii_grid
from minegen.exchange.formats.csv_table import write_csv
from minegen.exchange.formats.dxf import DxfDocument, DxfPolygon, DxfPolyline, write_dxf
from minegen.exchange.formats.glb import MINE_TO_GLTF_MATRIX, write_mesh_glb
from minegen.exchange.formats.json_document import dumps
from minegen.exchange.formats.obj import write_obj
from minegen.exchange.formats.stl import concatenate_stl_triangles, write_binary_stl
from minegen.exchange.geometry.centerlines import (
    RAMP_ENTITY_ID,
    CenterlineEntity,
    access_centerlines,
    geometry_ref_index,
    level_centerlines,
    ramp_centerlines,
    shaft_centerlines,
)
from minegen.exchange.geometry.excavation import (
    ExcavationSolid,
    ExcavationSweepError,
    development_solids,
    ramp_solid,
)
from minegen.exchange.geometry.faults import faults_document, project_faults
from minegen.exchange.geometry.orebody import OREBODY_ENTITY_ID, orebody_document, orebody_mesh
from minegen.exchange.geometry.qa import mesh_qa
from minegen.exchange.geometry.terrain import terrain_grid_rows, terrain_surface
from minegen.exchange.models import (
    COORDINATE_FRAME,
    GLTF_FRAME,
    MINE_EXCHANGE_VERSION,
    ExchangeCapability,
    ExchangeCapabilityEdge,
    ExchangeCapabilityNode,
    ExchangeEgressAdvisory,
    ExchangeEntity,
    ExchangeNetwork,
    ExchangeNetworkEdge,
    ExchangeNetworkNode,
    ExchangeOmission,
    ExchangeRequiredPath,
    GeometryQa,
    GlbFrame,
    MultiBodyComponent,
    SourceSnapshot,
)
from minegen.world.synthetic_world import SyntheticWorld

__all__ = [
    "ArtifactInput",
    "BundleFile",
    "BundleSpec",
    "ExchangeExportError",
    "ExchangeInputs",
    "build_exchange",
]

SURFACE_NODE_TYPES = frozenset({"PORTAL", "SHAFT_COLLAR"})
_MEDIA = {
    "csv": "text/csv",
    "asc": "text/plain",
    "stl": "model/stl",
    "obj": "model/obj",
    "glb": "model/gltf-binary",
    "dxf": "application/dxf",
    "json": "application/json",
}


class ExchangeExportError(RuntimeError):
    """A mandatory bundle member cannot be produced honestly (a closed-solid
    QA failure on backend-authored geometry, a sweep failure) — the whole
    export fails; no partial bundle is ever returned."""

    code = "MINE_EXCHANGE_EXPORT_FAILED"
    http_status = 409

    def __init__(self, detail: str) -> None:
        super().__init__(f"MineExchange export failed: {detail}")


@dataclass(frozen=True)
class ArtifactInput:
    document: dict[str, Any]
    revision: str


@dataclass
class ExchangeInputs:
    scenario: Scenario
    world: SyntheticWorld
    scenario_revision: str
    arrays_revision: str
    active_source: Literal["LEGACY", "LAYOUT_V2"]
    #: the ACTIVE Effective Ramp payload (source-neutral contract) + its owner
    ramp: ArtifactInput | None = None
    ramp_artifact: str | None = None
    accesses: ArtifactInput | None = None
    levels: ArtifactInput | None = None
    shafts: ArtifactInput | None = None
    network: ArtifactInput | None = None
    capability: ArtifactInput | None = None
    tunnel_report: ArtifactInput | None = None
    tunnel_glb: bytes | None = None
    development_report: ArtifactInput | None = None
    development_glb: bytes | None = None
    #: every observed artifact's file revision (provenance)
    artifact_revisions: dict[str, str] = field(default_factory=dict)


@dataclass
class BundleFile:
    path: str  # relative to the bundle root, forward slashes
    data: bytes
    semantic_type: str
    representation: str
    source_entity_ids: list[str]
    source_artifact: str | None
    source_revision: str | None
    derived: bool
    coordinate_frame: str = COORDINATE_FRAME
    geometry: GeometryQa | None = None
    glb: GlbFrame | None = None
    components: list[MultiBodyComponent] | None = None
    dxf_entities: list[dict[str, str]] | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def media_type(self) -> str:
        return _MEDIA[self.path.rsplit(".", 1)[-1]]


@dataclass
class BundleSpec:
    scenario_id: str
    scenario_name: str
    source_snapshot: SourceSnapshot
    files: list[BundleFile]
    entities: list[ExchangeEntity]
    omissions: list[ExchangeOmission]
    notes: list[str]


def _glb_frame() -> GlbFrame:
    return GlbFrame(
        stored_vertex_frame=COORDINATE_FRAME,
        scene_frame=GLTF_FRAME,
        source_frame=COORDINATE_FRAME,
        transform_matrix=list(MINE_TO_GLTF_MATRIX),
    )


def _copied_glb_frame() -> GlbFrame:
    return GlbFrame(
        stored_vertex_frame=COORDINATE_FRAME,
        scene_frame=COORDINATE_FRAME,
        source_frame=COORDINATE_FRAME,
        transform_matrix=None,
    )


def file_stem(entity_id: str) -> str:
    """Deterministic file name of an entity: ``:`` → ``_``; other characters
    kept when path-safe."""
    return re.sub(r"[^A-Za-z0-9_+\-.]", "_", entity_id.replace(":", "_"))


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #


def build_exchange(inputs: ExchangeInputs) -> BundleSpec:
    files: list[BundleFile] = []
    entities: list[ExchangeEntity] = []
    omissions: list[ExchangeOmission] = []
    notes: list[str] = []

    _terrain(inputs, files, entities)
    _orebody(inputs, files, entities)
    _faults(inputs, files, entities)
    centerlines = _excavations(inputs, files, entities, omissions)
    _topology(inputs, centerlines, files, entities, omissions)
    _capability(inputs, files, omissions)
    for group, detail in (
        ("STOPES", "planned stope geometry is a Phase 21A.2 MineExchange extension"),
        ("TIMELINE", "development / production scheduling is not part of MineExchange v1"),
        (
            "FIELD_LATTICE",
            "grade / rock-quality lattices are not exported in v1 (no block-model semantics)",
        ),
    ):
        omissions.append(
            ExchangeOmission(
                group=group, reason_code="NOT_IN_V1", detail=detail, source_artifact=None
            )
        )
    notes.append(
        "Individual excavation solids are closed but overlap at junctions and are NOT "
        "boolean-unioned; "
        "mine_multibody.stl is a concatenation, never an engineering solid."
    )
    notes.append(
        "Dual-egress and required capability paths are design advisories, never statutory claims."
    )
    return BundleSpec(
        scenario_id=inputs.scenario.id,
        scenario_name=inputs.scenario.name,
        source_snapshot=SourceSnapshot(
            scenario_revision=inputs.scenario_revision,
            arrays_revision=inputs.arrays_revision,
            active_ramp_source=inputs.active_source,
            artifact_revisions=dict(sorted(inputs.artifact_revisions.items())),
        ),
        files=files,
        entities=entities,
        omissions=omissions,
        notes=notes,
    )


# --------------------------------------------------------------------------- #
# terrain
# --------------------------------------------------------------------------- #


def _terrain(
    inputs: ExchangeInputs, files: list[BundleFile], entities: list[ExchangeEntity]
) -> None:
    t = inputs.world.terrain
    eid = "terrain:surface"
    rows = terrain_grid_rows(t)
    files.append(
        BundleFile(
            "terrain/terrain_grid.csv",
            write_csv(("i", "j", "x", "y", "z"), rows).encode("utf-8"),
            "TERRAIN_GRID",
            "NODE_GRID",
            [eid],
            "arrays.npz",
            inputs.arrays_revision,
            False,
            notes=[
                "lossless node grid: z at (x0 + i·spacing, y0 + j·spacing); "
                "bilinear interpolation between nodes"
            ],
        )
    )
    files.append(
        BundleFile(
            "terrain/terrain.asc",
            write_esri_ascii_grid(t.x0, t.y0, t.spacing, t.z).encode("utf-8"),
            "TERRAIN_GRID",
            "ESRI_ASCII_GRID",
            [eid],
            "arrays.npz",
            inputs.arrays_revision,
            False,
            notes=[
                "ESRI ASCII grid, node-centred (xllcenter / yllcenter); "
                "first row = north-most nodes"
            ],
        )
    )
    positions, triangles = terrain_surface(t)
    qa = mesh_qa(positions, triangles)
    geometry = GeometryQa(
        closed=False,
        watertight=False,
        manifold=qa.manifold,
        unioned=None,
        triangle_count=int(triangles.shape[0]),
        vertex_count=int(positions.shape[0]),
    )
    surface_notes = [
        "derived planar TIN of the bilinear node grid (sourceModel = BILINEAR_NODE_GRID): "
        "two triangles per cell",
        "an OPEN surface — not a terrain solid",
    ]
    files.append(
        BundleFile(
            "terrain/terrain_surface.stl",
            write_binary_stl(positions, triangles, "MineExchange terrain_surface LOCAL_ENU_Z_UP m"),
            "TERRAIN_SURFACE",
            "SURFACE_MESH",
            [eid],
            "arrays.npz",
            inputs.arrays_revision,
            True,
            geometry=geometry,
            notes=surface_notes,
        )
    )
    files.append(
        BundleFile(
            "terrain/terrain_surface.obj",
            write_obj(positions, triangles, eid).encode("utf-8"),
            "TERRAIN_SURFACE",
            "SURFACE_MESH",
            [eid],
            "arrays.npz",
            inputs.arrays_revision,
            True,
            geometry=geometry,
            notes=surface_notes,
        )
    )
    files.append(
        BundleFile(
            "terrain/terrain_surface.glb",
            write_mesh_glb(
                positions,
                [("terrain", triangles, {"entityId": eid, "semanticType": "TERRAIN_SURFACE"})],
                name="terrain_surface",
                node_extras={"entityId": eid, "semanticType": "TERRAIN_SURFACE"},
            ),
            "TERRAIN_SURFACE",
            "SURFACE_MESH",
            [eid],
            "arrays.npz",
            inputs.arrays_revision,
            True,
            geometry=geometry,
            glb=_glb_frame(),
            notes=surface_notes,
        )
    )
    entities.append(
        ExchangeEntity(
            entity_id=eid,
            kind="TERRAIN",
            source_artifact="arrays.npz",
            source_id="terrain",
            files=[
                "terrain/terrain_grid.csv",
                "terrain/terrain.asc",
                "terrain/terrain_surface.stl",
                "terrain/terrain_surface.obj",
                "terrain/terrain_surface.glb",
            ],
        )
    )


# --------------------------------------------------------------------------- #
# orebody
# --------------------------------------------------------------------------- #


def _orebody(
    inputs: ExchangeInputs, files: list[BundleFile], entities: list[ExchangeEntity]
) -> None:
    body = inputs.world.orebody
    eid = OREBODY_ENTITY_ID
    files.append(
        BundleFile(
            "orebody/orebody.json",
            dumps(orebody_document(inputs.scenario, body)),
            "OREBODY_MODEL",
            "DOCUMENT",
            [eid],
            "scenario.json",
            inputs.scenario_revision,
            False,
            notes=["the solid model is the membership authority; the meshes are derived surfaces"],
        )
    )
    positions, triangles = orebody_mesh(body)
    qa = mesh_qa(positions, triangles)
    if not qa.closed_solid:
        raise ExchangeExportError(
            f"{eid}: the derived orebody mesh is not a closed solid ({'; '.join(qa.problems)})"
        )
    geometry = GeometryQa(
        closed=True,
        watertight=True,
        manifold=True,
        unioned=None,
        triangle_count=qa.triangle_count,
        vertex_count=qa.vertex_count,
        signed_volume_m3=qa.signed_volume,
    )
    note = [
        f"derived surface of the {body.to_dict()['type']} solid; "
        "QA: closed, watertight, manifold, outward"
    ]
    files.append(
        BundleFile(
            "orebody/orebody.stl",
            write_binary_stl(positions, triangles, "MineExchange orebody LOCAL_ENU_Z_UP m"),
            "OREBODY",
            "DERIVED_SURFACE_OF_SOLID",
            [eid],
            "scenario.json",
            inputs.scenario_revision,
            True,
            geometry=geometry,
            notes=note,
        )
    )
    files.append(
        BundleFile(
            "orebody/orebody.obj",
            write_obj(positions, triangles, eid).encode("utf-8"),
            "OREBODY",
            "DERIVED_SURFACE_OF_SOLID",
            [eid],
            "scenario.json",
            inputs.scenario_revision,
            True,
            geometry=geometry,
            notes=note,
        )
    )
    files.append(
        BundleFile(
            "orebody/orebody.glb",
            write_mesh_glb(
                positions,
                [("orebody", triangles, {"entityId": eid, "semanticType": "OREBODY"})],
                name="orebody",
                node_extras={"entityId": eid, "semanticType": "OREBODY"},
            ),
            "OREBODY",
            "DERIVED_SURFACE_OF_SOLID",
            [eid],
            "scenario.json",
            inputs.scenario_revision,
            True,
            geometry=geometry,
            glb=_glb_frame(),
            notes=note,
        )
    )
    entities.append(
        ExchangeEntity(
            entity_id=eid,
            kind="OREBODY",
            source_artifact="scenario.json",
            source_id="orebody",
            files=[
                "orebody/orebody.json",
                "orebody/orebody.stl",
                "orebody/orebody.obj",
                "orebody/orebody.glb",
            ],
        )
    )


# --------------------------------------------------------------------------- #
# faults
# --------------------------------------------------------------------------- #


def _faults(
    inputs: ExchangeInputs, files: list[BundleFile], entities: list[ExchangeEntity]
) -> None:
    faults = project_faults(inputs.world)
    ids = [f.entity_id for f in faults]
    files.append(
        BundleFile(
            "geology/faults.json",
            dumps(faults_document(faults)),
            "FAULT_MODEL",
            "DOCUMENT",
            ids,
            "scenario.json",
            inputs.scenario_revision,
            False,
        )
    )
    doc = DxfDocument(
        polygons=[
            DxfPolygon(f.entity_id, "FAULT", f.polygon) for f in faults if f.polygon.shape[0] >= 3
        ]
    )
    text, mapping = write_dxf(doc)
    surface_qa = GeometryQa(closed=False, watertight=False, unioned=None)
    files.append(
        BundleFile(
            "geology/faults.dxf",
            text.encode("ascii"),
            "FAULT_SURFACE",
            "PLANAR_POLYGONS",
            ids,
            "scenario.json",
            inputs.scenario_revision,
            True,
            geometry=surface_qa,
            dxf_entities=mapping,
            notes=[
                "fault plane clipped to the field-lattice box, fan-triangulated into "
                "3DFACE entities; not a solid"
            ],
        )
    )
    positions: list[np.ndarray] = []
    prims: list[tuple[str, np.ndarray, dict[str, Any]]] = []
    offset = 0
    tri_total = 0
    for f in faults:
        n = int(f.polygon.shape[0])
        if n < 3:
            continue
        positions.append(f.polygon)
        fan = np.asarray(
            [[offset, offset + k, offset + k + 1] for k in range(1, n - 1)], dtype=np.int64
        )
        prims.append((f.entity_id, fan, {"entityId": f.entity_id, "semanticType": "FAULT_SURFACE"}))
        offset += n
        tri_total += int(fan.shape[0])
    pos = np.vstack(positions) if positions else np.zeros((0, 3))
    files.append(
        BundleFile(
            "geology/faults.glb",
            write_mesh_glb(
                pos, prims, name="faults", node_extras={"semanticType": "FAULT_SURFACE"}
            ),
            "FAULT_SURFACE",
            "PLANAR_POLYGONS",
            ids,
            "scenario.json",
            inputs.scenario_revision,
            True,
            geometry=GeometryQa(
                closed=False,
                watertight=False,
                unioned=None,
                triangle_count=tri_total,
                vertex_count=int(pos.shape[0]),
            ),
            glb=_glb_frame(),
        )
    )
    for f in faults:
        entities.append(
            ExchangeEntity(
                entity_id=f.entity_id,
                kind="FAULT",
                source_artifact="scenario.json",
                source_id=f"geology.faults[{ids.index(f.entity_id)}]",
                files=["geology/faults.json", "geology/faults.dxf", "geology/faults.glb"],
            )
        )


# --------------------------------------------------------------------------- #
# excavations
# --------------------------------------------------------------------------- #


def _excavations(
    inputs: ExchangeInputs,
    files: list[BundleFile],
    entities: list[ExchangeEntity],
    omissions: list[ExchangeOmission],
) -> list[CenterlineEntity]:
    ramp = inputs.ramp
    if ramp is None or inputs.ramp_artifact is None:
        omissions.append(
            ExchangeOmission(
                group="EXCAVATIONS",
                reason_code="ARTIFACT_ABSENT",
                detail=f"no {inputs.active_source} Effective Ramp artifact is persisted",
                source_artifact=None,
            )
        )
        return []
    ramp_doc = ramp.document
    if ramp_doc.get("status") == "FAILED" or not ramp_doc.get("segments"):
        omissions.append(
            ExchangeOmission(
                group="EXCAVATIONS",
                reason_code="SOURCE_NOT_SUCCESS",
                detail="the Effective Ramp artifact is FAILED / empty",
                source_artifact=inputs.ramp_artifact,
            )
        )
        return []
    scenario = inputs.scenario
    accesses = inputs.accesses.document if inputs.accesses is not None else None
    levels = inputs.levels.document if inputs.levels is not None else None
    shafts = inputs.shafts.document if inputs.shafts is not None else None

    # -- centerlines (authoritative polylines, stable ids) ------------------ #
    centerlines: list[CenterlineEntity] = ramp_centerlines(ramp_doc, inputs.ramp_artifact)
    if accesses is not None and accesses.get("status") == "SUCCESS":
        centerlines += access_centerlines(accesses)
    if levels is not None and levels.get("status") == "SUCCESS":
        centerlines += level_centerlines(levels)
    if shafts is not None and shafts.get("status") == "SUCCESS":
        centerlines += shaft_centerlines(shafts)
    elif scenario.shafts.specs:
        # declared shafts without a (SUCCESS) shafts artifact: recorded, never faked
        omissions.append(
            ExchangeOmission(
                group="SHAFTS",
                reason_code="ARTIFACT_ABSENT" if shafts is None else "SOURCE_NOT_SUCCESS",
                detail=(
                    "shafts are declared in the scenario but shafts.json is not generated"
                    if shafts is None
                    else f"shafts.json status is {shafts.get('status')}"
                ),
                source_artifact="shafts.json",
            )
        )

    # -- closed solids through the SAME sweep helpers the builders use ------ #
    try:
        solids: list[ExcavationSolid] = [
            ramp_solid(
                ramp_doc, accesses, scenario.ramp, scenario.tunnel_profile, inputs.ramp_artifact
            )
        ]
        solids += development_solids(
            ramp_doc, accesses, levels, scenario.ramp, scenario.tunnel_profile
        )
    except ExcavationSweepError as err:
        raise ExchangeExportError(str(err)) from err
    for solid in solids:
        if not solid.qa.closed_solid:
            raise ExchangeExportError(
                f"{solid.entity_id}: closed-solid QA failed ({'; '.join(solid.qa.problems)})"
            )

    revision_of = {
        inputs.ramp_artifact: ramp.revision,
        **({"level_accesses.json": inputs.accesses.revision} if inputs.accesses else {}),
        **({"levels.json": inputs.levels.revision} if inputs.levels else {}),
        **({"shafts.json": inputs.shafts.revision} if inputs.shafts else {}),
    }
    solid_paths: dict[str, str] = {}
    parts: list[tuple[np.ndarray, np.ndarray]] = []
    components: list[MultiBodyComponent] = []
    first = 0
    for solid in solids:
        path = f"excavations/solids/{file_stem(solid.entity_id)}.stl"
        solid_paths[solid.entity_id] = path
        files.append(
            BundleFile(
                path,
                write_binary_stl(
                    solid.positions,
                    solid.triangles,
                    f"MineExchange {solid.entity_id} LOCAL_ENU_Z_UP m",
                ),
                "EXCAVATION_SOLID",
                "CLOSED_LOGICAL_SWEEP",
                [solid.entity_id],
                solid.source_artifact,
                revision_of.get(solid.source_artifact),
                True,
                geometry=GeometryQa(
                    closed=True,
                    watertight=True,
                    manifold=True,
                    unioned=False,
                    overlapping_at_junctions=True,
                    triangle_count=solid.qa.triangle_count,
                    vertex_count=solid.qa.vertex_count,
                    signed_volume_m3=solid.qa.signed_volume,
                ),
                notes=[
                    "CAP-CAP closed logical sweep of the authoritative centerline with the "
                    "scenario profile (before typed junction apertures); overlaps "
                    "neighbouring solids at junctions; not a boolean union",
                    f"rings: {solid.ring_count}; members: {', '.join(solid.member_source_ids)}",
                ],
            )
        )
        parts.append((solid.positions, solid.triangles))
        components.append(
            MultiBodyComponent(
                entity_id=solid.entity_id,
                first_triangle=first,
                triangle_count=solid.qa.triangle_count,
            )
        )
        first += solid.qa.triangle_count
    mb_pos, mb_tri, _ranges = concatenate_stl_triangles(parts)
    files.append(
        BundleFile(
            "excavations/mine_multibody.stl",
            write_binary_stl(
                mb_pos, mb_tri, "MineExchange mine_multibody (concatenation) LOCAL_ENU_Z_UP m"
            ),
            "EXCAVATION_MULTI_BODY",
            "MULTI_BODY_CONCATENATION",
            [s.entity_id for s in solids],
            None,
            None,
            True,
            geometry=GeometryQa(
                closed=None,
                watertight=None,
                manifold=None,
                unioned=False,
                overlapping_at_junctions=True,
                closed_components=True,
                printability_guaranteed=False,
                engineering_solid_ready=False,
                triangle_count=int(mb_tri.shape[0]),
                vertex_count=int(mb_pos.shape[0]),
            ),
            components=components,
            notes=[
                "3D-printing CONVENIENCE representation: every component is closed, "
                "components overlap; printability is not guaranteed"
            ],
        )
    )

    # -- centerline tables -------------------------------------------------- #
    rows: list[tuple[Any, ...]] = []
    for c in centerlines:
        for k, (x, y, z) in enumerate(c.points.tolist()):
            rows.append((c.entity_id, c.kind, c.level_id, k, x, y, z))
    cl_ids = [c.entity_id for c in centerlines]
    cl_sources = sorted({c.source_artifact for c in centerlines})
    files.append(
        BundleFile(
            "excavations/centerlines.csv",
            write_csv(("entityId", "kind", "levelId", "sequence", "x", "y", "z"), rows).encode(
                "utf-8"
            ),
            "EXCAVATION_CENTERLINES",
            "POLYLINES",
            cl_ids,
            ",".join(cl_sources),
            None,
            False,
            notes=[
                "authoritative centerline points in their persisted order "
                "(never synthesized from a mesh)"
            ],
        )
    )
    layer_of = {
        "RAMP_SEGMENT": "RAMP",
        "LEVEL_ACCESS": "LEVEL_ACCESS",
        "DRIFT_PIECE": "DRIFT",
        "CROSSCUT": "CROSSCUT",
        "SHAFT": "SHAFT",
        "SHAFT_STATION_ACCESS": "SHAFT",
    }
    text, mapping = write_dxf(
        DxfDocument(
            polylines=[DxfPolyline(c.entity_id, layer_of[c.kind], c.points) for c in centerlines]
        )
    )
    files.append(
        BundleFile(
            "excavations/centerlines.dxf",
            text.encode("ascii"),
            "EXCAVATION_CENTERLINES",
            "POLYLINES",
            cl_ids,
            ",".join(cl_sources),
            None,
            False,
            dxf_entities=mapping,
            notes=[
                "3-D POLYLINE per centerline entity; layer = kind; "
                "handle → entityId in this manifest entry"
            ],
        )
    )

    # -- entities ----------------------------------------------------------- #
    entities.append(
        ExchangeEntity(
            entity_id=RAMP_ENTITY_ID,
            kind="RAMP",
            source_artifact=inputs.ramp_artifact,
            source_id="segments[*]",
            files=[solid_paths[RAMP_ENTITY_ID], "excavations/mine_multibody.stl"],
        )
    )
    solid_by_id = {s.entity_id: s for s in solids}
    for c in centerlines:
        cl_files = ["excavations/centerlines.csv", "excavations/centerlines.dxf"]
        if c.entity_id in solid_paths:
            cl_files = [solid_paths[c.entity_id], *cl_files]
        entities.append(
            ExchangeEntity(
                entity_id=c.entity_id,
                kind=c.kind,
                level_id=c.level_id,
                source_artifact=c.source_artifact,
                source_id=c.source_id,
                parent_entity_id=c.parent_entity_id,
                files=cl_files,
            )
        )
    for s in solids:
        if s.kind == "DRIFT":  # the level drift solid (its pieces are centerline entities)
            entities.append(
                ExchangeEntity(
                    entity_id=s.entity_id,
                    kind="DRIFT",
                    level_id=s.level_id,
                    source_artifact=s.source_artifact,
                    source_id=s.source_id,
                    files=[solid_paths[s.entity_id], "excavations/mine_multibody.stl"],
                )
            )
    del solid_by_id
    entity_doc = {
        "mineExchangeVersion": MINE_EXCHANGE_VERSION,
        "semanticType": "EXCAVATION_ENTITIES",
        "coordinateFrame": COORDINATE_FRAME,
        "activeRampSource": inputs.active_source,
        "rampOwningArtifact": inputs.ramp_artifact,
        "profile": {
            "shape": "HORSESHOE",
            "tunnelWidth": scenario.ramp.tunnel_width,
            "tunnelHeight": scenario.ramp.tunnel_height,
            "wallHeight": scenario.tunnel_profile.wall_height,
            "archSegmentsRamp": scenario.tunnel_profile.arch_segments,
            "archSegmentsDevelopment": max(2, scenario.tunnel_profile.arch_segments // 2),
        },
        "solids": [
            {
                "entityId": s.entity_id,
                "kind": s.kind,
                "levelId": s.level_id,
                "file": solid_paths[s.entity_id],
                "sourceArtifact": s.source_artifact,
                "sourceId": s.source_id,
                "members": s.member_source_ids,
                "closed": True,
                "unioned": False,
                "overlappingAtJunctions": True,
                "triangleCount": s.qa.triangle_count,
                "signedVolumeM3": s.qa.signed_volume,
            }
            for s in solids
        ],
        "centerlines": [
            {
                "entityId": c.entity_id,
                "kind": c.kind,
                "levelId": c.level_id,
                "sourceArtifact": c.source_artifact,
                "sourceId": c.source_id,
                "parentEntityId": c.parent_entity_id,
                "pointCount": int(c.points.shape[0]),
            }
            for c in centerlines
        ],
    }
    files.append(
        BundleFile(
            "excavations/entities.json",
            dumps(entity_doc),
            "EXCAVATION_ENTITIES",
            "DOCUMENT",
            [RAMP_ENTITY_ID, *cl_ids],
            ",".join(cl_sources),
            None,
            False,
        )
    )

    # -- render GLBs: copied bytes, never rebuilt ---------------------------- #
    _render_glb(
        inputs.tunnel_report,
        inputs.tunnel_glb,
        TUNNEL_MESH_ARTIFACT,
        "excavations/render/tunnel.glb",
        [RAMP_ENTITY_ID],
        files,
        omissions,
    )
    dev_ids = [s.entity_id for s in solids if s.kind != "RAMP"]
    _render_glb(
        inputs.development_report,
        inputs.development_glb,
        DEVELOPMENT_MESH_ARTIFACT,
        "excavations/render/development.glb",
        dev_ids,
        files,
        omissions,
    )
    return centerlines


def _render_glb(
    report: ArtifactInput | None,
    glb: bytes | None,
    artifact: str,
    path: str,
    entity_ids: list[str],
    files: list[BundleFile],
    omissions: list[ExchangeOmission],
) -> None:
    if report is None or glb is None:
        omissions.append(
            ExchangeOmission(
                group="RENDER_GLB",
                reason_code="ARTIFACT_ABSENT",
                detail=f"{artifact} is not generated",
                source_artifact=artifact,
            )
        )
        return
    doc = report.document
    if doc.get("status") != "SUCCESS":
        omissions.append(
            ExchangeOmission(
                group="RENDER_GLB",
                reason_code="SOURCE_NOT_SUCCESS",
                detail=f"{artifact} status is {doc.get('status')}",
                source_artifact=artifact,
            )
        )
        return
    files.append(
        BundleFile(
            path,
            glb,
            "EXCAVATION_RENDER_SURFACE",
            "RENDER_SURFACE",
            entity_ids,
            artifact,
            report.revision,
            True,
            geometry=GeometryQa(
                # the tunnel report states geometricallyClosed for its EMITTED render
                # mesh; the development report has no whole-file flag and its OPEN
                # endpoint policy (rule 166) makes the render surface not closed
                closed=bool(doc.get("geometricallyClosed"))
                if "geometricallyClosed" in doc
                else False,
                watertight=doc.get("watertight")
                if isinstance(doc.get("watertight"), bool)
                else None,
                manifold=doc.get("manifold") if isinstance(doc.get("manifold"), bool) else None,
                unioned=False,
                junction_apertures=True,
                triangle_count=int(doc["triangleCount"])
                if isinstance(doc.get("triangleCount"), int)
                else None,
            ),
            glb=_copied_glb_frame(),
            notes=[
                "source GLB bytes copied verbatim (typed junction apertures opened; "
                "the frontend applies the mine→Three transform itself)"
            ],
        )
    )


# --------------------------------------------------------------------------- #
# topology
# --------------------------------------------------------------------------- #


def _topology(
    inputs: ExchangeInputs,
    centerlines: list[CenterlineEntity],
    files: list[BundleFile],
    entities: list[ExchangeEntity],
    omissions: list[ExchangeOmission],
) -> None:
    del entities
    if inputs.network is None:
        omissions.append(
            ExchangeOmission(
                group="NETWORK",
                reason_code="ARTIFACT_ABSENT",
                detail="network.json is not generated",
                source_artifact=NETWORK_ARTIFACT,
            )
        )
        return
    net = inputs.network.document
    if net.get("status") != "SUCCESS":
        omissions.append(
            ExchangeOmission(
                group="NETWORK",
                reason_code="SOURCE_NOT_SUCCESS",
                detail=f"network.json status is {net.get('status')}",
                source_artifact=NETWORK_ARTIFACT,
            )
        )
        return
    refs = geometry_ref_index(centerlines)
    nodes = [
        ExchangeNetworkNode(
            id=str(n["id"]),
            type=str(n["type"]),
            position=[float(v) for v in n["position"]],
            level_id=n.get("levelId"),
            surface=str(n["type"]) in SURFACE_NODE_TYPES,
        )
        for n in net["nodes"]
    ]
    edges = []
    for e in net["edges"]:
        ref = e.get("geometryRef") or {}
        key = (str(ref.get("artifact")), int(ref.get("segmentIndex", -1)))
        edges.append(
            ExchangeNetworkEdge(
                id=str(e["id"]),
                type=str(e["type"]),
                source_node_id=str(e["fromNode"]),
                target_node_id=str(e["toNode"]),
                geometry_entity_id=refs.get(key),
                length=float(e["length3d"]),
                orientation=str(e.get("orientation", "DEVELOPMENT")),
                cross_section=e.get("crossSection"),
            )
        )
    doc = ExchangeNetwork(
        mine_exchange_version=MINE_EXCHANGE_VERSION,
        source_artifact=NETWORK_ARTIFACT,
        source_revision=inputs.network.revision,
        nodes=nodes,
        edges=edges,
    )
    node_ids = [n.id for n in nodes]
    files.append(
        BundleFile(
            "topology/network.json",
            dumps(doc.model_dump(mode="json", by_alias=True)),
            "MINE_NETWORK",
            "DOCUMENT",
            node_ids,
            NETWORK_ARTIFACT,
            inputs.network.revision,
            False,
            notes=["semantic authority of the topology; the CSVs are conveniences"],
        )
    )
    files.append(
        BundleFile(
            "topology/nodes.csv",
            write_csv(
                ("id", "type", "x", "y", "z", "levelId", "surface"),
                [(n.id, n.type, *n.position, n.level_id, n.surface) for n in nodes],
            ).encode("utf-8"),
            "MINE_NETWORK_NODES",
            "TABLE",
            node_ids,
            NETWORK_ARTIFACT,
            inputs.network.revision,
            False,
        )
    )
    files.append(
        BundleFile(
            "topology/edges.csv",
            write_csv(
                (
                    "id",
                    "type",
                    "sourceNodeId",
                    "targetNodeId",
                    "geometryEntityId",
                    "length",
                    "orientation",
                ),
                [
                    (
                        e.id,
                        e.type,
                        e.source_node_id,
                        e.target_node_id,
                        e.geometry_entity_id,
                        e.length,
                        e.orientation,
                    )
                    for e in edges
                ],
            ).encode("utf-8"),
            "MINE_NETWORK_EDGES",
            "TABLE",
            [e.id for e in edges],
            NETWORK_ARTIFACT,
            inputs.network.revision,
            False,
        )
    )


# --------------------------------------------------------------------------- #
# semantics
# --------------------------------------------------------------------------- #


def _capability(
    inputs: ExchangeInputs, files: list[BundleFile], omissions: list[ExchangeOmission]
) -> None:
    if inputs.capability is None:
        omissions.append(
            ExchangeOmission(
                group="CAPABILITY",
                reason_code="ARTIFACT_ABSENT",
                detail="capability_graph.json is not generated",
                source_artifact=CAPABILITY_GRAPH_ARTIFACT,
            )
        )
        return
    cap = inputs.capability.document
    advisory = cap.get("egressAdvisory")
    doc = ExchangeCapability(
        mine_exchange_version=MINE_EXCHANGE_VERSION,
        source_artifact=CAPABILITY_GRAPH_ARTIFACT,
        source_revision=inputs.capability.revision,
        capabilities=[str(c) for c in cap.get("capabilities", [])],
        edges=[
            ExchangeCapabilityEdge(
                edge_id=str(e["edgeId"]),
                capabilities=[str(c) for c in e["capabilities"]],
                restrictions=[str(c) for c in e.get("restrictions", [])],
                source=str(e.get("source")),
            )
            for e in cap.get("edges", [])
        ],
        nodes=[
            ExchangeCapabilityNode(
                node_id=str(n["nodeId"]),
                supports=[str(c) for c in n.get("supports", [])],
                surface=bool(n.get("surface")),
            )
            for n in cap.get("nodes", [])
        ],
        surface_node_ids=[str(s) for s in cap.get("surfaceNodeIds", [])],
        required_paths=[
            ExchangeRequiredPath(
                id=str(p["id"]),
                capability=str(p["capability"]),
                source_node_id=str(p["sourceNodeId"]),
                target_node_id=str(p["targetNodeId"]),
                rule=str(p["rule"]),
                physical_reachable=bool(p["physicalReachable"]),
                capability_reachable=bool(p["capabilityReachable"]),
                satisfied=bool(p["satisfied"]),
            )
            for p in cap.get("requiredPaths", [])
        ],
        egress_advisory=(
            ExchangeEgressAdvisory(
                capability=str(advisory["capability"]),
                criterion=str(advisory["criterion"]),
                required_routes=int(advisory["requiredRoutes"]),
                surface_node_ids=[str(s) for s in advisory.get("surfaceNodeIds", [])],
                per_node=list(advisory.get("perNode", [])),
            )
            if isinstance(advisory, dict)
            else None
        ),
        validation=cap.get("validation"),
    )
    files.append(
        BundleFile(
            "semantics/capability.json",
            dumps(doc.model_dump(mode="json", by_alias=True)),
            "CAPABILITY",
            "DOCUMENT",
            [e.edge_id for e in doc.edges],
            CAPABILITY_GRAPH_ARTIFACT,
            inputs.capability.revision,
            False,
            notes=[
                "capability ≠ capacity; egress advisory is a design advisory, "
                "not a statutory compliance determination"
            ],
        )
    )
