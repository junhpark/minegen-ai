# External adapters — architecture, contract and implementation (Phase 23B)

Status: **DELIVERED as ONE phase (23B)** — architecture finalized,
MineExchange 1.3 (timeline semantics), and four adapters at version 0.1.0:
Ventsim (§23.3), AnyLogic (§23.4), Unity and Unreal (§23.5). §1–§22 are the
architecture decision and gap analysis this implementation is built on
(kept as the record; §23 is the implementation contract and supersedes any
earlier sub-phase wording such as "23B.1 / 23B.x / 23B.2 / 23B.3" — no
sub-phase split exists). CLAUDE.md rules 207–212 are the binding invariants.

Baseline: `main` `4321babcce423d89a608ce4dc553fb71705d4a54` (after PR #49,
Phase 22C). MineExchange contract: `docs/mine-exchange.md` (1.3.0, rules
190 / 208).

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

## 4. Adapter input / output contract (conceptual sketch; implemented as `AdapterManifest` in `adapters/contracts.py`, §23.1)

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

## 5. MineExchange as the stable boundary — inventory (1.3)

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
| Timeline (1.3) | `operations/timeline.json` (authority: the MineTimeline projection), `operations/tasks.csv` | tasks with EXTERNAL `targetReference` (`NETWORK_EDGE` = edge id; `ENTITY` = `stope:` / `cut:` / `bench:` entity id), development progress (chainage fractions, start node, direction, transitions), production state machines, metrics — `docs/mine-exchange.md` "Timeline semantics" | the AnyLogic operational input; the engines' `scene/timeline.json` |
| Omissions | `manifest.omissions[]` | `ARTIFACT_ABSENT`, `SOURCE_NOT_SUCCESS` (with detail), `NOT_IN_V1` (field lattice only since 1.3) | the adapter's five-state input (§6) |

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

Not in the bundle (1.3): the field lattice (`NOT_IN_V1`), economics, a
Boolean union of excavations, any operational or physical property
(roughness, resistance, fans, fleet, speeds). The timeline joined the
bundle in 1.3 (`operations/`).

## 6. Five-state source mapping rule

An adapter never flattens source availability. Every bundle group it
consumes is reported in exactly one of FIVE states
(`AdapterSourceState`, `adapters/contracts.py`; decided once in
`adapters/common.py::source_state`):

| State | Meaning | Who decides |
| --- | --- | --- |
| `AVAILABLE` | the bundle carries the source and the adapter consumed it | bundle + adapter |
| `ARTIFACT_ABSENT` | `manifest.omissions[]` says `ARTIFACT_ABSENT` (MineGen never generated it) — or, for the optional SHAFTS group, no shaft entity exists | MineGen / bundle |
| `SOURCE_NOT_SUCCESS` | the source exists but its status is FAILED (`omissions[].detail`) | MineGen / bundle |
| `NOT_EXPORTED_BY_VERSION` | the MineGen authority may exist but the consumed MineExchange version does not expose it: the bundle's `NOT_IN_V1` (field lattice), or a group a newer version carries (the timeline for a 1.2 bundle) | MineExchange version |
| `UNSUPPORTED_BY_ADAPTER` | the bundle carries it, this adapter version has no mapping for it | adapter |

`bundleReasonCode` carries the bundle's own omission reason through
whenever the bundle decided the state. The states are never conflated: an
absent artifact (`ARTIFACT_ABSENT`) is not a version gap
(`NOT_EXPORTED_BY_VERSION`) and neither is an adapter gap
(`UNSUPPORTED_BY_ADAPTER`); "ABSENT" as a bare word is not a state. A group
with several bundle members (`RENDER_GLB`: the ramp tunnel GLB and the
development GLB) is `AVAILABLE` when at least one member was consumed and
names the omitted members in `detail` and in `omissions[]`
(`adapters/common.py::multi_member_group_state`).

