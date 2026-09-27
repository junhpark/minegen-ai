# MineExchange v1 — canonical interoperability bundle (Phase 23A, 1.1 in Phase 21A)

MineExchange is MineGen's **versioned, read-only projection** of existing
authoritative state into a downloadable, deterministic bundle. It exists so
that external software (mesh viewers, CAD, ventilation / simulation tools,
game engines, slicers) can consume a MineGen mine without ever reading
MineGen's internal `derived/` artifacts, whose shape may change with every
internal refactor.

    MineGen authoritative artifacts
              ↓  validated read (ONE coherent snapshot)
        MineExchange DTOs           backend/src/minegen/exchange/models.py
              ↓
        format writers              backend/src/minegen/exchange/formats/
              ↓
        mine_exchange.zip           backend/src/minegen/exchange/bundle.py

Rule 190 (CLAUDE.md) is the invariant: the export never redesigns the mine,
never re-ranks, never invents engineering semantics and never promotes a
derived representation into a stronger authority. Geometry, topology and
capability stay separate files with separate meanings.

## Version

`manifest.json → mineExchangeVersion = "1.1.0"` (semantic versioning). 1.1
(Phase 21A) is an ADDITIVE minor version over 1.0: the mining-method
semantics document, the production stopes and the `STOPE` entity kind
(see "Mining method and production stopes"); every 1.0 file, id and meaning
is unchanged. The
manifest version is the **external** contract authority; internal artifact
versions (scenario `schemaVersion`, per-artifact `sourceRevision`) are only
quoted as provenance. Additive fields are minor versions; a change in the
meaning of an existing field is a major version.

## API

    POST /api/v1/scenarios/{scenario_id}/export/mine-exchange
      → 200 application/zip
        Content-Disposition: attachment; filename="minegen_<safeScenarioId>_mineexchange_v1.zip"
        X-MineExchange-Version: 1.1.0
        X-MineExchange-Generated-At: <ISO time, NON-authoritative>
      → 404 SCENARIO_NOT_FOUND
      → 409 WORLD_NOT_GENERATED            (the world is the only prerequisite)
      → 409 READ_SNAPSHOT_CHANGED          (a source moved while exporting)
      → 409 <artifact refusal>             (STALE / MALFORMED present artifact:
                                            CAPABILITY_GRAPH_STALE, LAYOUT_V2_SELECTION_STALE,
                                            SHAFTS_STALE, ARTIFACT_MALFORMED, …)
      → 409 MINE_EXCHANGE_EXPORT_FAILED    (a mandatory entity failed its QA, or the
                                            mining-method authorities disagree — 1.1)

The export is **synchronous and read-only**: nothing is generated, nothing is
written under `derived/`, no registry entry, no invalidation cascade. There is
no `derived/mine_exchange.zip`. Frontend: `Export MineExchange (.zip)` in the
Scenario panel (enabled once a world exists; `Preparing export…` while the
request runs; typed refusals through the existing `ApiError` display).

## Coordinate contract

| Field | Value |
| --- | --- |
| `coordinateSystem.name` | `LOCAL_ENU_Z_UP` |
| axes | EAST, NORTH, UP — axis order X, Y, Z — Z vertical — right-handed |
| unit | metre (angles: degree, volumes: cubic metre) |
| `crs` | `LOCAL_SYNTHETIC` — no EPSG, no UTM zone, no `.prj` |

STL, OBJ, DXF and CSV store canonical `LOCAL_ENU_Z_UP` coordinates verbatim.
Two kinds of GLB exist, and each GLB manifest entry declares which one it is
through `glb.storedVertexFrame`, `glb.sceneFrame`, `glb.sourceFrame` and
`glb.transformMatrix`:

