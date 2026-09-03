# MineGen-AI Architecture (v0.1)

## Concept

MineGen-AI generates an underground mine from geology, orebody, rock-mass and
operational parameters, then lets a researcher design, sequence, instrument
and walk through it in a web browser. It is a research sandbox, not a
replacement for commercial mine-planning packages.

Design principle: **Geometry + Graph + Time + Simulation + Optimization**.

## Four shared representations

Every subsystem reads and writes the same mine through four views:

                       Mine Scenario
                            │
            ┌───────────────┼─────────────────┐
            ▼               ▼                 ▼
      Spatial World      Mine Network      Mine Timeline
      (geometry)         (graph)           (temporal model)
            └───────────────┼─────────────────┘
                            ▼
                    Simulation State
                ┌───────────┼───────────┐
                ▼           ▼           ▼
            Haulage     Ventilation   Communication / Sensors

1. **Geometry** – terrain, orebody, faults, tunnels, stopes, backfill,
   equipment, routers, sensors as 3D shapes (NumPy arrays, meshes).
2. **Graph** – `MineNetwork` (`networkx.MultiDiGraph`): nodes
   (PORTAL, JUNCTION, LEVEL_ENTRY, STOPE_ACCESS, …) and edges
   (RAMP, DRIFT, CROSSCUT, RAISE, SHAFT) carrying length, gradient,
   cross-section, cost and reserved simulation attributes.
3. **Time** – every major object has temporal state
   (PLANNED → DEVELOPING → ACTIVE → MINED → VOID → BACKFILLED → CLOSED) driven
   by a task DAG. `3D geometry + time = 4D mine`.
4. **Simulation** – each edge carries attributes that physics / operational
   models can fill in (haulage, ventilation, RF loss, rock risk).

Geometry and graph are both derived from the **tunnel centerline**. The
centerline is the source of truth; mesh and graph edge are siblings, never
parent/child (CLAUDE.md rule 13).

## Backend module map

    minegen/
      core/            enums, Pydantic models, coordinate utilities, units
      world/           terrain, authoritative orebody solid, numerical field
                       lattice (FieldGrid), SpatialFieldSet (rock quality, grade,
                       fault measurements; batch sample()), geology generators
      design/          cost field, level access targets, motion primitives,
                       smoothing + shared sample validation (Phase 05),
                       chained Hybrid-A* decline generator, smoothing,
                       constraints, level generator, mine designer
      geometry/        centerline, tunnel profile, tunnel mesh (gravity-aligned
                       sweep), mesh utils
      network/         MineNetwork graph, builder, metrics
      mining/          MiningMethod strategy interface, longhole open stoping,
                       stope generator, rule-based method selector
      scheduling/      MineTask, dependencies, scheduler, timeline state
      infrastructure/  candidate sites, demand points, coverage models,
                       PlacementProblem, placement optimizers
      simulation/      adapters for external haulage / ventilation solvers
      export/          scene manifest, JSON, glTF
      services/        scenario persistence, async job service
      api/             FastAPI routers (thin; no algorithms)

Layering (CLAUDE.md rule 5): `core` ← algorithms (`world`, `design`, …) ←
`services` ← `api`. Algorithms never import FastAPI. The API never
implements numerics.

## Frontend module map

    src/
      api/             typed fetch client (TanStack Query, in use since Phase 01)
      stores/          Zustand: scenario, viewer, timeline
      components/      layout, panels, timeline
      scene/           R3F canvas and per-layer components
      walkthrough/     first-person controller, collider, headlamp, HUD
                       (Rapier is added here in Phase 13, not before — rule 15)
      geometry/        coordinateTransform (the only Three.js mapping),
                       TunnelMeshFactory (BufferGeometry assembly only)
      types/           API types mirrored from backend schemas

The frontend never computes mine engineering quantities
(CLAUDE.md rule 17, 32).

## Decline design (decision record)

The decline is a **chained Hybrid-A\*** over per-level access targets, not a
single portal-to-orebody search:

    Portal → {L1 candidates} → {L2 candidates} → {L3 candidates} → …

Rationale: a 12 % decline losing 300 m needs ~2.5 km of development; a single
search to a deep target produces a spiral whose crossings of intermediate
level elevations are far from the orebody, which would explode level
development length. Chaining to footwall access targets per level mirrors
real decline layouts. Details: CLAUDE.md rules 21–25.

Name: **Chained Hybrid-A\* Decline Generator**.

## Tunnel frame (decision record)

Tunnel profiles are swept with a **gravity-aligned frame**, not parallel
transport (CLAUDE.md rule 26). Parallel transport is rotation-minimizing and
would bank the floor along a spiral. Gravity alignment is always well-defined
for ramp gradients (tangent is never vertical).

## Geology before routing (decision record)

Rock-quality field and synthetic fault planes are generated in Phase 02 so
that Phase 03 cost fields and Phase 04 routing have something to avoid
(CLAUDE.md rule 27). The first demo must show the decline changing when a
fault is added.