Example: no shaft in the mine → `SHAFTS = ARTIFACT_ABSENT`. A shaft in the
bundle but an adapter version without a vertical-airway mapping →
`SHAFTS = UNSUPPORTED_BY_ADAPTER`. A 1.2-shaped bundle (no
`operations/timeline.json`) under a 1.3 manifest → `TIMELINE =
ARTIFACT_ABSENT` (the bundle records the omission); a genuine 1.2 bundle →
`TIMELINE = NOT_EXPORTED_BY_VERSION` for the engine packages and a typed
version refusal for AnyLogic, which requires 1.3.

## 7. Assumption policy

Values a target application requires but no MineGen authority owns —
airway roughness / friction factor, fan curves, regulator resistance, door
leakage, heat load, diesel emission, vehicle speed, loading / dumping time,
vehicle capacity, traffic priority, material densities beyond the scenario
density, engine materials — are **never guessed**. Each such value is in one
of three states, recorded in `adapter_manifest.json → assumptions[]`
(`AdapterAssumption`):

| State | Meaning |
| --- | --- |
| `NOT_PROVIDED` | left empty in the target package; the target application's own default or the user fills it there |
| `USER_REQUIRED` | the adapter refuses to emit the element until the user supplies the value (`REQUIRED_PARAMETER_MISSING`, §8) |
| `ADAPTER_DEFAULT_EXPLICIT` | a documented adapter default was applied — recorded with `source` (adapter version + documented table), `value`, `unit`, `scope` (which entities), and `userOverride` (whether / how the user changed it) |

A silent default — a number written into the target package that is not in
the bundle and not in `assumptions[]` — is a defect. No adapter of 23B
applies an `ADAPTER_DEFAULT_EXPLICIT` value (the earlier simplification
tolerance default is gone with the simplification itself): every
operational / physical / engine value is `NOT_PROVIDED`, and no
`USER_REQUIRED` parameter exists in 0.1.0.

## 8. Failure model (implemented: `adapters/errors.py`)

| Code | HTTP | When |
| --- | --- | --- |
| `ADAPTER_MINEEXCHANGE_BUNDLE_INVALID` | 409 | the input is not a readable, integral MineExchange bundle (bad ZIP, missing / malformed manifest, SHA-256 mismatch, unlisted or unsafe entry, a document that does not validate against its DTO, a dangling reference the bundle preflight should have refused) |
| `ADAPTER_MINEEXCHANGE_VERSION_UNSUPPORTED` | 409 | `manifest.mineExchangeVersion` outside `supportedMineExchangeVersions` |
| `ADAPTER_REQUIRED_SOURCE_ABSENT` | 409 | a group the adapter needs is `ARTIFACT_ABSENT` / `NOT_IN_V1` (the omission reason is carried through) |
| `ADAPTER_SOURCE_NOT_SUCCESS` | 409 | a group the adapter needs exists but its authority is FAILED |
| `ADAPTER_CONVERSION_FAILED` | 409 | a conversion defect the adapter detected (duplicate target id, dangling reference, a polyline whose end points are not its topology nodes, an invalid GLB, a non-finite value, an unsafe package path) |
| `ADAPTER_TARGET_UNSUPPORTED` | 422 | the requested target application is not one this adapter set produces |

Every failure (`AdapterError`) names the ADAPTER, the bundle SOURCE GROUP
when one is concerned, the SUBJECT (entity / file / parameter) and the
REASON in its `detail` (`adapter=…; group=…; subject=…; reason=…`); the
API answers with the contract code and that message, never a bare 500. A
MineExchange refusal raised while building the bundle (`WORLD_NOT_GENERATED`,
`READ_SNAPSHOT_CHANGED`, STALE / MALFORMED artifacts,
`MINE_EXCHANGE_EXPORT_FAILED`) passes through unchanged. The 23B.0
candidates `REQUIRED_PARAMETER_MISSING`, `TARGET_FORMAT_UNSUPPORTED` and
`COORDINATE_MAPPING_UNSUPPORTED` have no trigger in 0.1.0 (no user
parameter, one format per target, one coordinate mapping per target) and are
not declared.

