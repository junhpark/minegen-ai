# External adapters — architecture, contract and gap analysis (Phase 23B.0)

Status: **architecture decision / gap analysis**. Phase 23B.0 implements no
adapter, no framework, no MineExchange change and no production code. It
fixes the boundary every later adapter (23B.1 …) is built on and records,
per target application, what MineExchange 1.2 already provides, what is
missing and which authority owns the gap.

Baseline: `main` `4321babcce423d89a608ce4dc553fb71705d4a54` (after PR #49,
Phase 22C). MineExchange contract: `docs/mine-exchange.md` (1.2.0, rule 190).

## 1. Purpose

Connect MineGen's authoritative state to external engineering / simulation
applications — first Ventsim (ventilation), AnyLogic (operations /
material-flow simulation) and Unity / Unreal (runtime visualization),
later CAD / mine-planning tools, GIS and other engines — through ONE adapter
architecture, without any of them reading MineGen's internal artifacts and
without any of them redesigning the mine.

The question this phase answers:

> What does MineExchange 1.2 already give each application, what is missing,
> and which authority is responsible for each missing piece?

## 2. Architecture boundary

External applications never read `derived/*`. The only external
interoperability boundary is MineExchange.

    MineGen authoritative state
            ↓  validated coherent snapshot (READ_SNAPSHOT_CHANGED on drift)
        MineExchange bundle  (canonical, application-neutral, versioned)
            ↓
        External adapter     (translator)
            ↓
        Application-specific package (disposable projection)

    MineGen
       ↓
    MineExchange
       ├── Ventsim adapter
       ├── AnyLogic adapter
       └── Unity / Unreal adapter

Forbidden shapes:

    VentsimAdapter  → derived/network.json        (internal artifact read)
    AnyLogicAdapter → derived/timeline.json       (internal artifact read)
    Adapter         → ScenarioStore / ArtifactReader / DesignService

An adapter's only MineGen input is a MineExchange bundle (§5). If a target
needs something the bundle does not carry, the fix is a MineExchange minor
version (additive), never a side channel into `derived/`.

## 3. Authority model

An adapter is a **translator**, not a planner. Every number an adapter
emits is either (a) copied from the bundle, (b) a declared, provenance-
tracked conversion of a bundle value, or (c) an explicit adapter parameter
supplied by the user and labelled as such.