## Development phases

    01 Repository scaffold                   done
    02 Synthetic world (terrain, orebody, spatial fields, rock quality, faults)   done
    03 Design cost evaluator & level access targets   done
    04 Chained Hybrid-A* decline generator (raw path)   done
    04.5 Async jobs + progress + CI                      done
    05 Ramp smoothing + revalidation   done
    06 Tunnel mesh (gravity-aligned sweep)   done
    07 MineNetwork   done
    08 Levels & crosscuts   done
    09 Stopes & mining method   done
    10 4D mining sequence   done
    11 Communication OSP    done
    12 Generic Sensor OSP   done
    13 First-person walkthrough done
    14 Walkthrough interaction done
    15 4D walkthrough done
    16 Navigation / visual polish   done
    17 Deterministic geology & orebody scenario engine   done
    17.1 Scenario isolation & viewer polish   done
    18 Spatial Field Core (no block/SMU semantics)   done ← current
    (19 … 23: see docs/roadmap.md)

## Scenario document shape

    scenario
     ├─ world          size_x, size_y, depth (below terrain reference elevation)
     ├─ terrain
     ├─ orebody
     ├─ geology
     │    ├─ rockQuality
     │    └─ faults[]   (half-widths from the plane)
     ├─ fieldSampling  numerical field spacing (never a block / SMU size);
     │                 schemaVersion 2 — v1 `blockModel` is migrated on read
     ├─ portal
     ├─ ramp
     ├─ tunnelProfile
     ├─ mining
     ├─ schedule       Phase 10 temporal planning rates/durations
     │                 (synthetic baseline defaults, rule 82)
     └─ infrastructure Phase 11 communication + Phase 12 sensor planning
                       parameters (network-geodesic ranges; synthetic
                       planning/demo assumptions, never RF measurements or
                       gas models, rules 88/95)

Future geology members (water, lithology, alteration, joint sets, stress)
go under `geology`, not at the scenario root.

## Persistence and jobs (v0.1)

- Scenarios: `data/scenarios/{id}/scenario.json` + `arrays.npz` + `derived/`.
  `derived/` now holds `targets.json`, `decline.json`, `decline_smoothed.json`,
  `tunnel_mesh.json` (Phase 06 report, always persisted with explicit status),
  `tunnel_mesh.glb` (excavation mesh, SUCCESS only), `levels.json` (Phase 08
  typed LevelsPayload — the validated centerline artifact owning DRIFT and
  CROSSCUT geometry, rule 71), `stopes.json` (Phase 09 typed StopesPayload —
  planned stope prisms in the analytic orebody frame, rule 75), `network.json` (Phase 07/08 typed
  NetworkPayload — deterministic serialization of the typed contract, never
  a raw NetworkX dump), `timeline.json` (Phase 10 typed TimelinePayload —
  deterministic precedence-only planning baseline owning time/task/state
  only, never geometry, rules 81–86) and `communication.json` (Phase 11
  typed CommunicationPayload — deterministic connected communication
  placement baseline owning placement/coverage planning state only, never
  geometry or topology, rules 87–92) and `sensors.json` (Phase 12 typed
  SensorPayload — deterministic monitoring-placement baseline owning
  sensor-placement planning state only, rules 93–98). Invalidation chain
  (rules 64/67/68/74/86/92/98):

      smoothed ──┬── tunnel_mesh
                 └── levels ──┬── network ─┬─ communication
                              │            ├─ sensors
                              └── stopes  ─┴─ timeline
                                  (network + stopes → timeline)

  Tunnel mesh and the levels branch are SIBLINGS of the smoothed centerline:
  a new smoothed (or upstream) artifact deletes tunnel + levels + network +
  stopes; regenerating levels deletes network AND stopes (both rebuilt, never
  patched) and never touches the tunnel; regenerating the network deletes
  `timeline.json`, `communication.json` AND `sensors.json`; regenerating
  stopes deletes only `timeline.json` (communication, sensors and timeline
  are SIBLINGS below the network — stopes/timeline regeneration never
  touches communication or sensors); regenerating the timeline,
  communication or sensors touches nothing upstream and none of the other
  siblings. Regenerating any stage deletes every downstream artifact
  (rules 64/67/68/74/79/86/92/98).
- Long-running work (rule 60): `services/job_service.py` — in-memory
  registry + 2-worker thread pool; one job per scenario at a time. Algorithms
  emit `ProgressEvent`s through a plain callback (`design/progress.py`);
  the job service records them; `GET /jobs/{id}` and `/ws/jobs/{id}` expose
  them. Jobs capture an input-revision fingerprint and re-verify it under
  the per-scenario store lock before persisting; mutated inputs →
  `JOB_INPUTS_CHANGED`, nothing written (rule 60). Job state is lost on
  restart (v0.1). No queue, no database.

## Non-goals (v0.1)

Production reserve estimation, regulatory certification, full geostatistics,
FEM/DEM, CFD ventilation, full-wave RF, dispatch optimization, NPV
optimization, multi-user, photorealism. APIs are shaped so these can be
attached later (`simulation/interfaces.py`).

## Phase 13 — first-person walkthrough runtime (rules 99–104)

WALKTHROUGH mode is an ephemeral frontend runtime over existing
backend-authored geometry — nothing about it is persisted and no backend
artifact, endpoint or invalidation relationship was added. The runtime
mounts only in walkthrough camera mode (OrbitControls and the pointer-lock
controller never coexist), uses one upright collision-constrained Rapier
capsule under gravity (walking from camera YAW only; pitch never flies; no
jump/fly/noclip), and spawns deterministically from the effective decline
portal end (rule 102 — no world-origin fallback).