| GLB kind | files | stored vertices | scene frame | root transform |
| --- | --- | --- | --- | --- |
| exporter-created | `terrain/terrain_surface.glb`, `orebody/orebody.glb`, `geology/faults.glb` | `LOCAL_ENU_Z_UP` | `GLTF_Y_UP` | mine → glTF rotation as the **root node matrix** (column-major `[1,0,0,0, 0,0,-1,0, 0,1,0,0, 0,0,0,1]`, i.e. `(x, y, z) → (x, z, −y)`, the orientation the viewer applies), recorded as `transformMatrix` |
| copied production render | `excavations/render/tunnel.glb`, `excavations/render/development.glb` | `LOCAL_ENU_Z_UP` | `LOCAL_ENU_Z_UP` | none — `transformMatrix = null`; the production bytes are copied **verbatim** and the consumer applies the rotation itself |

The copied render GLBs' `geometry.junctionApertures` is read from the
authoritative junction report of the source artifact and answers whether an
aperture was ACTUALLY opened: only the aperture outcome counters decide
(`junctions.openedEndpointCount`, `junctions.removedTriangles`, each
`openings[].removedTriangles`) — any positive → `true`, every present
outcome counter zero → `false`, no outcome counter at all → `null`.
`junctions.count` and the mere presence of `openings[]` are not evidence:
production records an opening report for every junction it finds, opened or
not. It is never assumed.