## 9. Versioning

    adapterName                   VENTSIM | ANYLOGIC | UNITY | UNREAL
    adapterVersion                0.1.0 for all four (semver of the adapter itself)
    supportedMineExchangeVersions VENTSIM / UNITY / UNREAL ">=1.2.0,<2.0.0"; ANYLOGIC ">=1.3.0,<2.0.0"
    sourceMineExchangeVersion     the consumed bundle's manifest version

Example: `VENTSIM 0.1.0`, `MineExchange >=1.2.0,<2.0.0`. The adapter version and
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
  package records an identity mapping (no offset, no re-basing).
- AnyLogic: space-markup coordinates are model-local; the package delivers
  `LOCAL_ENU_Z_UP` metres and records the model axis mapping / scale as a
  `NOT_PROVIDED` assumption (`MODEL_AXIS_MAPPING`) — a consumer parameter,
  never a hidden default.
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

### 12.3 Mine­Exchange 1.3 decision gate (RESOLVED — 1.3 delivered in 23B)

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

### 12.5 Recommended AnyLogic scope (implemented in 23B, §23.4)

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
| Timeline | PRESENT since 1.3 (`operations/timeline.json`; unused by the Ventsim seed) | PRESENT since 1.3 — consumed (§23.4) | PRESENT since 1.3 — copied as `scene/timeline.json` (§23.5) | delivered (was MISSING in 1.2) |
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

## 18. Implementation sequence (as delivered)

The 23B.0 plan foresaw sub-phases (23B.1 Ventsim seed, 23B.x MineExchange
1.3, 23B.2 AnyLogic, 23B.3 Unity / Unreal). Phase 23B delivered all of
them as ONE phase on one branch (see §23); the sub-phase names are
historical and no longer denote separate deliverables. Simulation result
import / overlay stays a separate future phase (§14).

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

**First implementation target was Ventsim** (its seed shipped first, then
was reworked to the §23.3 contract inside the same phase); AnyLogic's useful
scope was gated by MineExchange 1.3, which 23B delivers.

## 20. No premature abstraction

23B creates no `BaseAdapter`, plugin SDK, adapter runtime, plugin loader or
adapter persistence. `adapters/registry.py::ADAPTERS` is a plain table of
four `bytes → AdapterPackage` builders keyed by target (the API composes it
with the exporter through `AdapterService`); shared consumption helpers live
in `adapters/common.py` and the deterministic writer in
`adapters/package.py`. That is the whole framework.

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

## 22. Completion checklist (23B.0 architecture stage, historical)

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

## 23. Phase 23B — Full External Application Adapters (DELIVERED)

One phase, one branch, one PR: architecture (§23.1), MineExchange 1.3
(§23.2), Ventsim (§23.3), AnyLogic (§23.4), Unity / Unreal (§23.5), API and
frontend (§23.6), tests and acceptance (§23.7). No proprietary vendor file
(`.vsm`, `.alp`, `.unitypackage`, `.uasset`) is produced anywhere.

### 23.1 Architecture and boundary (rules 207, 209)

    backend/src/minegen/adapters/
      errors.py           AdapterError + the six typed codes (§8)
      contracts.py        AdapterManifest, AdapterSourceState (five states), AdapterAssumption,
                          AdapterGeneratedFile, AdapterCoordinateMapping, AdapterIdentityEntry,
                          AdapterOmission
      bundle_reader.py    manifest-driven MineExchange ZIP reader (READ ≠ TRUST)
      common.py           shared consumption helpers: five-state mapping, required-group refusal,
                          version range, network / centerline / timeline / capability documents,
                          NOT_PROVIDED assumptions, identity coordinate mapping
      package.py          PackageBuilder / write_package — deterministic ZIP, adapter_manifest.json last
      registry.py         ADAPTERS = {VENTSIM, ANYLOGIC, UNITY, UNREAL} → build_package(target, bytes)
      ventsim/adapter.py  build_ventsim_package
      anylogic/adapter.py build_anylogic_package
      engine/glb.py       split_glb / join_glb / scene_root_nodes / add_root_transform
      engine/package.py   build_unity_package / build_unreal_package
    backend/src/minegen/services/adapter_service.py   AdapterService(ExchangeService).export(id, target)
    backend/src/minegen/api/adapters.py               POST /scenarios/{id}/export/{ventsim|anylogic|unity|unreal}