**Collision boundary (rule 100)**: collider triangles come exclusively from
the Phase 06 `tunnel_mesh.glb` primitives — the proven GLTFLoader
representation is one Mesh child per primitive in writer order (segments,
PORTAL_CAP, TERMINAL_CAP) with primitive extras on `geometry.userData` —
transformed only by the canonical mine→Three rotation. Each decline segment
becomes an independently addressable fixed trimesh collider
(`WALK:COLLIDER:SEGMENT:{segmentId}`, plus separately identifiable cap
colliders), so a future Phase 15 can toggle individual segment colliders by
ID without rebuilding the physics world (rule 104). Phase 13 keeps every
segment and both caps active.

**Decline-only scope (rule 103)**: the walkable excavation is the Phase 06
decline ONLY. DRIFT/CROSSCUT developments own centerlines, not volumetric
meshes, and the frontend never inflates them into fake tunnels; timeline,
communication and sensor semantics are untouched. Walkthrough visibility is
DERIVED (tunnel mesh + passive terrain), never a mutation of the user's
stored layers.

## Phase 14 — walkthrough interaction / inspection (rules 105–110)

Interaction is INSPECTION ONLY and entirely ephemeral frontend state: no
backend artifact, endpoint, invalidation relationship or dependency was
added, and no object state is ever mutated. The supported interactable
kinds are exactly the backend-authored **MESH_ROUTER** and **GAS_SENSOR**
selected assets, resolved through their authoritative candidate →
MineNetwork references and filtered to the walkable decline domain by
topology (EDGE candidate → owning edge type RAMP; NODE candidate →
incident to at least one RAMP edge) — never Euclidean proximity, and never
by inventing access into non-volumetric DRIFT/CROSSCUT developments.

Targeting is the first-person camera **center ray** (rule 107): a bounded
runtime interaction distance (10 m) plus authoritative tunnel occlusion
raycast against the exact Phase 06 GLB triangles (the same collider-unit
triangle set Phase 13 physics uses, double-sided, detached from the
scene). An asset focuses only when its ray distance is within range AND
strictly closer than the wall; through-rock interaction is impossible. E
is edge-triggered inspect while pointer-locked; `selectedObjectId` remains
the single canonical selection identity (rule 109) and stale selections
are cleared frontend-side when regeneration removes the asset.

**Static planned-layout semantics (rule 108)**: walkthrough infrastructure
is a planned static layout — installation timing, power, telemetry,
alarms, RF performance and physical sensing are not modeled, and the gas
sensor keeps the Phase 12 network-distance monitoring-proxy disclaimer.
Phase 15 boundary (rule 110): no currentDay/timeline logic exists in the
interaction path; future temporal filtering can wrap the interactable list
without touching the resolver.

## Phase 15 — 4D walkthrough integration (rules 111–118)

Walkthrough now has two explicit runtime contexts. **STATIC_FINAL**
(entering Walk from DESIGN/INFRASTRUCTURE) is exactly the merged Phase
13/14 behaviour: complete decline, both caps, planned router/sensor
interaction. **TIMELINE_SNAPSHOT** (entering Walk from 4D) captures the
Phase 10 `currentDay` ONCE at entry — the workflow is 4D → choose day →
Walk, and the snapshot day, collider set and physical topology stay
immutable for the whole session (rule 112): no playback, no slider, no
hidden time loop inside walkthrough; time changes only by returning to 4D.

**ACTIVE-only volumetric baseline (rule 114)**: the normal 4D orbit view
keeps showing continuous DEVELOPING centerline progress, but first-person
volumetric traversal is deliberately conservative — a decline segment is
walkable exactly from its ACTIVE transition (`stateAt` exact-boundary at
`progressEndDay`) and never before. Partially excavated tunnel volume is
never fabricated; a future phase would need backend-authored temporally
splittable mesh geometry to do better. Availability is resolved ONLY
through each RAMP `DevelopmentTimeline.geometryRef` →
`decline_smoothed.json` segmentIndex with exact runtime identity
validation (`runtime.segmentId == smoothed.levelId`, counts equal, each
index exactly once, ACTIVE indices a portal-prefix); any inconsistency
fails closed (rule 117). Visually, the temporal layer clones the same
cached Phase 06 GLB once and toggles per-primitive visibility from the
proven `geometry.userData` metadata (the static TunnelMeshLayer now reads
the same shared helper); physically, only ACTIVE segment colliders mount,
the portal cap stays active and the terminal cap activates only at full
completion.

**Runtime frontier barrier (rule 115)**: a partial ACTIVE prefix is closed
by one ephemeral cuboid (`WALK:TEMPORAL:FRONTIER:{lastActiveSegmentId}`)
at the exact last-active Phase 05 boundary point, oriented by the
persisted boundary tangent in a gravity-aligned frame and sized from the
Scenario ramp cross-section plus a small margin. It is access-control
geometry — not excavation geometry, never persisted, and rule 100 is
unamended.

**No infrastructure timing inference (rule 116)**: installation timing is
not modeled, so TIMELINE_SNAPSHOT suppresses all planned MESH_ROUTER /
GAS_SENSOR markers, focus, E-inspect and inspector cards; excavation
completion never implies installation. Phase 16 integration boundary: any
future installed-state semantics require backend-authored installation
timing artifacts first.

### Phase 15 browser-acceptance hotfix — keyboard-only walkthrough