| An adapter must NEVER | An adapter MAY |
| --- | --- |
| redesign geometry, reroute development, re-rank layouts, select candidates | transform coordinates (declared source frame → declared target frame) |
| invent production quantities, invent a schedule, infer development order from topology | map fields and identifiers (bundle ids → target ids, with a mapping table) |
| infer airflow, size fans, invent a truck fleet, optimize haulage | convert formats (DXF / CSV / GLB / JSON → the target's interchange format) and units |
| infer material properties, change the mining method | package application-specific structure (layers, tables, prefabs) |
| fill a required target field with a silent engineering default | consume explicit, user-supplied adapter parameters (§7) |

Every conversion is provenance-tracked: the adapter output names the bundle
file, entity id and MineExchange version each generated element came from.

## 4. Adapter input / output contract (conceptual — no code in 23B.0)

    AdapterInput
      mineExchangeVersion     manifest.mineExchangeVersion (semver)
      manifest                manifest.json (meaning authority of the bundle)
      files                   the bundle files, addressed through manifest.files[] / entities[].files
      omissions               manifest.omissions[] (ARTIFACT_ABSENT / SOURCE_NOT_SUCCESS / NOT_IN_V1)
      provenance              manifest.sourceSnapshot (scenarioRevision, arraysRevision,
                              activeRampSource, artifactRevisions)
      adapterParameters       explicit user-supplied values (§7), never defaults hidden in code

    AdapterOutput
      targetApplication       e.g. VENTSIM | ANYLOGIC | UNITY | UNREAL
      adapterName, adapterVersion, supportedMineExchangeVersions   (§9)
      sourceMineExchangeVersion, sourceSnapshot (copied from the manifest)
      generatedFiles[]        { path, mediaType, targetSemantic, sourceEntityIds[], sourceFiles[], sha256 }
      identityMap[]           { bundleEntityId | bundleNodeId | bundleEdgeId → targetId }
      coordinateMapping       { sourceFrame LOCAL_ENU_Z_UP, targetFrame, transform, unitFactor }
      sourceStates[]          per source group: AVAILABLE | ABSENT | SOURCE_NOT_SUCCESS | UNSUPPORTED_BY_ADAPTER (§6)
      assumptions[]           § 7 records (kind, key, value, unit, scope, source, userOverride)
      warnings[]
      omissions[]             what the adapter did not emit and why (typed, §6)

The adapter reads the bundle by manifest — `entities[].files`,
`files[].sourceEntityIds`, `files[].dxfEntities` — never by reconstructing a
file stem (the stem hash prefix is not injective; `docs/mine-exchange.md`,
"Stable entity identity").

## 5. MineExchange 1.2 as the stable boundary — inventory

What the bundle carries today (from `docs/mine-exchange.md`, verified
against `backend/src/minegen/exchange/models.py`):

| Group | Files | Authority / representation | Notes for adapters |
| --- | --- | --- | --- |
| Manifest | `manifest.json` | meaning authority: version, coordinate contract, `sourceSnapshot`, `entities[]`, `files[]`, `omissions[]` | the ONLY place to learn frames, ids and what is missing |
| Terrain | `terrain/terrain_grid.csv` (authority), `terrain.asc`, `terrain_surface.{stl,obj,glb}` | node grid + derived OPEN TIN | surface context, portal / collar elevation |
| Orebody | `orebody/orebody.json` (authority), `orebody.{stl,obj,glb}` | solid parameters + derived closed mesh (QA'd) | context only for Ventsim / AnyLogic; a visual body for engines |
| Faults | `geology/faults.json`, `faults.{dxf,glb}` | plane parameters + clipped planar polygons | context only |
| Excavation entities | `excavations/entities.json` | id, kind (RAMP segments, LEVEL_ACCESS, DRIFT pieces, CROSSCUT, SHAFT_SEGMENT, SHAFT_STATION_ACCESS), levelId, parents, `ownsGeometry` | the identity table |
| Centerlines | `excavations/centerlines.csv` (entityId, kind, levelId, sequence, x, y, z), `centerlines.dxf` (one 3-D POLYLINE per entity, layer = kind, `$INSUNITS = 6`, handle → entityId in the manifest) | authoritative polylines, 2 m sampling on layout-v2 geometry | the Ventsim seed input |
| Excavation solids | `excavations/solids/<entity>.stl` (closed sweeps, not unioned), `mine_multibody.stl` | per-excavation closed logical sweep | engines (collision / CAD); not a Boolean union |
| Render surfaces | `excavations/render/tunnel.glb`, `development.glb` | production render meshes copied verbatim, `LOCAL_ENU_Z_UP` stored vertices, `transformMatrix = null`, per-primitive `name` / `extras` (segment ids, piece ranges, ring reveal metadata), `junctionApertures` outcome flag | engines (visual) |
| Topology | `topology/network.json` (authority), `nodes.csv`, `edges.csv` | nodes `{id, type, position, levelId, surface}`; edges `{id, type, sourceNodeId, targetNodeId, geometryEntityId, geometryContract, length, orientation, crossSection{width, height, shape}}`; edge direction = storage direction, NOT traffic | the Ventsim airway graph and the AnyLogic route graph |
| Capability | `semantics/capability.json` | per-edge typed may / may-not tags with `source`, node `supports`, required paths (`physicalReachable` AND `capabilityReachable`), egress advisory (`advisoryOnly = true`) | access-restriction candidates; capability ≠ capacity |
| Mining method | `semantics/mining_method.json` (always present) | requested method, registry status, typed parameters, production status | operation semantics (metadata) |
| Production | `production/stopes.json` + `stopes/<stope>.{stl,obj,glb}` (Longhole); `production/cut_fill.json` + `cut_fill/cuts/*` + BACKFILL semantic entities (Cut & Fill); `production/room_pillar.json` + `room_pillar/{benches,pillars}/*` (Room & Pillar) | authoritative closed prisms, planning quantities (`geometricVolumeM3`, `tonnes`, `meanGradeProxy`), `STOPE_ACCESS` node links (Longhole), `accessEntityId` (Cut & Fill), room ↔ unit membership | source / destination candidates for AnyLogic; mesh actors for engines |
| Omissions | `manifest.omissions[]` | `ARTIFACT_ABSENT`, `SOURCE_NOT_SUCCESS` (with detail), `NOT_IN_V1` (timeline, field lattice) | the adapter's four-state input (§6) |

Coordinate authority (the ONLY external coordinate contract):

    coordinateSystem.name  LOCAL_ENU_Z_UP
    X = East, Y = North, Z = Up, metre, right-handed
    crs = LOCAL_SYNTHETIC (no EPSG, no UTM zone, no .prj)

STL / OBJ / DXF / CSV store canonical coordinates verbatim. Exporter-created
GLBs store `LOCAL_ENU_Z_UP` vertices under a glTF Y-up **root node matrix**
(`(x, y, z) → (x, z, −y)`, recorded as `glb.transformMatrix`); the copied
production render GLBs store `LOCAL_ENU_Z_UP` with `transformMatrix = null`.
An adapter reads `glb.storedVertexFrame` / `glb.sceneFrame` /
`glb.transformMatrix` from the manifest; it never guesses MineGen's internal
Three.js convention.

Not in the bundle (1.2): the timeline / schedule (`NOT_IN_V1`), the field
lattice, economics, a Boolean union of excavations, any operational or
physical property (roughness, resistance, fans, fleet, speeds).

## 6. Four-state source mapping rule

An adapter never flattens source availability. Every bundle group it
consumes is reported in exactly one of four states:

| State | Meaning | Who decides |
| --- | --- | --- |
| `AVAILABLE` | the bundle carries the source and the adapter mapped it | bundle + adapter |
| `ABSENT` | `manifest.omissions[]` says `ARTIFACT_ABSENT` (never generated) | MineGen / bundle |
| `SOURCE_NOT_SUCCESS` | the source exists but its status is FAILED (`omissions[].detail`) | MineGen / bundle |
| `UNSUPPORTED_BY_ADAPTER` | the bundle carries it, this adapter version has no mapping for it | adapter |

Example: no shaft in the mine → `SHAFT = ABSENT`. A shaft in the bundle but
a Ventsim adapter version without a vertical-airway mapping →
`SHAFT = UNSUPPORTED_BY_ADAPTER`. The two are different facts and are
reported differently; `NOT_IN_V1` groups (timeline) are `ABSENT` at the
bundle level with the bundle's own reason code carried through.

## 7. Assumption policy

Values a target application requires but no MineGen authority owns —
airway roughness / friction factor, fan curves, regulator resistance, door
leakage, heat load, diesel emission, vehicle speed, loading / dumping time,
vehicle capacity, traffic priority, material densities beyond the scenario
density, engine materials — are **never guessed**. Each such value is in one
of three states, recorded in `AdapterOutput.assumptions[]`:

| State | Meaning |
| --- | --- |
| `NOT_PROVIDED` | left empty in the target package; the target application's own default or the user fills it there |
| `USER_REQUIRED` | the adapter refuses to emit the element until the user supplies the value (`REQUIRED_PARAMETER_MISSING`, §8) |
| `ADAPTER_DEFAULT_EXPLICIT` | a documented adapter default was applied — recorded with `source` (adapter version + documented table), `value`, `unit`, `scope` (which entities), and `userOverride` (whether / how the user changed it) |

A silent default — a number written into the target package that is not in
the bundle and not in `assumptions[]` — is a defect. `ADAPTER_DEFAULT_EXPLICIT`
is an allowance for later phases (e.g. an airway profile default for the
Ventsim seed); 23B.0 permits it only under the five recorded fields.

## 8. Failure model (contract candidates — no enum, no code in 23B.0)

| Code | When |
| --- | --- |
| `MINEEXCHANGE_VERSION_UNSUPPORTED` | `manifest.mineExchangeVersion` outside `supportedMineExchangeVersions` |
| `REQUIRED_SOURCE_ABSENT` | a group the adapter needs is `ABSENT` / `SOURCE_NOT_SUCCESS` (the omission reason is carried through) |
| `REQUIRED_PARAMETER_MISSING` | a `USER_REQUIRED` assumption was not supplied |
| `TARGET_FORMAT_UNSUPPORTED` | the requested target format / version is not produced by this adapter version |
| `COORDINATE_MAPPING_UNSUPPORTED` | the requested target frame / unit / offset cannot be expressed (e.g. a real CRS requested from `LOCAL_SYNTHETIC`) |
| `ADAPTER_CONVERSION_FAILED` | a conversion defect the adapter detected (duplicate target id, dangling reference, non-finite value) |

One generic failure covering every case is not acceptable; each failure
names the bundle group, entity or parameter concerned.

## 9. Versioning

    adapterName                   VENTSIM | ANYLOGIC | UNITY | UNREAL | …
    adapterVersion                semver of the adapter itself
    supportedMineExchangeVersions e.g. ">=1.2,<2"

Example: `VENTSIM 0.1.0`, `MineExchange >=1.2,<2`. The adapter version and
the MineExchange version are never identified with each other: a bundle
minor version that adds files does not change an adapter that ignores them;
an adapter change never bumps MineExchange.

## 10. Coordinate policy

- Source frame is always the manifest's `LOCAL_ENU_Z_UP` (metre,
  right-handed, Z up). The adapter declares the target frame and the exact
  transform in `coordinateMapping`.
- Ventsim: DXF is imported in the Ventsim file's current units and
  coordinates (vendor manual, §11) — the adapter emits metres and the
  adapter package README states "metric, local synthetic origin"; an
  optional user offset is an explicit parameter, never a hidden re-basing.
- AnyLogic: space-markup coordinates are model-local; the mapping (metre →
  model unit, axis orientation of the 2-D / 3-D canvas) is an explicit
  adapter parameter pair (scale, axis map) recorded in the output.
- Unity / Unreal: glTF is Y-up right-handed metre; both engines convert on
  import (Unity: left-handed, one axis mirrored by the importer; Unreal:
  Z-up left-handed centimetre, converted by the glTF importer). The adapter
  emits the frame the engine importer expects and records which of the two
  MineExchange GLB kinds (exporter-created Y-up root matrix vs copied
  `LOCAL_ENU_Z_UP` render GLB) was used per file.
- Nothing in 23B changes the bundle's coordinate contract (a 2.0 change).

## 11. Target A — Ventsim (ventilation)

### 11.1 Vendor facts (official sources, §21)

- Ventsim DESIGN imports CAD line-string graphics from DXF, DWG and DGN
  files; "Centrelines can be converted to airways during the import
  function, or later on by selectively clicking or fencing the centrelines
  with the Add > Convert function"; the import can alternatively load the
  centrelines as a graphical reference only. (Ventsim DESIGN User Guide,
  Import section.)
- Convert Centrelines can inherit Primary / Secondary layers from the
  reference graphics (Ventsim update logs 5.4 / 6.0).
- Imported files carry no reliable unit flag: "Ventsim will assume the
  coordinates are the same as currently used in the Ventsim file" — a
  mismatch displaces the data. (User Guide.)
- DXF export from Ventsim loses ventilation attributes and cannot be
  re-imported as a ventilation model (User Guide) — the DXF path is a
  geometry path, not a ventilation-model path.
- Automation: the manual documents "Ventsim Static Scripting" (Appendix H)
  for running simulation scenarios automatically; no public model-
  construction API / SDK is documented in the sources reachable here.
- Native model files (`.vsm` and predecessors) are proprietary and
  undocumented — out of scope by rule (§2, §21): no reverse engineering.
- Current official release: Ventsim DESIGN 6.0.4.9 (2026-01-01), preview
  6.0.5.0 (vendor download page).
- NOT confirmed from official sources in this phase: a documented text /
  CSV *airway* import with coordinate columns (only text strings inside
  DXF / DWG / DGN and the spreadsheet tool's CSV *export* are documented in
  the snippets read). Treated as **UNVERIFIED**, to be checked in the
  manual's Import chapter before 23B.1 relies on it.

### 11.2 Mapping matrix

States: `DIRECT`, `DERIVABLE_WITHOUT_ENGINEERING_ASSUMPTION`,
`REQUIRES_EXPLICIT_ASSUMPTION`, `MISSING`, `NOT_RELEVANT`.

| MineGen / MineExchange | Ventsim concept | State | Notes |
| --- | --- | --- | --- |
| RAMP centerline (`ramp:main:<seg>`, DXF layer `RAMP`) | airway (chain) | DIRECT | 3-D polyline; Ventsim builds a chain of airways at the vertices; 2 m sampling of a spiral yields many short airways (§11.4 Q1) |
| LEVEL_ACCESS centerline | airway | DIRECT | welded to the ramp within 1e-6 m in the authority, so DXF endpoints coincide |
| DRIFT pieces | airway | DIRECT | |
| CROSSCUT | airway (dead end at the face) | DIRECT | face end is a terminal node |
| SHAFT axis segments (layer `SHAFT`) | vertical airway | DIRECT | vertical polyline; the shaft aggregate owns no solid — only the axis |
| SHAFT_STATION_ACCESS | airway | DIRECT | |
| network junction (`topology/network.json` nodes) | airway junction | DERIVABLE_WITHOUT_ENGINEERING_ASSUMPTION | node ids / positions exist; the DXF chain nodes at the same positions must be reconciled with the topology nodes (identity map) |
| tunnel width / height (`edges[].crossSection {width, height, shape}`) | airway dimensions | DERIVABLE_WITHOUT_ENGINEERING_ASSUMPTION for the values; REQUIRES_EXPLICIT_ASSUMPTION for the *delivery path* | the numbers are in the bundle; DXF cannot carry them, so they reach Ventsim through an airway attribute table applied after conversion (spreadsheet / edit) or a documented profile preset — the path is an adapter config choice |
| centerline DXF (`excavations/centerlines.dxf`) | CAD import → Convert Centrelines | DIRECT | official path; layer = kind maps to a Ventsim layer |
| edge length (`edges[].length`) | airway length | DIRECT (cross-check) | Ventsim computes length from geometry; the bundle value is the check |
| capability graph | — | NOT_RELEVANT | no ventilation semantics; may annotate airway names only |
| mining method | metadata only | NOT_RELEVANT | naming / grouping |
| terrain, orebody, faults | reference graphics | DIRECT (optional) | context layers only |
| ventilation resistance / friction factor | airway resistance | MISSING | no MineGen authority (gap class C) |
| fan | fan | MISSING | class C |
| regulator / door | regulator | MISSING | class C |
| heat sources, diesel, gas | heat / contaminant input | MISSING | class C |
| air density, surface conditions | model settings | MISSING | class C |
| timeline (development over time) | staged model | MISSING in 1.2 | class A — MineGen owns it, MineExchange does not expose it (§14) |

### 11.3 First-adapter decision

> Can MineExchange 1.2 alone produce a useful Ventsim geometry / network
> seed model?

**Answer: `YES_WITH_EXPLICIT_ADAPTER_CONFIG`.**

Grounds:

1. Every development the mine has (ramp, level accesses, drifts, crosscuts,
   shaft axes, station drives) is in the bundle as an authoritative 3-D
   polyline with kind-named DXF layers, and the vendor documents exactly
   that import path (DXF → Convert Centrelines → airways).
2. Junction connectivity is guaranteed by the authority (welded
   centerlines), so the converted airways connect without adapter
   engineering.
3. Airway dimensions exist per edge in the bundle; nothing has to be
   invented. What is *not* free is the delivery of those dimensions into
   Ventsim (DXF carries geometry only), the unit / origin declaration and
   the polyline-simplification tolerance — all explicit adapter
   configuration, none an engineering assumption.
4. Everything ventilation-specific (resistance, fans, regulators, heat) is
   correctly `MISSING` and stays `NOT_PROVIDED` / `USER_REQUIRED` in the
   seed; the seed is the start of a ventilation model, not a ventilation
   model.

Expected 23B.1 architecture (to be confirmed by 23B.1 design):

    MineExchange 1.2
          ↓
    Ventsim seed adapter
          ├── DXF: centerline polylines, layer = kind (+ optional reference layers)
          ├── airway attribute table (entityId, kind, edge id, node ids, length,
          │   width, height, shape) — for post-conversion assignment
          ├── identity map (DXF handle / entity id ↔ network edge / node ids)
          └── adapter config + assumption record (units, origin offset,
              simplification tolerance, dimension delivery policy)

23B.1 scope is deliberately **the seed** — "make MineGen's development
topology usable as the starting point of a Ventsim airway model" — not a
finished ventilation model.

### 11.4 Open questions for 23B.1 (not blocking 23B.0)

- Q1 Representation: polyline-faithful (each 2 m vertex → a Ventsim node;
  hundreds of airways on a spiral) vs edge-straight (one straight airway per
  MineNetwork edge, true length as an attribute) vs simplified polyline split
  only at topology nodes (tolerance an explicit parameter). Recommended
  default to evaluate first: simplified polyline, split only at network
  nodes, tolerance recorded as `ADAPTER_DEFAULT_EXPLICIT`.
- Q2 Whether a documented text / spreadsheet airway import exists in the
  current manual (UNVERIFIED, §11.1); if not, dimensions are applied through
  Ventsim's spreadsheet tool by the user, guided by the attribute table.
- Q3 Whether Ventsim's Convert step preserves the DXF layer as the airway
  layer / type in the current version (update logs say layers can be
  inherited; confirm on 6.0.x).
- Q4 Testing without a Ventsim licence: DXF is verifiable with the existing
  tag-level parser; Convert behaviour needs a manual acceptance on a real
  installation (recorded as a 23B.1 acceptance step, not a unit test).

## 12. Target B — AnyLogic (operations simulation)

### 12.1 Vendor facts (official sources, §21)

- Every AnyLogic model has a built-in database; data can be imported from
  MS Excel (`.xlsx`), MS Access (`.accdb`), MS SQL Server and, through
  JDBC / ODBC, other databases (e.g. PostgreSQL); "Update data on the model
  startup" refreshes from the source. (AnyLogic Help, "AnyLogic database",
  "Importing database tables".)