## Bundle tree

    mine_exchange/
      manifest.json                     meaning authority of the bundle
      README.txt
      terrain/terrain_grid.csv          i,j,x,y,z  — the AUTHORITY (lossless node grid)
      terrain/terrain.asc               ESRI ASCII grid, node-centred (xllcenter / yllcenter)
      terrain/terrain_surface.{stl,obj,glb}   derived planar TIN, 2 triangles / cell, OPEN
      orebody/orebody.json              the solid model (authority) + scenario parameters
      orebody/orebody.{stl,obj,glb}     derived surface of the solid (closed, QA'd)
      geology/faults.json               FaultPlane parameters (authority)
      geology/faults.{dxf,glb}          planar polygons clipped to the field-lattice box
      excavations/entities.json         entity catalogue (ids, kinds, sources, point counts)
      excavations/centerlines.csv       entityId,kind,levelId,sequence,x,y,z
      excavations/centerlines.dxf       3-D POLYLINE per entity, layer = kind
      excavations/solids/<entity>.stl   individual CLOSED logical sweep per excavation
      excavations/mine_multibody.stl    concatenation of every solid (NOT a union)
      excavations/render/tunnel.glb     production ramp render mesh, copied verbatim
      excavations/render/development.glb  production development render mesh, copied verbatim
      topology/network.json             MineNetwork DTO (authority for topology)
      topology/nodes.csv, edges.csv     convenience tables
      semantics/capability.json         capability DTO (edge capabilities, required paths, egress advisory)
      semantics/mining_method.json      1.1 — requested method, registry implementation status,
                                        parameters, production-development / production status (ALWAYS present)
      production/stopes.json            1.1 — planned stopes DTO (authority: stopes.json), planning quantities
      production/stopes/<stope>.{stl,obj,glb}  1.1 — one AUTHORITATIVE closed prism per stope (never unioned)

A world-only scenario yields `terrain/`, `orebody/`, `geology/` and
`semantics/mining_method.json` (the scenario is its first authority) and
records everything else under `manifest.omissions[]` (`ARTIFACT_ABSENT`). Partial
exports (world-only, world + ramp, world + ramp + levels, …) are the normal
case: the bundle is a portable snapshot of the currently valid authoritative
state, and the exporter never generates or recomputes a design to fill a
gap. Four situations are kept distinct:

| source state | export outcome |
| --- | --- |
| absent | omission `ARTIFACT_ABSENT` for that group |
| present, VALID, status `FAILED` (optional source: level accesses, levels, shafts, network, capability graph, render meshes, stopes) | omission `SOURCE_NOT_SUCCESS` with the artifact, its status and `failureReason` in `detail`; the rest of the bundle is unaffected |
| present but STALE | typed refusal with the artifact's own code (e.g. `CAPABILITY_GRAPH_STALE`, `LAYOUT_V2_SELECTION_STALE`) — never treated as absent |
| present but MALFORMED | typed refusal `ARTIFACT_MALFORMED` |

Files are never faked; `NOT_IN_V1` omissions name what v1 deliberately leaves
out (timeline, field lattice — stopes joined the bundle in 1.1 and now follow
the `ARTIFACT_ABSENT` / `SOURCE_NOT_SUCCESS` semantics above). A defect in the exporter's own
projection — an unresolvable network geometry reference, a duplicated entity
id or bundle path, a dangling parent, an unrecognised development id, a
closed-solid QA failure — is a typed `409 MINE_EXCHANGE_EXPORT_FAILED`
(`exchange/errors.py`), never a bare 500 and never a partial bundle with a
silent `null`. A bundle **preflight** (`builder.py::preflight_bundle`) checks
referential integrity before any byte is written: unique entity ids, unique
safe paths, every `entities[].files` entry present, every non-null
`parentEntityId` and every excavation / geology `sourceEntityIds` entry
resolving to an entity, and every exported network edge's
`geometryEntityId` resolving.

## Manifest schema (1.1.0)

    mineExchangeVersion   "1.1.0"
    scenarioId, scenarioName
    coordinateSystem      { name, crs, axes, axisOrder, verticalAxis, handedness, unit }
    units                 { length, angle, volume }
    sourceSnapshot        { scenarioRevision, arraysRevision, activeRampSource, artifactRevisions{} }
    entities[]            { entityId, kind, levelId, sourceArtifact, sourceId, sourceMemberIds?,
                            parentEntityId, files[] }
    files[]               { path, sha256, mediaType, semanticType, representation,
                            sourceEntityIds[], sourceArtifact, sourceRevision,
                            coordinateFrame, derived, geometry?, glb?, components?, dxfEntities?, notes[] }
    omissions[]           { group, reasonCode, detail, sourceArtifact }
    extensions            {}   (reserved for version-compatible extensions)

`files[].geometry` (only where meaningful, otherwise null):
`closed, watertight, manifold, unioned, overlappingAtJunctions,
closedComponents, printabilityGuaranteed, engineeringSolidReady,
junctionApertures, triangleCount, vertexCount, signedVolumeM3`.

Semantic types: `MANIFEST, README, TERRAIN_GRID, TERRAIN_SURFACE,
OREBODY_MODEL, OREBODY, FAULT_MODEL, FAULT_SURFACE, EXCAVATION_ENTITIES,
EXCAVATION_CENTERLINES, EXCAVATION_SOLID, EXCAVATION_MULTI_BODY,
EXCAVATION_RENDER_SURFACE, MINE_NETWORK, MINE_NETWORK_NODES,
MINE_NETWORK_EDGES, CAPABILITY` and, since 1.1, `MINING_METHOD,
PRODUCTION_STOPES, STOPE_SOLID`. Representations: `DOCUMENT, TABLE,
NODE_GRID, ESRI_ASCII_GRID, SURFACE_MESH, DERIVED_SURFACE_OF_SOLID,
PLANAR_POLYGONS, POLYLINES, CLOSED_LOGICAL_SWEEP, MULTI_BODY_CONCATENATION,
RENDER_SURFACE` and, since 1.1, `AUTHORITATIVE_CLOSED_MESH` (a closed mesh
that IS the authority's own geometry — the stope prism — not a derived
surface and not a sweep).

## Stable entity identity

External identity is never a list index. Existing authoritative ids are
reused; new ids follow a documented deterministic rule
(`exchange/geometry/centerlines.py`):

| Entity | id rule | example |
| --- | --- | --- |
| terrain | `terrain:surface` | |
| orebody | `orebody:primary` | |
| fault | `fault:F<nn>` (1-based scenario order) | `fault:F01` |
| main ramp | `ramp:main` (aggregate); per segment `ramp:main:<segmentId>` | `ramp:main:S02` |
| level access | `level-access:<levelId>` | `level-access:L01` |
| drift | `drift:<levelId>` (aggregate + solid) / `drift:<levelId>:<piece>` (pieces) | `drift:L01`, `drift:L01:00` |
| crosscut | `crosscut:<levelId>:<station>` | `crosscut:L01:S+00` |
| shaft | `shaft:<shaftId>` (aggregate, kind `SHAFT`); axis segments `shaft:<centerlineId>` (kind `SHAFT_SEGMENT`, parent `shaft:<shaftId>`); station drives `shaft-station-access:<centerlineId>` | `shaft:SHAFT-01`, `shaft:SHAFT:SHAFT-01:SEG00` |
| stope (1.1) | `stope:<stopeId>` (kind `STOPE`, `sourceArtifact = stopes.json`, `sourceId = stopeId`, no parent) | `stope:STOPE:L01-L02:S+00` |

**Aggregates** (`ramp:main`, `drift:<levelId>`, `shaft:<shaftId>`) are parent
entities. Provenance is by kind:

| aggregate | `sourceId` | `sourceMemberIds[]` |
| --- | --- | --- |
| synthetic — `ramp:main`, `drift:<levelId>` (no single authoritative id) | `null` | segment ids / drift piece ids |
| authoritative — `shaft:<shaftId>` (`shafts.json` `shafts[shaftId]`) | `shaftId` | axis segment ids |

Members are listed in persisted order. Every non-null
`parentEntityId` resolves to an entity in the same manifest. The shaft
aggregate owns **no geometry** (`files = []`): shafts are represented by
centerlines only — the axis segments and station drives — and no shaft solid,
Boolean or reinterpretation is emitted. `excavations/entities.json` lists the
aggregates with `ownsGeometry`.

STL file stems are deterministic, **collision-resistant** and path-safe: the
sanitized entity id (`:` and other unsafe characters → `_`) followed by the
first 8 hex characters of the entity id's SHA-256, e.g.
`excavations/solids/crosscut_L01_S+00_73a3bcb0.stl`. The old sanitizer
collisions (`a:b` vs `a_b`) no longer occur, but a 32-bit hash prefix is not
injective in the mathematical sense — **final uniqueness is enforced by the
bundle preflight** (a duplicate path is a typed 409), never assumed from the
stem. Consumers resolve files through `entities[].files` /
`files[].sourceEntityIds`, never by reconstructing a stem. DXF entities carry a
`handle → entityId` table in the manifest (`files[].dxfEntities`).

## Terrain semantics

The terrain authority is the regular node grid `x0, y0, spacing, z[nx, ny]`
with bilinear interpolation between nodes. `terrain_grid.csv` is the lossless
representation (`repr` floats, exact round trip). `terrain.asc` is ESRI
ASCII-grid compatible: `ncols = nx`, `nrows = ny`, `xllcenter = x0`,
`yllcenter = y0`, `cellsize = spacing`; the first data row is the
**north-most** node row, columns run west → east (tested with the SW=11,
SE=22, NW=33, NE=44 four-corner fixture). The TIN
(`sourceModel = BILINEAR_NODE_GRID`) is a derived planar approximation of the
bilinear patches — two triangles per cell, counter-clockwise from above,
vertices exactly the grid nodes; it is an OPEN surface (`closed = false`,
`watertight = false`) and is never named a "terrain solid".

## Orebody: authority vs derived mesh

`orebody.json` is the membership authority projection (`Orebody.to_dict()`):
type, centre, u/v/w axes, half extents / semi-axes / morphology, bbox,
`volumeM3` + `volumeMethod`, `distanceContract`; WARPED_VEIN keeps its
`shapeModelVersion`, geometry lattice, morphology and clearance metadata. The
meshes are `DERIVED_SURFACE_OF_SOLID` from the same backend-authored mesh
(`Orebody.mesh()`, rule 120/138) for TABULAR, ELLIPSOID and WARPED_VEIN. The
exporter runs the closed-solid QA (finite, valid indices, no degenerate
triangles, edge-manifold, watertight, consistent orientation, positive signed
volume) and refuses the export (`MINE_EXCHANGE_EXPORT_FAILED`) rather than
label a broken mesh `closed = true`.

## Faults

`faults.json` projects the analytic `FaultPlane` parameters (origin, normal,
strike / dip vectors and degrees, half-widths, penalties). `faults.dxf` /
`faults.glb` contain the plane clipped to the field-lattice box as planar
polygons (`FAULT_SURFACE`, `closed = false`). Faults are never volumetric
solids.

## Excavations: two geometries, two meanings

1. **Render surfaces** (`excavations/render/*.glb`, `RENDER_SURFACE`): the
   production `tunnel_mesh.glb` / `development_mesh.glb` bytes copied
   verbatim. `junctionApertures` states whether typed junction apertures are
   opened in those bytes, read from the source junction report (`true` /
   `false` / `null` = unknown, see the coordinate contract). `closed` is the
   source report's `geometricallyClosed` for the ramp; the development render
   mesh has OPEN endpoint policy and is reported `closed = false`.
2. **Individual closed solids** (`excavations/solids/*.stl`,
   `CLOSED_LOGICAL_SWEEP`): the CAP–CAP logical sweep of every RAMP /
   LEVEL_ACCESS / DRIFT / CROSSCUT on its authoritative centerline with the
   scenario profile, built by the **same** production helpers
   (`tunnel_mesh.ramp_logical_sweep`, `development_mesh.closed_sweep`, the
   gravity-aligned profile frame, `build_ring_chain`, `build_logical_mesh`) —
   no second sweep algorithm, no redesign, no search re-run. Each solid passes
   the closed-solid QA (`closed = watertight = manifold = true`,
   `signedVolumeM3 > 0`) or the export fails. Solids **overlap at junctions**
   and are **not** boolean-unioned (`unioned = false`,
   `overlappingAtJunctions = true`).

`mine_multibody.stl` (`EXCAVATION_MULTI_BODY`, `MULTI_BODY_CONCATENATION`) is
the concatenation of every solid's triangles in manifest order with a
per-component `{entityId, firstTriangle, triangleCount}` table. It is a
3D-printing / viewing convenience: `closedComponents = true`, `unioned =
false`, `overlappingAtJunctions = true`, `printabilityGuaranteed = false`,
`engineeringSolidReady = false`. Names such as `excavation.stl`,
`mine_solid.stl` or `watertight_mine.stl` are reserved against — a future
exact Boolean union would be a separate `excavation_union.stl`.

## STL limitations

Binary STL stores unit-less triangle soups: the unit (metre) lives only in the
manifest, the 80-byte header text is informational, and vertices are welded
by consumers, not by the format. Face normals are computed from the triangle
geometry. Coordinates are stored as IEEE float32.

## Centerlines

`centerlines.csv` lists every authoritative polyline point in its persisted
order (`entityId, kind, levelId, sequence, x, y, z`); it is never synthesized
from a mesh. `centerlines.dxf` (AC1009-compatible ASCII, `$INSUNITS = 6`)
holds one 3-D `POLYLINE` per entity on layers `RAMP`, `LEVEL_ACCESS`,
`DRIFT`, `CROSSCUT`, `SHAFT`, `SHAFT_STATION_ACCESS`; identity is kept through
the manifest handle table. The writer is validated by an independent
tag-level parser in the test-suite.

## Network semantics

`topology/network.json` is a MineExchange DTO — not the internal
`network.json`. Nodes: `id, type, position, levelId, surface`; edges: `id,
type, sourceNodeId, targetNodeId, geometryEntityId, geometryContract, length,
orientation, crossSection`. Every physical edge's `geometryRef` is resolved
through the canonical `minegen.network.geometry_refs.resolve_owning_centerline`
**with its edge type** (RAMP → the active ramp owning artifact, LEVEL_ACCESS →
`level_accesses.json`, DRIFT / CROSSCUT → `levels.json`, SHAFT /
SHAFT_STATION_ACCESS → `shafts.json`; non-negative integer index in range;
flat, numeric, finite centerline), then checked to be the ACTIVE ramp
artifact for RAMP edges and an exported centerline entity. Any failure —
wrong owner, out-of-range index, absent owner, malformed geometry, resolved
geometry not exported, a network built over the inactive ramp — is a typed
`MINE_EXCHANGE_EXPORT_FAILED` refusal, never a silent `null`.
`geometryContract = OWNING_CENTERLINE` marks a resolved edge; RAISE, the one
edge type with no owning-centerline contract (rule 184), is exported with
`geometryContract = NONE` and `geometryEntityId = null`, and no geometry is
invented for it. Any other edge type missing from the canonical ownership
table is a typed refusal (fail closed), never an unowned export. Edge direction is the storage / centerline direction
(`directionSemantics` explains this); it does **not** mean one-way traffic
and no traffic semantics are exported because none exist in the authority.
The CSVs are convenience tables; JSON is the semantic authority.

## Capability semantics

`semantics/capability.json` projects a **SUCCESS** capability graph: capability list,
per-edge typed may / may-not tags with their `source`, node `supports`,
surface node ids, required paths with **both** `physicalReachable` and
`capabilityReachable` (never conflated) and `satisfied`, the egress advisory
(`advisoryOnly = true`, explicitly a design advisory — never a statutory or
regulatory compliance determination) and the build-time validation summary.
Capability ≠ capacity: no tonnes / hour, people / hour or airflow. A present
but FAILED capability graph yields no `capability.json` and an omission
`CAPABILITY / SOURCE_NOT_SUCCESS` (status + failure reason in `detail`);
STALE / MALFORMED graphs are typed refusals as everywhere else.

Geometry ≠ topology ≠ capability: a DXF polyline does not mean connected, a
network edge does not mean personnel-capable, a capability does not mean a
legal certification.

## Mining method and production stopes (1.1, Phase 21A)

`semantics/mining_method.json` (`MINING_METHOD`, always present) projects the
scenario's **requested** method and what this MineGen version implements for
it, resolved through the ONE backend mining-method registry
(`mining/methods/registry.py::plan_for`, CLAUDE.md rule 192):

    requestedMethod          scenario.mining.method (configuration authority)
    displayName              registry presentation name
    implementationStatus     IMPLEMENTED | UNSUPPORTED_METHOD (registry authority)
    parameters               { sublevelInterval, stopeLength, minimumPillar }
    productionDevelopment    { status IMPLEMENTED | UNSUPPORTED_METHOD | NOT_GENERATED, reason,
                               sourceArtifact levels.json, sourceRevision, entityIds[] = CROSSCUT entities }
    production               { status SUCCESS | FAILED | NOT_GENERATED, failureReason,
                               sourceArtifact stopes.json, sourceRevision, stopeCount, entityIds[] = STOPE entities }

It references the exported CROSSCUT / STOPE entities and duplicates no
geometry. Three authorities must agree or the export is a typed
`409 MINE_EXCHANGE_EXPORT_FAILED` (`builder.py::check_method_authority`):
the scenario's requested method, `levels.json → productionDevelopment.method
/ status` (against the registry's implementation status) and `stopes.json →
method`; a SUCCESS `stopes.json` under a method the registry does not
implement is refused — longhole geometry is never exported under another
method's name. An unsupported method (CUT_AND_FILL, ROOM_AND_PILLAR,
SUBLEVEL_CAVING, SHRINKAGE_STOPING) exports `implementationStatus =
UNSUPPORTED_METHOD`, `productionDevelopment.status = UNSUPPORTED_METHOD`
with the builder's reason, no CROSSCUT entities, a FAILED `production`
block and a `STOPES / SOURCE_NOT_SUCCESS` omission carrying the typed
`UNSUPPORTED_METHOD: …` failure reason — a feature boundary, never a mine
failure and never a fallback.

`production/stopes.json` (`PRODUCTION_STOPES`) and the per-stope files
(`STOPE_SOLID`, `AUTHORITATIVE_CLOSED_MESH`) project a **SUCCESS**
`stopes.json`: one `STOPE` entity per planned stope in **sorted stope-id
order** (never list order), with the artifact's own 8-vertex / 12-triangle
prism written to STL, OBJ and an exporter-created GLB (glTF Y-up root
matrix, like the orebody). The geometry is the authority's — never
re-derived, never moved, never unioned (`unioned = false`; vertically
adjacent stopes share a boundary face by construction) — and every body is
QA'd INDEPENDENTLY: finite, valid indices, non-degenerate, edge-manifold,
watertight, outward, positive signed volume agreeing with the artifact's
`geometricVolumeM3` within 1e-6 relative, exactly 8 / 12, unique ids. A
defect is a typed refusal, never trusted from the source report. The stope
DTO rows carry identity (`entityId`, `stopeId`, `method`, `stationIndex`,
`stationU`, level pair), the two MineNetwork `STOPE_ACCESS` node ids (the
link to the network — a stope is a production VOLUME, never a network edge),
local bounds, dimensions and the planning quantities `geometricVolumeM3`,
`tonnes`, `meanGradeProxy` — deterministic planning numbers, never reserves
or resources. Stopes export **without** a network (world + levels + stopes
is a valid partial bundle); when the network IS present, both access node
ids must be exported nodes or the export is refused. Multi-body / unioned
stope files and the future kinds `DRAWPOINT`, `PILLAR`, `BACKFILL_VOLUME`,
`ROOM`, `CUT`, `BENCH` are NOT emitted in 1.1.

## Determinism and integrity

The same authoritative snapshot yields the same bytes: lexicographic entry
order, fixed entry timestamp (1980-01-01), fixed DEFLATE settings, relative
normalized paths under `mine_exchange/`, no absolute path, no UUID, no
wall-clock value in the manifest (the generation time is only the
non-authoritative `X-MineExchange-Generated-At` header). Every listed file
carries its SHA-256; the manifest lists every payload file (the manifest is
not self-listed) and nothing unlisted is packed.

## Snapshot consistency

The service takes ONE validated snapshot of every source (scenario, arrays,
ramp source, both ramp owners, level accesses, levels, shafts, network,
capability graph, stopes (1.1), tunnel / development reports and GLB bytes), checks the
world binding against it, builds the bundle, then re-snapshots and refuses
with `READ_SNAPSHOT_CHANGED` if any revision or presence changed meanwhile.
A bundle never mixes revisions.

## Frontend

The Scenario panel's "Export MineExchange (.zip)" button downloads the bundle
of the currently available state; a world is the only prerequisite and the
button is never disabled because a design layer is missing. Beneath it,
"Current export contents" (`components/panels/exportContents.ts`) lists each
layer as included / not generated / failed, read from the already-loaded
scene snapshot only — no generation endpoint is called and nothing is
inferred — including, since 1.1, the always-included "Mining method" row and
the "Stopes" row (`scene.stopes` status) — with the helper text "MineExchange exports the currently available
mine state. Layers not yet generated are omitted and recorded in the
manifest." The manifest remains the authority on the bundle's content.

## Exclusions in v1 (`NOT_IN_V1` / non-scope)

Grade / rock quality lattices (never a block model), GeoTIFF / real CRS /
`.prj`, a terrain-closed `model_block.stl`, Boolean unions (including a
unioned or multi-body stope file), timeline / production scheduling /
economics, drawpoint / pillar / backfill / room / cut / bench entities (the
Phase 21B / 21C methods that own them are not implemented), application
adapters (Phase 23B), import and write-back. Stopes and the mining-method
semantics were NOT_IN_V1 in 1.0 and are part of the bundle since 1.1.

## Versioning policy

- 1.x: additive files, fields, omission groups and entity kinds only;
  existing meanings, ids and coordinate contract unchanged. 1.1 declared
  `STOPE`; the remaining reserved future entity kinds (PRODUCTION_DRIFT,
  DRAWPOINT, PILLAR, BACKFILL_VOLUME, ROOM, CUT, BENCH) are documented here,
  not pre-declared in the enum.
- 2.0: any change to the coordinate contract, entity identity rule or the
  meaning of an existing manifest field.