Real-browser acceptance of the initial Phase 13–15 runtime failed on
readability and control, so the walkthrough is now KEYBOARD-ONLY: WASD
walks, J/L yaw and I/K pitch (frame-rate-independent, 90/70 deg/s, pitch
clamped ±80°, no roll), R resets and E inspects (STATIC_FINAL only); the
mouse never rotates the camera and pointer lock was removed entirely —
there is no entry click. Movement remains yaw-only under Rapier gravity
(rule 101 unchanged in substance; the pitch-affects-view-only clause now
applies to keyboard pitch). Walkthrough visibility renders ONLY the tunnel
environment (terrain suppressed in both contexts; other modes untouched),
the spawn chainage moved to 6.0 m for a readable first view, the lighting
rig became a modest ambient/hemisphere fill plus a broad soft
camera-following headlamp (no narrow hotspot, no shadows), and the
walkthrough canvas renders at DPR 1 while other modes keep [1, 2]. Tunnel
collision fidelity is deliberately unchanged. A DEV-only ~2 Hz overlay
reports FPS / triangles / draw calls for manual browser measurement.

## Phase 16 — navigation modes, minimap, visual polish (frontend-only)

**Navigation modes** are ephemeral runtime inspection proxies — never
pedestrian biomechanics, vehicle dynamics or UAV flight control, never
persisted. PERSON (walk 2.0, Shift-run 5.8 m/s, gravity), VEHICLE (8/12
m/s along a heading steered by A/D at a bounded 60°/s — no strafing, no
instant flips; elevated 2.2 m inspection eye; gravity) and DRONE (7/13
m/s horizontal from camera yaw, Space/C vertical 5 m/s, gravityScale 0)
all collide with the exact Phase 06 tunnel trimesh plus the temporal
frontier — no mode is noclip, and the DRONE deliberately cannot leave the
excavated volume. Keys 1/2/3 (or HUD buttons) switch modes; switching
clears transient input and remounts the body at the deterministic
mode-specific spawn — the documented safe baseline for mode switching
(never a mid-geometry collider morph, never a world-origin fallback).
Camera look stays keyboard IJKL in every mode; movement remains yaw-only.

**Minimap + telemetry**: a pure SVG overlay (no second Three canvas, zero
GPU draw calls) shows the authoritative effective centerline north-up in
FOLLOW mode (150 m radius), portal/deep-end markers and a compass-bearing
heading arrow; in TIMELINE_SNAPSHOT it receives ONLY the ACTIVE prefix so
future segments cannot even appear. The player writes cheap telemetry
(position/heading/speed/mode) into a shared ref each physics frame; DOM
consumers sample it at 8 Hz and mutate SVG/text attributes directly — no
per-frame React state, no Zustand traffic. The readout shows mine E/N/RL
plus approximate chainage (nearest-centerline scan at the same 8 Hz),
explicitly navigation information, not survey data.

**Rock/joint texture**: the Phase 06 GLB owns stable UVs (u = perimeter
fraction — floor empirically spans u ∈ [0.72, 1.0] — and v = chainage in
metres), so one 512² seamless CanvasTexture is generated per scenario
seed (mulberry32; low-frequency mottling + 2–3 irregular dark joint-trace
families + a subtle darker floor band) and shared by the SAME two tunnel
materials in both the static and temporal layers: deterministic per
scenario, zero image assets, zero additional draw calls. VISUAL ONLY —
not mapped discontinuities, DFN, RMR or any geological claim.

DEV perf overlay moved bottom-right; the bounded sampler now lives in
perfSampler.ts (component files export only components).

### Phase 16 hotfix 2 — acceptance polish (Park-directed)

Browser acceptance follow-ups fixed directly on the Phase 16 branch:
timeline development/stope layers no longer frustum-cull (their
day-rebuilt geometries could vanish at some camera angles); grade blocks
are suppressed in 4D only (the stope sequence is the 4D story — DESIGN
keeps the layer and the stored user toggle is untouched); the four
infrastructure layers (routers, communication coverage, sensors,
monitoring coverage) are default-visible, which only manifests inside
INFRASTRUCTURE mode; router/sensor markers are click-selectable in orbit
(the transient instanceId only looks up the authoritative backend id);
rock-quality labels now state the backend contract — a synthetic
RMR-like 0-100 index, not measured RMR. Navigation: PERSON is an
inspection pace (4.0 walk / 7.0 run m/s); VEHICLE drives WHERE THE
CAMERA LOOKS (A/D steer the camera yaw at a bounded 60 deg/s on top of
IJKL — no hidden heading state); DRONE flies along the full camera
direction (pitch flies), which makes ramp following natural. A level
teleport select ("Go to…") jumps to the portal or any on-decline
LEVEL_ENTRY station via the SAME deterministic spawn rules at the
station chainage — in temporal snapshots the station list derives from
the ACTIVE-prefix centerline, so beyond-frontier entries are never
offered. The minimap gained a longitudinal CH-RL profile strip fed by
the same ACTIVE-prefix chainage points.

Deferred to Phase 17+: orebody/fault randomization, irregular orebody +
regularized ramp patterns, third-person/truck view, true 3D minimap,
drone tunnel-relative altitude, access-target concept revisit, Analysis
mode (reserved since Phase 01).

## Phase 17 — deterministic geology & orebody scenario engine