**Input = MineExchange ZIP bytes, nothing else.** `AdapterService` calls
`ExchangeService.export` (one coherent validated snapshot) and hands the
bytes to `build_package`; the adapter package never imports or reads
`ScenarioStore`, `ArtifactReader`, `DesignService`, `derived/*`,
`scenario.json`, `timeline.json`, `network.json` or `stopes.json`
(`tests/test_adapters_core.py::test_b63_*` scans the import graph and the
code strings, and builds every package from a saved fixture ZIP without any
service module loaded). The reader: safe relative paths under
`mine_exchange/`, `manifest.json` validated as `ExchangeManifest`, every
listed file present with its SHA-256, no unlisted entry, entity file
references resolving, `LOCAL_ENU_Z_UP` metre contract; files, entities,
semantic types, DXF handles (`files[].dxfEntities`) and omissions are looked
up through the manifest — no file name is guessed, no handle is re-parsed.

**Output = one deterministic ZIP per target** (`<target>_package/`):
fixed 1980-01-01 entry timestamps, lexicographic paths, fixed DEFLATE,
SHA-256 per file, duplicate / unsafe paths refused, no wall-clock value;
same bundle bytes → byte-identical package. `adapter_manifest.json`
(`AdapterManifest`) is the meaning authority of every package:

    adapterName, adapterVersion, targetApplication
    supportedMineExchangeVersions, sourceMineExchangeVersion
    sourceScenarioId, sourceScenarioName, sourceSnapshot (copied from the bundle manifest)
    coordinateMapping { sourceFrame, targetFrame, unit, unitFactor, handedness, upAxis, transform, note }
    generatedFiles[]  { path, mediaType, targetSemantic, sourceEntityIds[], sourceFiles[], sha256 }
    identityMap[]     { targetId, targetKind, bundleEntityId, bundleEdgeId, bundleNodeId, file }
    sourceStates[]    { group, state (§6), bundleReasonCode, detail }
    assumptions[]     { kind, state (§7), value, unit, scope, source, userOverride, note }
    warnings[], omissions[] { subject, reasonCode, detail }, details {}

Read-only: an export generates nothing and persists nothing — `scenario.json`,
`arrays.npz`, `derived/*` and `economics.json` stay byte- and stat-identical
(proved by `tests/test_adapters_api.py` and `tests/test_adapters_e2e.py`).

### 23.2 MineExchange 1.3 — timeline semantics (rule 208)

`docs/mine-exchange.md` "Timeline semantics" is the contract:
`operations/timeline.json` (`ExchangeTimeline`) + `operations/tasks.csv`,
`TIMELINE_ARTIFACT` in the export snapshot, external `targetReference` per
task (`NETWORK_EDGE` = edge id; `ENTITY` = `stope:<id>` / `cut:<id>` /
`bench:<unitId>`; BACKFILL / CURE target the cut; pillars never a target),
development progress and production states copied from the authority,
preflight-bound to the exported edges / centerlines / entities. Additive:
every 1.2 file is byte-identical and the geometry binaries are untouched
(`tests/test_exchange_timeline.py` MX13-11 / 12). `TIMELINE` omission =
`ARTIFACT_ABSENT` / `SOURCE_NOT_SUCCESS`; `FIELD_LATTICE` stays the only
`NOT_IN_V1`.