- Connectivity palette: "Text File" element (Read / Write / Write-Append,
  configurable separators — CSV reading; demo "Reading Agent Parameters from
  a CSV File") and "Excel File" element (`.xls` / `.xlsx`, `readFile()`,
  "Load on model startup"). (AnyLogic Help, "Text file", "Excel file".)
- Networks can be created programmatically ("Create network by code"):
  nodes (`PointNode`, `RectangularNode`) and paths built from
  `MarkupSegmentLine` segments taking X, Y, Z start / end coordinates,
  connected with `setSource()` / `createPort()`, returning a `Level`; only
  at model startup, not modifiable afterwards. (AnyLogic Help.)
- GIS: shapefiles can be converted to road / rail space markup on a GIS
  map ("Convert Shapefile to Space Markup"); GIS routes need real
  coordinates. (AnyLogic Help, "Converting GIS shapefiles to a road
  network".) MineExchange is `LOCAL_SYNTHETIC` (no CRS) — the GIS path is
  not applicable; the non-GIS network-by-code path is.
- Results: database tables export to Excel from the UI ("Export to Excel",
  "Export to Excel after simulation run") and programmatically
  (`exportToExternalDB()`). (AnyLogic Help, "Exporting data to MS Excel
  file".) Relevant only to the future result-import phase (§17).

### 12.2 Mapping matrix

| MineGen authority | AnyLogic use | State | Notes |
| --- | --- | --- | --- |
| MineNetwork nodes (`nodes.csv` / `network.json`) | route nodes (`PointNode` …) | DIRECT | id, type, x / y / z, levelId, surface flag |
| MineNetwork edges (`edges.csv`) | movement links (`Path`, `MarkupSegmentLine`) | DIRECT | node pair; shape from the owning centerline entity if a faithful path is wanted |
| edge length | travel distance | DIRECT | `edges[].length` (3-D) |
| edge kind (RAMP / LEVEL_ACCESS / DRIFT / CROSSCUT / SHAFT / SHAFT_STATION_ACCESS) | route classification | DIRECT | |
| edge orientation / gradient | ramp vs level classification | DIRECT (orientation); gradient DERIVABLE from the centerline | no traffic direction is exported (storage direction only) |
| capability (`capability.json`) | vehicle / access restriction candidate | DERIVABLE_WITHOUT_ENGINEERING_ASSUMPTION | typed may / may-not tags per edge; capability ≠ capacity — no flow rate is implied |
| mining method (`mining_method.json`) | operation semantics | DIRECT (metadata) | |
| production entities (stopes / cuts / benches; STOPE_ACCESS nodes, `accessEntityId`) | source / destination candidates | DIRECT | linked to network nodes / crosscut entities |
| planned tonnes (`tonnes` per production unit) | material-flow quantity | DIRECT (planning quantity) | never a forecast; retained pillars / backfill are separate records, not production |
| timeline tasks | operation events | MISSING in 1.2 (`NOT_IN_V1`) | gap class A — see §13 |
| development completion over time | network availability over time | MISSING in 1.2 | class A — derived from timeline development progress, which the timeline authority owns |
| production order / unit state transitions | stoping sequence events | MISSING in 1.2 | class A (`timeline.json` `production.units[].transitions`) |
| vehicle fleet (types, count) | agents | MISSING | class C (simulation input) |
| vehicle speed (by grade / kind) | agent parameter | MISSING | class C |
| loading / dumping time | process parameter | MISSING | class C |
| dispatch logic, priorities, shift calendar | model logic | MISSING | class C / D (model design) |
| dump / stockpile / crusher locations | destinations | MISSING | class B (no MineGen authority for surface infrastructure) |
| tunnel width / height | vehicle clearance / passing rules | DERIVABLE | `crossSection` exists; passing semantics are model logic (C) |

### 12.3 Mine­Exchange 1.3 decision gate

> Is MineExchange 1.3 — Operational / Timeline Semantics — required before
> an AnyLogic adapter?

**Decision: `REQUIRED` for the 23B.2 scope as directed** (network +
production + schedule → LHD / truck / material-flow / congestion
simulation). Without the timeline, an AnyLogic package can only model a
static final-layout network with static production sources; development
availability over time and the production sequence — the parts that make
the simulation operational rather than geometric — are exactly the
`NOT_IN_V1` group. `OPTIONAL` would hold only for a reduced "static-network
haulage" scope, which is not what 23B.2 is defined as.

Minimum candidate contract (a 1.3 **design requirement**, not a schema):

    operations/timeline.json     summary: startDay, endDay, task counts, method, targetKind
    operations/tasks.csv         taskId, taskType, targetKind, targetId (bundle entity / edge id),
                                 startDay, endDay, durationDays, dependencies,
                                 basisQuantity, basisUnit, basisRate, rateUnit, miningMethod
    operations/development_progress.json   per development: excavationStartNode, progressDirection,
                                 pointChainageFractions (owning centerline order), state transitions
    operations/production_states.json      per production unit: initialState, transitions[{day, state}]

Every id is a bundle id (network edge id, production entity id), never an
internal artifact id; the exporter resolves them the way it resolves
`geometryEntityId` today. Additive minor version (1.3.0), `NOT_IN_V1`
reason code retired for the timeline group. This list is recorded for the
1.3 design phase only; nothing is implemented in 23B.0.

### 12.4 Timeline authority rule

Even with 1.3 the adapter never reconstructs temporal semantics:

    forbidden   production geometry → adapter guesses production order
                network topology   → adapter guesses development schedule
    correct     MineTimeline authority → MineExchange timeline semantics → AnyLogic adapter

`state(day)` keeps the exact-boundary rule of the authority (CLAUDE.md rule
84); the adapter copies transitions, it does not re-evaluate them.

### 12.5 Recommended 23B.2 scope (after 1.3)

Network tables (nodes / edges / kinds / lengths / cross-sections), production
unit tables (id, tonnes, access node), timeline task and state tables — as
CSV / XLSX for the built-in database or the Text / Excel File elements —
plus a documented network-by-code recipe. The AnyLogic model itself (agents,
dispatch, speeds, fleet) is user model logic, never generated by the
adapter.

## 13. Target C — Unity / Unreal (runtime visualization)

### 13.1 Vendor facts (official sources, §21)

- Unity: glTF / GLB import through the Unity glTFast package
  (`com.unity.cloud.gltfast`, 6.x), Editor and runtime import, glTF 2.0 and
  many extensions; node `extras` are supported (Newtonsoft JSON, Add-on
  API use case "custom extras"). Unity also imports `.fbx`, `.obj`, `.dae`,
  `.3ds`, `.dxf` natively (Unity Manual, "Model file formats"). STL is not
  a native Unity format. Unity is left-handed; glTF importers mirror one
  axis on import (UnityGLTF documents an X mirror; the exact policy is the
  chosen importer's).
- Unreal Engine 5: glTF / GLB import through the Interchange framework
  ("Import Into Level" supports glTF / GLB; FBX under Interchange was
  experimental at 5.3; the legacy importer covers FBX / OBJ). Unreal is
  Z-up, left-handed, centimetre; the glTF importer performs the conversion.
  Datasmith carries per-object metadata ("Using Datasmith Metadata");
  whether the Interchange glTF path exposes node `extras` as metadata is
  **UNVERIFIED** here — the identity mapping must not depend on it (§13.3).

### 13.2 Mapping matrix

| MineExchange | Engine concept | State | Notes |
| --- | --- | --- | --- |
| tunnel GLB (`excavations/render/tunnel.glb`) | static mesh | DIRECT | copied production bytes, `LOCAL_ENU_Z_UP` stored, `transformMatrix = null` → the adapter applies the mine → glTF rotation or emits a re-based GLB (explicit) |
| development GLB | static mesh | DIRECT | OPEN endpoint policy at junctions; typed apertures per `junctionApertures` |
| per-excavation STL solids | collision / CAD mesh | DIRECT (Unity: via conversion; STL not native) / DERIVABLE | closed, not unioned; overlaps at junctions |
| orebody / terrain / faults GLB | static mesh | DIRECT | exporter-created, Y-up root matrix declared |
| production solids (stope / cut / bench / pillar GLB) | mesh actors | DIRECT | one closed prism each, ids in the manifest |
| entity ids (`entities[]`, GLB primitive `name` / `extras`) | actor / GameObject metadata | DERIVABLE_WITHOUT_ENGINEERING_ASSUMPTION | the manifest is the identity authority; `extras` availability differs per importer (§13.3) |
| MineNetwork | navigation / logical graph | DIRECT (data) / REQUIRES_EXPLICIT_ASSUMPTION (navmesh use) | nodes / edges import as data; turning it into a NavMesh or spline set is engine-side design |
| coordinate metadata (`coordinateSystem`, `glb.*`) | transform | DIRECT | declared per file |
| capability | interaction metadata | DIRECT (data) | may / may-not tags for gating interactions; never a physical simulation |
| timeline | animation / state | MISSING in 1.2 | class A (§12.3); the 4D reveal metadata in the render GLB `extras` (ring chainage fractions) is present but useless without the schedule |
| material semantics (rock, backfill, ore) | engine materials | REQUIRES_EXPLICIT_ASSUMPTION | the bundle names kinds, not materials; an explicit material table is an adapter parameter (`ADAPTER_DEFAULT_EXPLICIT`) |
| simulation results (airflow, vehicles) | overlays | NOT IN CURRENT SCOPE | class E (§17) |

### 13.3 Three different things

    visual geometry import  ≠  mine semantics import  ≠  runtime simulation

A GLB that opens in the engine proves only the first. Semantics require the
manifest → actor identity map (entity id, kind, level, network node / edge
ids, capability tags) carried by the adapter package as its own table,
so it works whether or not an importer preserves `extras`. Runtime
simulation (vehicles, ventilation visualization) is outside 23B.3 unless a
result-import phase feeds it.

Recommended 23B.3 scope: an engine package = the two render GLBs (re-based to
the engine's expected frame with the transform recorded), optional
per-entity solids, the identity / semantics table, the network as data, an
explicit material table; no runtime plugin, no vendor SDK work.

## 14. Result import / write-back boundary (future, out of 23B scope)

23B is one-way: MineGen → external application. A future phase may accept

    external simulation → result package → MineGen visualization overlay

(Ventsim airflow / pressure / temperature per airway; AnyLogic vehicle
positions, queues, utilization, haulage rates). Such results are overlays
keyed by bundle ids and never modify authoritative mine geometry, topology,
ranking or schedule. Overlay semantics and design authority stay separate.

## 15. Canonical exchange vs application-specific output

    MineExchange bundle   = canonical, application-neutral, versioned contract (rule 190)
    Adapter output        = disposable, application-specific projection

Ventsim DXF / attribute tables, AnyLogic tables, Unity / Unreal packages are
never MineGen authoritative artifacts, never persisted under `derived/`,
never a fingerprint input and always regenerable from a bundle. No
`derived/adapters/` exists.

## 16. Adapter capability matrix

Cells: `READY` (MineExchange 1.2 carries it and the vendor path exists),
`PARTIAL`, `MISSING`, `NOT_REQUIRED`, `FUTURE`.

| | Ventsim | AnyLogic | Unity | Unreal |
| --- | --- | --- | --- | --- |
| Geometry | READY — centerline DXF (official import path) | PARTIAL — centerlines usable as path shapes; meshes not needed | READY — GLB / OBJ, frames declared | READY — GLB (Interchange), OBJ (legacy) |
| Topology | READY — welded centerlines + `network.json` for identity | READY — `nodes.csv` / `edges.csv` + network-by-code | READY (data) — graph as data; navmesh is engine-side | READY (data) |
| Capabilities | NOT_REQUIRED — no ventilation meaning | PARTIAL — restriction candidates, no capacity | PARTIAL — interaction gating only | PARTIAL |
| Production | NOT_REQUIRED (context) | READY — units, tonnes, access links | READY — prism meshes + ids | READY |
| Timeline | MISSING (1.2 `NOT_IN_V1`) — needed only for staged models | MISSING — required for 23B.2 (§12.3) | MISSING — needed only for 4D animation | MISSING |
| Economics | NOT_REQUIRED | NOT_REQUIRED (planning economics are not simulation inputs) | NOT_REQUIRED | NOT_REQUIRED |
| Coordinate mapping | PARTIAL — metres + declared origin; unit declared by adapter, none in DXF flag | PARTIAL — explicit scale / axis parameters | READY — glTF frames declared per file | READY — importer converts |
| Static visualization | READY (reference layers) | NOT_REQUIRED | READY | READY |
| Operational simulation | MISSING — resistance / fans / heat are user inputs (class C) | MISSING — fleet / speeds / dispatch are user model logic (C) + timeline (A) | FUTURE | FUTURE |
| Result write-back | FUTURE (§14) | FUTURE | FUTURE | FUTURE |

## 17. Data gap register

Classes: **A** MineGen authority exists, MineExchange does not expose it ·
**B** no MineGen authority exists · **C** external application-specific
assumption (user planning input) · **D** external application-specific
transformation (adapter work) · **E** future simulation result.

| Gap | Class | Owner of the fix | Notes |
| --- | --- | --- | --- |
| Timeline tasks / development progress / production states | A | MineExchange 1.3 (§12.3) | `MineTimeline` exists (rules 81–86, 174, 196) |
| Edge gradient as a scalar | A (derivable) | MineExchange minor addition or adapter derivation from the centerline | orientation is exported; a signed mean gradient is in the internal edge; adapter derivation is class D and exact |
| Airway resistance / friction factor / roughness | C | user (Ventsim planning input) | never inferred from rock quality |
| Fans, regulators, doors, leakage | C | user | |
| Heat load, diesel emission, gas sources | C | user | |
| Vehicle fleet, speeds, loading / dumping times, capacity, priorities, dispatch, shifts | C | user (AnyLogic model input) | |
| Surface infrastructure (dump, stockpile, crusher, workshop) | B | a future MineGen authority (if ever) | no scenario field; must not be invented by an adapter |
| Airway dimension delivery into Ventsim (DXF carries no attributes) | D | Ventsim adapter (attribute table + documented user step or preset) | values themselves are class-free (present in `crossSection`) |
| Polyline simplification / splitting policy for airway chains | D | Ventsim adapter (explicit tolerance) | must keep topology nodes |
| Unit / origin declaration (Ventsim assumes the current file's units) | D | Ventsim adapter (explicit parameter) | |
| Metre → model-unit scale and axis map for AnyLogic space markup | D | AnyLogic adapter (explicit parameters) | |
| Engine frame re-basing of the copied `LOCAL_ENU_Z_UP` render GLBs | D | engine adapter (recorded transform) | exporter-created GLBs already declare a Y-up root matrix |
| Engine material table (rock / ore / backfill / pillar) | C / D | engine adapter parameter (`ADAPTER_DEFAULT_EXPLICIT`) | |
| Identity in engines when `extras` are not preserved by an importer | D | engine adapter (identity table in the package) | |
| Airflow, pressure, temperature per airway | E | future result-import phase | |
| Vehicle positions, queues, utilization, haulage rate | E | future result-import phase | |
| Fan / ventilation model in Ventsim's native format | — | out of scope (proprietary format, §2) | |

## 18. Recommended implementation sequence

    23B.0  External Adapter Architecture & Contract              — this document
    23B.1  Ventsim Geometry / Network Seed Adapter               — MineExchange 1.2 only
    23B.x  MineExchange 1.3 — Operational / Timeline Semantics   — REQUIRED before 23B.2
    23B.2  AnyLogic Operational Adapter                          — after 1.3
    23B.3  Unity / Unreal Runtime Package Adapter                — 1.2 suffices for static; 1.3 for 4D
    future Simulation Result Import / Overlay                    — separate phase (§14)

23B.3 could run before 23B.2 (it needs no MineExchange change for the
static scope); it is placed third because its product value without the
timeline is a packaged viewer, which the browser app already is. Scopes
stay separate; no two of them are merged into one phase.

## 19. First implementation target — Ventsim vs AnyLogic

| Axis | Ventsim seed adapter | AnyLogic operational adapter |
| --- | --- | --- |
| MineExchange 1.2 readiness | geometry + topology + dimensions present; official DXF import path | network + production present; timeline `NOT_IN_V1` |
| Required new authority | none | MineExchange 1.3 (class A exposure of the existing timeline) |
| Required user assumptions | ventilation physics only (out of seed scope) | fleet / speeds / times / dispatch to run anything at all |
| Implementation complexity | DXF (writer exists) + attribute CSV + identity map + config record | tables + timeline projection + coordinate map + network recipe; 1.3 first |
| Testing feasibility | DXF round-trip with the existing tag-level parser; Convert behaviour needs one manual acceptance on a licensed install | table / id integrity fully unit-testable; model behaviour needs an AnyLogic install and a user-built model |
| Vendor-format openness | DXF documented; native `.vsm` closed (not used) | open (Excel / CSV / JDBC / Java API) |
| Research value | moderate (seed only) | high (operations coupling), but blocked by 1.3 |
| MineGen product value | high — first external engineering consumer of the development topology | high, after 1.3 |

**FIRST IMPLEMENTATION TARGET = Ventsim (23B.1).** The initial hypothesis
holds on the evidence: Ventsim needs no new authority, uses a documented
open import path and can be tested largely against existing writers;
AnyLogic's useful scope is gated by MineExchange 1.3.

## 20. No premature abstraction

23B.0 creates no `BaseAdapter`, `AdapterRegistry`, plugin SDK, adapter
runtime, plugin loader, adapter REST API or adapter persistence. The first
concrete adapter (23B.1) decides which abstraction, if any, is justified by
a second adapter; until then the contract lives in this document only.

## 21. Research evidence

Access date: 2026-09-28. **Limitation:** direct page fetches of
`ventsim.com`, `anylogic.help`, `help.anylogic.com`, `dev.epicgames.com`
and `docs.unity3d.com` were blocked by the sandbox egress proxy in this
session; every vendor claim below was read from search-engine excerpts of
the named official pages, with the official page URL recorded for
verification. Claims that could not be confirmed this way are marked
UNVERIFIED in §11–§13 and must be checked against the manual before the
phase that relies on them.

| Vendor | Document / page | URL | Version / date | Claim supported |
| --- | --- | --- | --- | --- |
| Ventsim (Chart Industries) | Ventsim DESIGN User Guide (PDF) | https://ventsim.com/files/VentsimManual.pdf | current manual (undated in excerpt); older editions 5.2 / 5.4 at `VentsimManual52.pdf`, `VentsimManual5.4.pdf` | DXF / DWG / DGN line-string import; centrelines converted to airways at import or via Add > Convert; reference-only import; imported units assumed = current file; DXF export loses ventilation attributes; Appendix H "Ventsim Static Scripting" |
| Ventsim | Update Log 5.4 / 6.0 | https://ventsim.com/update-log-5-4/ , https://ventsim.com/update-log-6-0/ | 5.4 / 6.0 | Convert Centrelines inherits layers from reference graphics; spreadsheet CSV export row limit removed (6.0) |
| Ventsim | Official Releases | https://ventsim.com/download/currentdownloads/ | 6.0.4.9 (2026-01-01), preview 6.0.5.0 | current version |
| Ventsim | Product page | https://ventsim.com/ventsim-design/ | — | product description |
| AnyLogic | AnyLogic database | https://anylogic.help/anylogic/connectivity/database.html | current help | built-in database; import from Excel / databases |
| AnyLogic | Importing database tables | https://help.anylogic.com/topic/com.anylogic.help/html/connectivity/import.html | current help | Excel `.xlsx`, Access `.accdb`, MS SQL Server, JDBC / ODBC; update on startup |
| AnyLogic | Text file | https://anylogic.help/anylogic/connectivity/text-file.html | current help | CSV read with separators; demo "Reading Agent Parameters from a CSV File" |
| AnyLogic | Excel file | https://anylogic.help/anylogic/connectivity/excel-file.html | current help | `.xls` / `.xlsx` read / write, `readFile()`, load on startup |
| AnyLogic | Create network by code | https://anylogic.help/markup/create-network-by-code.html | current help | nodes / paths / `MarkupSegmentLine(x, y, z)` / `Level`; startup-only |
| AnyLogic | Converting GIS shapefiles to a road network | https://anylogic.help/markup/converting-roads.html | current help | shapefile → space markup on a GIS map (needs real coordinates) |
| AnyLogic | Exporting data to MS Excel file | https://anylogic.help/anylogic/connectivity/export-excel.html | current help | result export (future result-import phase) |
| Epic Games | Importing glTF Files Into Unreal Engine | https://dev.epicgames.com/documentation/en-us/unreal-engine/importing-gltf-files-into-unreal-engine | UE 5.8 docs | glTF import support |
| Epic Games | Importing Assets Using Interchange | https://dev.epicgames.com/documentation/en-us/unreal-engine/importing-assets-using-interchange-in-unreal-engine | UE 5.8 docs (FBX experimental noted at 5.3) | Interchange glTF / GLB "Import Into Level"; offset / scale options |
| Epic Games | Using Datasmith Metadata | https://dev.epicgames.com/documentation/en-us/unreal-engine/using-datasmith-metadata-in-unreal-engine | UE 5.7 docs | per-object metadata via Datasmith |
| Unity | Unity glTFast manual | https://docs.unity3d.com/Packages/com.unity.cloud.gltfast@6.17/manual/index.html | glTFast 6.17 | Editor + runtime glTF import, glTF 2.0 + extensions |
| Unity | glTFast Add-on API — custom extras | https://docs.unity3d.com/Packages/com.unity.cloud.gltfast@6.2/manual/UseCaseCustomExtras.html | glTFast 6.2 | node `extras` accessible |
| Unity | Model file formats | https://docs.unity3d.com/Manual/3D-formats.html | current manual | native `.fbx`, `.obj`, `.dae`, `.3ds`, `.dxf` |
| Khronos / UnityGLTF (secondary) | UnityGLTF issue — coordinate conversion | https://github.com/KhronosGroup/UnityGLTF/issues/257 | — | X mirror on import (secondary evidence for the handedness policy) |

Community forum posts (ventsim.invisionzone.com, Epic forums) were not used
as evidence.

## 22. Completion checklist (23B.0)

- [x] MineExchange remains the only external interoperability boundary (§2)
- [x] no adapter reads `derived/*` directly (§2, §15)
- [x] assumptions are separated from MineGen authority (§7, §17)
- [x] Ventsim mapping matrix (§11.2)
- [x] AnyLogic mapping matrix (§12.2)
- [x] Unity / Unreal mapping matrix (§13.2)
- [x] MineExchange 1.2 gaps classified A–E (§17)
- [x] Timeline / MineExchange 1.3 need decided: REQUIRED before 23B.2 (§12.3)
- [x] first implementation target selected: Ventsim (§19)
- [x] adapter implementation sequence defined (§18)
- [x] result import / write-back kept out of scope (§14)
- [x] no production code added; no MineExchange version change; no FULL / golden re-run (docs-only)

## 23. Phase 23B.1 — Ventsim geometry / network SEED adapter (DELIVERED)

The first concrete adapter. It implements §4–§11 for the Ventsim target in
the seed scope decided in §11.3 and answers the §11.4 questions it can
answer without a Ventsim licence.

### 23.1 Code and boundary

    backend/src/minegen/adapters/
      errors.py           typed failures (§8 codes + MINEEXCHANGE_BUNDLE_INVALID)
      contracts.py        generic AdapterReport DTOs (§4, §6, §7, §10)
      bundle_reader.py    manifest-driven MineExchange ZIP reader (READ ≠ TRUST)
      polyline.py         length + 3-D Douglas-Peucker (end points kept)
      package.py          deterministic package ZIP
      ventsim/config.py   VentsimSeedConfig — explicit parameters
      ventsim/seed.py     build_ventsim_seed(bundle, config) → package + report
    backend/src/minegen/services/adapter_service.py
    backend/src/minegen/api/adapters.py   POST /scenarios/{id}/export/ventsim-seed

The service calls the MineExchange exporter (`ExchangeService.export`, one
coherent validated snapshot) and hands the adapter the bundle **bytes**: the
adapter reads `manifest.json`, verifies every listed file's SHA-256, refuses
unlisted entries and validates each consumed document against its
MineExchange DTO — it never touches `derived/*` and behaves exactly like an
offline consumer of a downloaded bundle (`build_ventsim_seed_from_bundle_bytes`).
Nothing is persisted; no derived artifact, no lifecycle.

### 23.2 Representation decision (§11.4 Q1 answered)

ONE 3-D DXF `POLYLINE` per **MineNetwork edge**, layer = the edge type
(`RAMP`, `LEVEL_ACCESS`, `DRIFT`, `CROSSCUT`, `SHAFT`, `SHAFT_STATION_ACCESS`).
Every network edge owns exactly one exported centerline entity
(`geometryEntityId`) whose first / last points ARE its two topology nodes
(the network builder welds at 1e-6 m), so the DXF polylines of edges meeting
at a node share that vertex — the property Ventsim's Convert Centrelines
needs to join airway chains. The adapter verifies the weld
(`ENDPOINT_WELD_TOLERANCE_M` = 1e-4 m, typed `ADAPTER_CONVERSION_FAILED`
above it — a detached or reversed polyline is never snapped or flipped) and
the declared edge `length` against the polyline it owns (typed
`MINEEXCHANGE_BUNDLE_INVALID` on disagreement).

Vertices are the authoritative points, optionally reduced by a 3-D
Douglas-Peucker pass with an explicit tolerance: end points are always kept,
every kept vertex is an authoritative point, every removed point lies within
the tolerance of the delivered polyline, and the measured maximum deviation
is reported. Default `0.5 m` (one tenth of the default tunnel width,
recorded as `ADAPTER_DEFAULT_EXPLICIT`, `userOverride = false`); `0`
delivers the polyline verbatim. Measured on one 30 m-radius spiral turn
sampled at ≈ 0.47 m: 400 → 33 vertices, deviation 0.156 m.

A `RAISE` edge (the one type with `geometryContract = NONE`) is a typed
omission (`NO_GEOMETRY_CONTRACT`); no geometry is invented for it.

### 23.3 Package (`ventsim_seed/`)

| File | Content |
| --- | --- |
| `airways.dxf` | R12 3-D POLYLINE per edge, deterministic handle, layer = edge type, `$INSUNITS = 6` |
| `airways.csv` | `dxfHandle, airwayId (= edge id), edgeType, layer, sourceNodeId, targetNodeId, geometryEntityId, entityKind, levelId, orientation, authoritativeLengthM, deliveredLengthM, lengthDeviationM, vertexCountAuthoritative, vertexCountDelivered, widthM, heightM, profileShape` |
| `nodes.csv` | every network node: `nodeId, type, x, y, z, levelId, surface` |
| `identity_map.json` | DXF handle ↔ airway / edge / entity id; node positions |
| `adapter_report.json` | the §4 `AdapterReport` (+ config, effective tolerance, airway metrics) |
| `README.txt` | import steps, coordinate statement, what is NOT provided |

No ventilation quantity appears anywhere: the attribute table carries only
what the bundle owns (lengths, cross-section width / height / shape). A
missing cross-section leaves the cells blank and is reported (warning +
`airwaysWithoutCrossSection`), never filled.

### 23.4 Explicit configuration and assumption record

`VentsimSeedConfig` (request body, all optional): `simplificationToleranceM`
(`null` → 0.5 default, `0…5`, validated never clamped), `originOffset`
(metres on the source axes, default `(0, 0, 0)`; the coordinate mapping
records it as `translation`), `dimensionDeliveryPolicy = ATTRIBUTE_TABLE`
and `targetFormat = DXF_R12_3D_POLYLINES` (the only values this version
produces; another value is a 422).

`assumptions[]`: `SIMPLIFICATION_TOLERANCE` and `DIMENSION_DELIVERY_POLICY`
as `ADAPTER_DEFAULT_EXPLICIT` (value, unit, scope, documented source,
userOverride); `AIRWAY_RESISTANCE`, `AIRWAY_ROUGHNESS`, `FANS`,
`REGULATORS_AND_DOORS`, `HEAT_SOURCES`, `CONTAMINANT_SOURCES`,
`AIR_DENSITY_AND_SURFACE_CONDITIONS` as `NOT_PROVIDED`. No `USER_REQUIRED`
parameter exists in 0.1.0.

`sourceStates[]`: `EXCAVATIONS`, `NETWORK` = `AVAILABLE` (required —
`REQUIRED_SOURCE_ABSENT` carries the bundle's own `ARTIFACT_ABSENT` /
`SOURCE_NOT_SUCCESS` reason otherwise); `SHAFTS` only when the bundle
records a shaft omission; `TERRAIN`, `OREBODY`, `FAULTS`, `CAPABILITY`,
`MINING_METHOD`, `PRODUCTION` = `UNSUPPORTED_BY_ADAPTER` (no reference
layers in 0.1.0); `TIMELINE` = `ABSENT` with the bundle's `NOT_IN_V1`.

Coordinate mapping: `LOCAL_ENU_Z_UP` → `LOCAL_ENU_Z_UP`, metre, unit factor
1, translation = the offset. The README states that Ventsim imports a DXF in
the Ventsim file's current units (vendor manual, §11.1).

Versioning: `VENTSIM_SEED 0.1.0`, `supportedMineExchangeVersions =
">=1.2.0,<2.0.0"`; a manifest outside the range is
`MINEEXCHANGE_VERSION_UNSUPPORTED`.

### 23.5 API

    POST /api/v1/scenarios/{id}/export/ventsim-seed     body: VentsimSeedConfig (optional)
      → 200 application/zip  minegen_<id>_ventsim_seed.zip
        X-Adapter-Name: VENTSIM_SEED, X-Adapter-Version: 0.1.0, X-MineExchange-Version: 1.2.0
      → 404 SCENARIO_NOT_FOUND · 409 WORLD_NOT_GENERATED · 409 READ_SNAPSHOT_CHANGED
      → 409 <MineExchange refusal>  (STALE / MALFORMED / MINE_EXCHANGE_EXPORT_FAILED)
      → 409 REQUIRED_SOURCE_ABSENT · 409 MINEEXCHANGE_BUNDLE_INVALID
      → 409 MINEEXCHANGE_VERSION_UNSUPPORTED · 409 ADAPTER_CONVERSION_FAILED
      → 422 COORDINATE_MAPPING_UNSUPPORTED · 422 request validation (out-of-range parameter)

Frontend: `Export Ventsim seed (.zip)` in the Scenario panel, enabled only
when the scene shows a ramp and a SUCCESS network (the same prerequisite the
backend enforces); no adapter parameter is edited in the UI in 23B.1.

### 23.6 Tests

`backend/tests/test_ventsim_seed_adapter.py` (FAST, synthetic bundle through
the REAL exporter: identity / shared end vertices / determinism, faithful vs
simplified, Douglas-Peucker properties, attribute table, source states and
NOT_PROVIDED policy, RAISE omission, origin offset, world-only refusal,
tampered / unlisted / non-ZIP / malformed-manifest bundles, version range,
detached end point, inconsistent length, missing cross-section, config
validation, API 404 / 409 / 422) and
`backend/tests/test_exchange_bundle.py::test_v1_ventsim_seed_over_the_real_layout_v2_chain`
(e2e: the real LAYOUT_V2 chain — every edge welded, simplification inside
tolerance, read-only, byte-identical re-run). Frontend:
`exportFilename.test.ts`, `exportContents.test.tsx`.

### 23.7 Open after 23B.1 (unchanged, §11.4)

- Q2 a documented text / spreadsheet airway import — UNVERIFIED; the
  attribute-table path is the one implemented.
- Q3 layer inheritance on Convert Centrelines in 6.0.x — to confirm on an
  installation.
- Q4 acceptance on a real Ventsim installation (Convert behaviour, joined
  chains, dimension assignment) is a MANUAL acceptance step with a licence;
  everything verifiable without one (DXF structure through the independent
  tag-level parser, identity, welds, tolerances, determinism) is a unit
  test.
- Reference layers (terrain / orebody / faults) as optional context DXF
  layers are a later adapter version, reported today as
  `UNSUPPORTED_BY_ADAPTER`.