Scenario REALIZATION is now an explicit non-persistent step (rule 119):
`POST /scenarios/realize` maps preset + seed (+ fault count) to a fully
resolved ScenarioCreate that the client inspects and then submits to the
ordinary create endpoint, so `generate_world` keeps its pure contract and
a persisted scenario reproduces its world forever. Presets: BASELINE (the
exact Phase 16 user-facing mine — backend-default tabular orebody plus
the fixed fault — with zero random draws), RANDOM_TABULAR and
RANDOM_ELLIPSOID. Draws come from NEW independent seed sub-streams
(orebody 0x0B0D17, faults 0xFA0117; rule 121) so the existing terrain /
rock / grade streams — and therefore every existing world — are
bit-identical. Realized faults must demonstrably cut the model volume
(clip_to_box, bounded deterministic retries, typed failure; rule 122).

ELLIPSOID is the first non-tabular orebody: the triaxial ellipsoid
inscribed in the equivalent tabular slab (semi-axes = length/height/
thickness ÷ 2 in the same strike/dip frame), so the persisted schema is
unchanged (schema_version stays 1). Its signed distance is the EXACT
Euclidean distance via the classic largest-root equation solved with a
deterministic bisection (axis-plane degeneracies handled with a 1 nm
clamp, error ≪ 1e-6 m); contains / volume (4/3·π·abc) / closed-form
rotated AABB / UV-sphere mesh with every vertex on the analytic surface
all describe the SAME solid (rule 120). True free-form irregular bodies
were DEFERRED here because without a metric SDF they would poison the
engineering buffers; Phase 19 resolves that with an explicit
implicit-body contract (below) rather than by faking an SDF. The legacy
design pipeline remains TABULAR-only behind a typed 422
(UNSUPPORTED_OREBODY_FOR_LEGACY_LAYOUT; rule 123) until the Phase 20
generalized layout (Parametric Layout Family Search).

Frontend: the Scenario panel gained Preset / Seed / fault-count controls
with a Randomize preview that shows the backend-realized parameters
verbatim (rule 124 — the client never draws or computes geometry), and
the design panel disables target generation with an explanatory notice
for non-tabular scenarios. The 'one fault' checkbox is superseded by the
BASELINE preset, which reproduces it exactly.

### Phase 17 acceptance hotfix

Two acceptance blockers closed on the Phase 17 branch. (1) The scenario
panel now realizes into an EDITABLE draft: Randomize calls the backend and
seeds the draft, an Advanced section exposes the explicit orebody (type
restricted to the implemented TABULAR/ELLIPSOID), grade, rock-quality and
per-fault parameters (add/remove within the backend 0-6 contract), and
Create submits the edited draft verbatim — never a fresh realization over
user edits. Changing preset, seed or fault count invalidates the draft so
a stale preview can never be mistaken for the new inputs; the client still
contains no randomness and derives no geometry (rule 124). (2) Randomized
orebody acceptance now tests the ACTUAL analytic solid —
`build_orebody(cfg).bounding_box()` against the world bounds with the
intended 80 m horizontal and 40 m top margins — because strike/dip
rotation means a centre-only test proves nothing; invalid candidates are
rejected whole and retried deterministically (budget 64), never clamped
(rule 125).

### Phase 18 — Spatial Field Core

Core-representation migration, not a rename. The world is now

    Scenario → Terrain → authoritative Orebody solid → FieldGrid
             → SpatialFieldSet {rock_quality, grade, fault_signed_distance,
                                fault_zone, fault_influence; terrain_support}
             → engineering consumers

`BlockModel`, `BlockModelConfig`, `RockType`, `ore_fraction`, `ore_flag` and
`rock_type` are gone (rule 127). The 10 m lattice remains numerically
identical but is described only as numerical field spacing
(`scenario.fieldSampling`, schemaVersion 2 — v1 documents are migrated on
first read and lose their derived artifacts; a Phase-17 `arrays.npz` is
rejected with 409 WORLD_ARTIFACT_INCOMPATIBLE, never reinterpreted).

The public field API is batch-first: `RegularScalarField.sample(N×3)` is
the trilinear interpolation the Phase-17 evaluator used to own, now a
property of the field (rule 128). The near-surface behaviour that used to
be "fill AIR blocks from the column top" is the field's `COLUMN_TOP_FILL`
terrain boundary policy driven by a per-cell terrain-support fraction — an
interpolation policy, not a rock classification. Because the arithmetic is
unchanged, the golden suite shows decline, smoothing, level, network and
timeline results that are numerically identical within the golden tolerance
(1e-9 relative) before and after the migration — a contract-equivalence
result over the recorded engineering metrics, not a byte hash of the
artifacts (`backend/golden/phase18_vs_phase17.md`).

Only one number changed by design: the longhole planning grade proxy no
longer weights ore-flagged cells by `ore_fraction`; it samples the grade
field on a deterministic equal-volume quadrature of the stope prism ∩
orebody solid ∩ below terrain (rule 130). The orebody solid is the only
membership authority (rule 129): the grade field is defined everywhere and
the scene ships a slice display mask instead of ore blocks. That mask marks
the display CELLS that INTERSECT the solid (centre inside, or a deterministic
3³ sub-sample inside, bounded by the cell half-diagonal); it is named
`OREBODY_INTERSECTION_BELOW_TERRAIN` precisely because a proximity or
intersection test must never be presented as point membership. World stats are
neutral field diagnostics — no block counts, no sampled ore tonnes, no mean
ore grade, no in-situ orebody tonnes (rule 131).