### 23.3 Ventsim — geometry / network SEED (`VENTSIM 0.1.0`, rule 210)

Requires `EXCAVATIONS` (centerlines) and `NETWORK`; `SHAFTS` consumed when
present (SHAFT / SHAFT_STATION_ACCESS airways). MineExchange `>=1.2.0,<2.0.0`.

    ventsim_package/
      adapter_manifest.json
      README.txt                      documented Ventsim workflow, coordinate statement, NOT PROVIDED list
      geometry/mine_centerlines.dxf   the bundle's excavations/centerlines.dxf, BYTE FOR BYTE
      network/nodes.csv               nodeId, nodeType, x, y, z, levelId, surface
      network/airways.csv             edgeId, geometryEntityId, sourceNodeId, targetNodeId, edgeType, lengthM,
                                      widthM, heightM, shape, orientation, dxfHandle, levelId, vertexCount
      identity/entity_map.csv         dxfHandle, layer, dxfEntityType, entityId, entityKind, levelId, edgeId

Representation (§11.4 Q1, revised): the bundle DXF is the geometry authority
and is delivered **verbatim — full fidelity, no simplification** (the earlier
Douglas-Peucker option and its `ADAPTER_DEFAULT_EXPLICIT` tolerance are
removed). One 3-D POLYLINE per exported centerline entity, layer = entity
kind; every network edge owns exactly one entity whose end points ARE its
topology nodes, so polylines meeting at a node share the vertex Ventsim's
Convert Centrelines joins. DXF handles come from `manifest.files[].dxfEntities`
(never re-parsed). The adapter VERIFIES and never repairs: end points on the
nodes within `ENDPOINT_WELD_TOLERANCE_M` = 1e-4 m (typed
`ADAPTER_CONVERSION_FAILED`, never snapped or reversed), declared edge length
equal to the polyline length within 1e-6 relative (typed
`ADAPTER_MINEEXCHANGE_BUNDLE_INVALID`). `RAISE` (the one edge type without an
owning centerline) is a typed `NO_GEOMETRY_CONTRACT` omission. A missing
cross-section leaves `widthM` / `heightM` blank with a warning, never filled.