Task 0 of the phase was the golden-scenario harness
(`python -m minegen.regression`, rule 132): 22 fixed cases (5 BASELINE,
12 RANDOM_TABULAR with 0–3 faults, 5 world-only RANDOM_ELLIPSOID that fail
the legacy layout deterministically), a HARD CONTRACT / QUALITY METRIC
split, committed Phase-17 baseline, a machine-readable comparison and a
3-case smoke subset in ordinary CI. Frontend: the Grade-blocks layer, the
`oreBlocks` / `blockGrid` payloads and the `oreFraction` slice are removed;
Field Slice stays an explicit default-OFF layer, now masked by the backend;
the Parameters panel shows "Field sampling · numerical spacing" instead of
"Block".

### Phase 19 — Implicit Geological Orebody (WARPED_VEIN)

The smooth ellipsoid stays as the analytic geometric reference; the
realistic-looking non-tabular demonstration is now a deterministic,
geologically plausible SYNTHETIC irregular body that is a TRUE
authoritative solid:

    resolved ScenarioCreate.orebody.warpedVein   (shapeModelVersion = 1)
        ↓ smooth low-order morphology fields on the strike/dip frame
    authoritative implicit function φ(u, v, w)      contains := φ <= 0
        ├── conservative analytic bounding box       (constructor-time)
        ├── deterministic numerical volume           (2-D midpoint quadrature)
        ├── DERIVED approximate signed clearance     (lazy lattice + EDT)
        └── DERIVED render mesh                      (lazy marching cubes)

Honest contract split (`world/orebody.py`, rule 134): `AnalyticOrebody`
(TABULAR, ELLIPSOID — `signed_distance` is the EXACT Euclidean SDF) and
`ImplicitOrebody` (WARPED_VEIN — `level` = φ, `approximate_clearance`
with explicit spacing / error metadata, never called an SDF). The
generic `Orebody` interface is shape-neutral: `half_thickness` and
`footwall_point` moved to `TabularOrebody`, and the legacy targets /
levels / stope code is typed against that class, unchanged in
behaviour (golden suite identical). `DesignCostEvaluator` accepts only
`AnalyticOrebody` (`ExactDistanceRequiredError`); the service maps that
to UNSUPPORTED_OREBODY_FOR_LEGACY_LAYOUT (422, Phase 20 explanation) for
targets AND cost evaluation, so an approximate clearance can never
weaken the hard orebody buffers (rule 135).

Shape model 1 (`world/warped_vein.py`, rule 139): weight-normalized
harmonic modes (wavenumber ≤ 3 on the body extent) drive a laterally
deviating centreline, an asymmetric superellipse planform with four
independently modulated edges, a warped mid-surface and a pinch-and-swell
thickness multiplier `1 + V·g` whose floor `1 − V ≥ pinchFloorRatio` holds
by construction; terminations taper as `sqrt(1 − P^k)`, `k = 2/edgeTaper`.
φ = ((w − w_mid)/(T/2·m))² + P^k − 1 is single-valued over the frame (no
overhangs) and the planform is verified connected at realization.
Volume is the deterministic 2-D quadrature of the exact w-extent `2h`
(no Monte Carlo; converges to < 1e-4 between 1 m and 0.5 m; independent
3-D lattice count and closed-mesh signed volume agree within 2 %).

Derived geometry (rule 138) lives on its OWN lattice (`geometryResolution`
in-plane, across-thickness spacing ≤ floor thickness / 3, padded, capped
at 6 M cells with an explicit `OREBODY_GEOMETRY_BUDGET_EXCEEDED`), never
on `fieldSampling`. Clearance = signed Euclidean distance transform of the
lattice classification, trilinear query, sign forced to agree with
`contains`. Mesh = scikit-image marching cubes (Lewiner; the only new
dependency — a hand-written triangulator would be fragile for no
benefit), welded, watertight, outward, vertices rounded to 1 mm for
transport. Construction is ≈ 10 ms (cheap enough for the realizer's
bounded retries); the derivatives are built lazily and cached.

Realization (`RANDOM_WARPED_VEIN`, rule 136): the SAME orebody sub-stream
(0x0B0D17, no new key) draws location / orientation / nominal
dimensions, then every scalar control and every mode coefficient;
candidates pass the identical world-fit AABB gate (rule 125) plus a
morphology acceptance on cheap 2-D diagnostics (one connected planform,
floor respected, pinch/swell range ≥ 0.15, warp ≥ 50 % of amplitude,
edge asymmetry ≥ 5 %, geometry budget) and are rejected whole otherwise.
Existing presets are bit-identical. The persisted document alone — with
its `shapeModelVersion` (rule 137) — reproduces the solid; `schemaVersion`
stays 2 because the block is additive and no v2 meaning changed.

Frontend: preset "Randomized · irregular warped vein"; ellipsoid is
labelled a geometric reference shape; the Advanced editor exposes warp
amplitude, centreline deviation, outline irregularity, thickness
variability, pinch floor and edge taper (plus a collapsed read-only view
of the resolved modes) and never fabricates coefficients — WARPED_VEIN is
reachable only through realization, and leaving it discards the
morphology; readouts say "nominal thickness"; the layer shades the
backend isosurface smooth (edge wireframe only for analytic bodies);
`designSupported` stays false with the Phase 20 notice. A separate
world-only golden suite (`python -m minegen.regression warped-vein`,
12 seeds, baseline `golden/phase19_warped_vein.json`, smoke subset in CI)
records bbox, volume, mesh counts, watertightness, clearance resolution,
thickness range, morphology diagnostics and timings; WARPED_VEIN is never
fed through the legacy decline pipeline to populate metrics. The existing
22-case golden suite re-run after the phase
(`golden/phase19_full.json`, comparison `golden/phase19_vs_phase18.md`)
shows 0 HARD CONTRACT regressions and 0 metric changes against
`phase18_after_migration` — the TABULAR pipeline and the ELLIPSOID typed
rejection are unchanged. This is a
synthetic morphology model — not a measured orebody, not resource or
reserve estimation, not kriging, not an imported block model, not a
digital twin.

### Phase 20A — Parametric Whole-Mine Layout & Access Network v2 (families + Effective Ramp)

Phase 20 is split: 20A (this phase) delivers the parametric ramp-family
search and the source-neutral Effective Ramp; 20B–20D (generalized level
development, local bounded refinement, rulebook comparison) follow. The
legacy chained Hybrid-A* pipeline is untouched and stays the default.

    scenario.layout (typed finite grids, 3 group weights)   ← rules 142/148
        ↓ enumerate_candidates  (SPIRAL 36 · LONGITUDINAL 8 · SWITCHBACK 24 = 68)
    families.py  closed-form primitives from the authoritative portal
        SPIRAL        R = ΔZ/(2π·g·n), drifting helix along the footwall track
        LONGITUDINAL  one-direction along-strike descent, corridor clipped to the world
        SWITCHBACK    stacked antiparallel legs, L = ΔZ/(k·g) − π·R_min, constant hairpin sense
        ↓ delivered polyline (sampleSpacing 2 m)             ← rule 144
    geometry.py   per-edge gradient, chord plan radius, unwrapped heading,
                  family signatures, exact level crossings          ← rule 145
    levels.py     required levels = generate_level_elevations (rule 141);
                  in-plane footprint sections on `contains` + KD-tree + bisection
                  (upper-bound access distance)                     ← rule 144
    search.py     STAGE 1 enumerate → 2 cheap (grade, radius, bounds, monotone,
                  level service) → 3 shortlist (12) → 4 detailed
                  (shared DesignCostEvaluator sample validator + clearance policy
                  + exposure + 3-group scores) → 5 ranking            ← rules 147/148
        ↓ layout_v2.json (catalogue) · layout_v2_selected.json (materialized winner)
    services/effective_ramp.py   ramp_source.json → LEGACY | LAYOUT_V2   ← rules 149–151
        ↓ ONE Effective Ramp (Phase 05 shape + sourceKind/owningArtifact/sourceRevision)
    tunnel → levels → network → timeline → communication / sensors → walkthrough

Clearance policy (`design/cost_field.py`, rule 146): `ExactClearance`
(analytic SDF; the legacy constructor path is byte-identical) and
`ConservativeClearance` for implicit bodies, `safe = approximate −
1.5·‖lattice spacing‖` (10.77 m for the default WARPED_VEIN lattice; the
measured over-estimate of the Phase 19 approximation against the derived
mesh is ≤ 3.6 m after the far-field fix in `warped_vein.py`: outside the
lattice the clearance is now `hypot(edge value, box distance)`, a lower
bound, where the previous additive form over-estimated by up to 67 m).
WARPED_VEIN therefore runs the whole layout-v2 search (candidates, level
service on the authoritative solid, conservative clearance, ranking,
winner, rendering) while the legacy pipeline still answers
UNSUPPORTED_OREBODY_FOR_LEGACY_LAYOUT; its drifts / crosscuts / walkthrough
are Phase 20B.

Level service (directive §6): a candidate serves level L iff its delivered
centerline crosses z = zL (segment interpolation, no tolerance) and the
horizontal distance from the crossing to the orebody footprint at zL is
≤ `accessReach` (60 m) and the crossing is an accepted sample of the
detailed validation; unserved levels carry NO_RL_CROSSING /
NO_OREBODY_SECTION_AT_LEVEL / ACCESS_REACH_EXCEEDED /
CONNECTION_POINT_INVALID. The generic level generator works from the
bounding box, so an implicit body can own required levels without a
section (reported `hasOrebodySection = false`, excluded from the
serviceable set) — a documented discrepancy, not a second generator.

Effective Ramp (rules 149–150): downstream builders take the ramp payload
plus its owning artifact; `MineNetworkBuilder.build(..., geometry_artifact)`
writes RAMP `geometryRef.artifact` as `decline_smoothed.json` or
`layout_v2_selected.json`, and scheduling / infrastructure resolve either.
`WorldService.scene()` ships `smoothedDecline` = the ACTIVE ramp (legacy
adapter view or the selected candidate), `legacySmoothedDecline`,
`rampSource`, a slim `layoutV2` catalogue and `layoutV2Selected`. Every
downstream fingerprint includes `decline_smoothed.json`,
`layout_v2_selected.json` and `ramp_source.json`, so selecting, activating
or switching is a new input revision (rule 151). Frontend: `LayoutPanel`
(source radio, candidate job, ranked list with Development / Geology /
Geometry totals, Select / Activate), `SmoothedDeclineLayer` colours
PARAMETRIC_V2 segments amber with `L01…` connection labels,
`LayoutSelectedLayer` previews a selected-but-inactive candidate,
`temporalPlan.rampOwningArtifact` resolves RAMP refs through the owning
artifact. Golden: `python -m minegen.regression layout-v2` (4 cases,
baseline `golden/phase20a_layout_v2.json`, smoke in CI) alongside the
untouched legacy suite (`golden/phase20a_full.json`, comparison
`golden/phase20a_vs_phase19.md`).