No ventilation physics: `airways.csv` has no friction, resistance, fan,
regulator, door, leakage, heat, diesel, airflow, pressure or density column;
`assumptions[]` records `AIRWAY_FRICTION_FACTOR`, `AIRWAY_RESISTANCE`,
`FANS`, `REGULATORS_AND_DOORS`, `HEAT_SOURCES`,
`DIESEL_AND_CONTAMINANT_SOURCES`, `AIRFLOW_AND_PRESSURE` as `NOT_PROVIDED`.
The CSV is an **authoritative handoff / QA table**: applying dimensions
inside Ventsim per DXF handle / layer is the documented USER workflow
(README steps: DXF import → Convert Centrelines → verify metric / local
basis → assign dimensions → configure physics); no official automated
attribute import is claimed (§11.4 Q2 stays UNVERIFIED), and no `.vsm` is
produced. Coordinate mapping: identity (`LOCAL_ENU_Z_UP` metres; Ventsim
imports a DXF in the file's CURRENT units — the README says to set metres).

### 23.4 AnyLogic — operational data package (`ANYLOGIC 0.1.0`, rule 211)

Requires MineExchange `>=1.3.0,<2.0.0`, `NETWORK` and `TIMELINE`
(`ADAPTER_REQUIRED_SOURCE_ABSENT` / `ADAPTER_SOURCE_NOT_SUCCESS` with the
bundle's reason otherwise; a 1.2 bundle is
`ADAPTER_MINEEXCHANGE_VERSION_UNSUPPORTED`); production optional.

    anylogic_package/
      adapter_manifest.json, README.txt
      data/nodes.csv                  nodeId, nodeType, x, y, z, levelId, surface
      data/edges.csv                  edgeId, sourceNodeId, targetNodeId, edgeType, geometryEntityId, lengthM,
                                      widthM, heightM, shape, orientation, geometryContract
                                      (direction = storage / centerline orientation, NOT one-way traffic)
      data/centerline_points.csv      geometryEntityId, sequence, x, y, z
      data/capabilities.csv           edgeId, capability, allowed, source   (capability ≠ capacity)
      data/production_units.csv       entityId, productionKind (STOPE | CUT | BACKFILL | BENCH | PILLAR), sourceId,
                                      levelId, accessReference, plannedTonnes, geometricVolumeM3, retained,
                                      backfill, parentEntityId
      data/tasks.csv                  taskId, taskType, targetKind, targetReferenceKind, targetReferenceId, startDay,
                                      endDay, durationDays, dependencies (JSON list), basis quantity / unit / rate
      data/development_progress.csv   edgeId, geometryEntityId, taskId, progressStartDay, progressEndDay,
                                      excavationStartNode, progressDirection, initialState, pointChainageFractions
      data/production_states.csv      entityId, targetKind, initialState, transitionIndex, day, state
      templates/simulation_inputs.csv fleetSize, truckType, lhdType, speedLoadedKmh, speedEmptyKmh, gradeSpeedCurve,
                                      loadingTimeMin, dumpingTimeMin, shiftCalendar, trafficPriority, dispatchLogic,
                                      crusherCapacityTph, stockpileCapacityT — COLUMNS ONLY, every value blank

Pillars are RETAINED material (`retained = true`, `plannedTonnes` blank);
a backfill is the semantic record of a cut void (`backfill = true`,
`plannedTonnes` blank, `parentEntityId` = the source cut) — neither is
production tonnes. Referential integrity is re-verified at the boundary
(every task target an edge or an exported production unit, every dependency
a task, every progress edge / start node and every state entity known, every
capability edge a network edge) — a defect is
`ADAPTER_MINEEXCHANGE_BUNDLE_INVALID`. No fleet, speed, cycle time, calendar,
priority, dispatch or capacity value is written or defaulted (all
`NOT_PROVIDED`, plus `MODEL_AXIS_MAPPING`); no `.alp` is produced. The README
gives the documented AnyLogic workflow (database / text-file import, network
by code, tables as the planning baseline).

### 23.5 Unity / Unreal — engine import packages (`UNITY` / `UNREAL 0.1.0`, rule 212)

MineExchange `>=1.2.0,<2.0.0`; no required group — a world-only bundle
yields a partial package (geology assets only).

    <unity|unreal>_package/
      adapter_manifest.json, README.txt
      scene/assets/<bundle path, '/' → '_'>.glb   every bundle GLB, scene = glTF Y-up right-handed metres
      scene/entities.json         IDENTITY AUTHORITY: entityId, kind, levelId, assetPath, sourceEntityId,
                                  sourceId, parentEntityId, sourceMemberIds, networkEdgeIds[], bundleFiles[]
      scene/network.json          topology/network.json verbatim (when present)
      scene/capability.json       semantics/capability.json verbatim (when present)
      scene/timeline.json         operations/timeline.json verbatim (when present, 1.3)
      scene/import_settings.json  packageSceneFrame, unit, handedness, the root matrix, engine notes,
                                  per-asset facts (storedVertexFrame, sourceSceneFrame, rootTransformAdded,
                                  binaryChunkPreserved, junctionApertures, closed)

GLB normalization (`engine/glb.py`): an exporter GLB (`glb.sceneFrame =
GLTF_Y_UP`, root matrix present) is copied verbatim; a copied render GLB
(`sceneFrame = LOCAL_ENU_Z_UP`, `transformMatrix = null`) gets EXACTLY ONE
new root node `MineExchange_LOCAL_ENU_Z_UP_to_GLTF_Y_UP` carrying the
column-major matrix of `(x, y, z) → (x, z, −y)` that parents the previous
scene roots; nodes, meshes, accessors, extras and the BIN chunk are preserved
byte for byte; a GLB already carrying the root node is refused (never
transformed twice); any other frame record or an invalid container is
`ADAPTER_CONVERSION_FAILED`. Unity and Unreal packages differ only in the
engine notes (Unity: glTFast / UnityGLTF, Y-up left-handed importer mirror,
metres; Unreal: Interchange glTF import, Z-up left-handed, centimetres by
the importer's metre → cm scale). Not provided (all `NOT_PROVIDED`):
materials / lighting, collision / physics, NavMesh, gameplay / AI,
ventilation simulation, runtime synchronization, animation. No
`.unitypackage` / `.uasset`.

### 23.6 API and frontend (rule 209)

    POST /api/v1/scenarios/{id}/export/ventsim
    POST /api/v1/scenarios/{id}/export/anylogic
    POST /api/v1/scenarios/{id}/export/unity
    POST /api/v1/scenarios/{id}/export/unreal
      → 200 application/zip  minegen_<id>_<target>.zip
        X-Adapter-Name: <TARGET>, X-Adapter-Version: 0.1.0, X-MineExchange-Version: 1.3.0
      → 404 SCENARIO_NOT_FOUND · 409 WORLD_NOT_GENERATED · 409 READ_SNAPSHOT_CHANGED
      → 409 <MineExchange refusal>  (STALE / MALFORMED / MINE_EXCHANGE_EXPORT_FAILED)
      → 409 ADAPTER_REQUIRED_SOURCE_ABSENT · 409 ADAPTER_SOURCE_NOT_SUCCESS
      → 409 ADAPTER_MINEEXCHANGE_VERSION_UNSUPPORTED · 409 ADAPTER_MINEEXCHANGE_BUNDLE_INVALID
      → 409 ADAPTER_CONVERSION_FAILED · 422 ADAPTER_TARGET_UNSUPPORTED

Frontend (`components/panels/ScenarioPanel.tsx`, `exportContents.ts`,
`api/client.ts::exportAdapter`): one compact selector (MineExchange —
"Canonical exchange bundle"; Ventsim — "Ventilation geometry/network seed";
AnyLogic — "Operational simulation data package"; Unity / Unreal — "Engine
import package") with one "Export <target> (.zip)" button; the download
mutates no scene state and no epoch; a backend refusal is shown through the
existing `ApiError` display. "Current export contents" gained the Timeline
row (1.3).

### 23.7 Tests and acceptance

- `tests/test_exchange_timeline.py` (FAST, MX13-1 … MX13-14 on the
  synthetic consistent mine) and `tests/test_exchange_timeline_e2e.py`
  (real Longhole / Cut & Fill / Room & Pillar chains).
- `tests/test_adapters_core.py` — boundary (import graph + code-string scan,
  build from saved bytes without services), bundle integrity refusals,
  version ranges, five-state mapping, error detail, deterministic /
  wall-clock-free packages, package builder guards.
- `tests/test_adapter_ventsim.py`, `tests/test_adapter_anylogic.py`,
  `tests/test_adapter_engine.py` — per-adapter contracts on the synthetic
  bundle (verbatim DXF, manifest handles, copied dimensions, no physics
  columns, detached end point / length refusals, blank template, no fleet
  value, 1.2-shape and version refusals, GLB root transform added once with
  the binary chunk preserved, Unity vs Unreal, world-only partial package).
- `tests/test_adapters_api.py` (FAST: 404 / 409 / typed refusals / headers /
  read-only proof on a world-only scenario) and `tests/test_adapters_e2e.py`
  (real chains: Ventsim, AnyLogic on all three methods — pillars retained,
  backfill never tonnes, targets resolve — Unity / Unreal re-framing both
  render GLBs exactly once, every export read-only).
- Browser acceptance Cases A–G (production build + real backend) recorded in
  the phase report. A licensed Ventsim / AnyLogic / engine import remains a
  manual step outside CI (§11.4 Q3 / Q4 unchanged).