### Phase 20B — Ramp Junctions, Level Access Drives, Mining-Method-Aware Level Development

Phase 20A's downstream treated the main ramp's crossing of a level RL as
the level entry — a whole-mine simplification that is not a truck-access
topology. Phase 20B replaces it with the physical route

    PORTAL → RAMP → RAMP_JUNCTION (turnout) → LEVEL_ACCESS → LEVEL_ENTRY
           → level / footwall drift → JUNCTION → CROSSCUT → STOPE_ACCESS

and distinguishes five concepts (rules 153–160): the MAIN RAMP (Effective
Ramp), the RAMP LEVEL REFERENCE (an RL crossing — diagnostics and the
stage-2 access-potential screen only), the RAMP JUNCTION (a turnout that
becomes a topology node), the LEVEL ACCESS (a validated branch drive with
its own centerline) and the LEVEL ENTRY (the branch terminal where the
level development starts).

`layout/access.py` owns the engineering:

* `LevelDevelopmentAnchor` — the development location a branch must reach:
  the footwall backbone at `anchorStandoff` from the footwall edge (exact
  rule 43 line for TABULAR, the numerical level section's principal axis
  and footwall-side extent for implicit bodies), the entry placed by the
  explicit NEAREST_TO_RAMP policy (backbone point closest to the ramp's
  level reference, clamped inside the extent), the terminal heading along
  the backbone toward its centre, the mining method and diagnostics. Under
  a CONSERVATIVE clearance policy the stand-off is raised to
  `required + errorBound + 1 m` so the entry itself is clear.
* `plan_level_accesses` — per serviceable level: a finite lattice of ramp
  junction candidates every `junctionSearchSpacing` (10 m) whose ramp
  elevation lies within `junctionWindowAbove` (45 m) / `junctionWindowBelow`
  (10 m) of the level and within `maximumAccessLength` of the anchor; for
  each candidate and both terminal senses a G1 Dubins CSC connector
  (LSL/RSR/LSR/RSL, R = minTurnRadius, exact endpoints, z linear in
  delivered chord length so every edge carries one gradient); rejection
  reasons NO_JUNCTION_IN_WINDOW, GRADE_LIMIT, TURN_RADIUS, ACCESS_TOO_SHORT /
  LONG, WORLD_BOUNDS, SURFACE_COVER, RESTRICTED_ZONE, OREBODY_CLEARANCE,
  ENVELOPE_INVALID (profile boundary points through `envelope_masks`),
  JUNCTION_SPACING_CONFLICT (`minimumRampJunctionSpacing`, 40 m);
  deterministic selection = min (length, junction chainage, sense). No
  clamping, no optimizer, no randomness.
* Search integration (`layout/search.py`): stage 4 plans accesses for every
  validated shortlisted main ramp; a level without a valid access makes the
  candidate INFEASIBLE (LEVEL_ACCESS_INFEASIBLE); Development score counts
  `mainRampLength + levelAccessLength`; `accessibleLevels`, the access
  summary (total / worst / max gradient / min radius / failures) and the
  per-level accesses are reported. `materialize_effective_ramp` splits the
  main ramp at the ramp junctions (+ `RAMP_END` tail, `segmentId`,
  `rampJunction`, `terminalKind`); `materialize_level_accesses` writes the
  sibling artifact.

Artifacts and downstream (rules 155, 160, 162): `layout_v2_selected.json`
(main ramp) and `level_accesses.json` (junctions, branches, anchors) are
written together by the selection under one revision; `levels.json` takes
its LEVEL_ENTRY positions from the accesses (`entrySource = LEVEL_ACCESS`,
LEVEL_ACCESSES_REQUIRED otherwise) and reports
`productionDevelopment` — LONGHOLE keeps the station / crosscut lattice,
every reserved method (CUT_AND_FILL first) gets the generic backbone drift
and an explicit UNSUPPORTED_METHOD production status. MineNetwork emits
RAMP_JUNCTION / RAMP_END nodes and LEVEL_ACCESS edges (geometryRef →
`level_accesses.json`); scheduling adds DEVELOP_LEVEL_ACCESS tasks that
depend on the ramp task reaching their junction and root each level there;
the infrastructure domain resolves LEVEL_ACCESS geometry through its
owner. The LEGACY Phase 05 path is unchanged (segment ends stay entries).

Phase 20A closeout: the plan-radius estimator is now the three-point
circumradius `|p_{i+1} − p_{i−1}| / (2 sin δ_i)` (exact for any sampling
of a circular arc), so a true R_min hairpin sampled at 5 m is accepted
(rule 161).

Frontend: `LevelAccessLayer` (branches, junction spheres, entry cubes with
labels), RAMP_JUNCTION / RAMP_END / LEVEL_ACCESS in the network and 4D
layers, ramp segment labels "turnout" / "ramp end", `LayoutPanel` access
summaries (accessible levels, total / worst access, max gradient, min
radius, per-level junction chainage or failure), `rampSegmentId` identity
for the walkthrough / minimap. Golden: `golden/phase20b_layout_v2.json`
(6 cases incl. ACCESS-INFEASIBLE and CUT_AND_FILL) records junction
chainages, entries, access lengths / gradients / radii and typed failures;
`golden/phase20b_full.json` re-runs the legacy suite.
