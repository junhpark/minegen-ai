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
      world/           terrain, orebody, block model, geology (rock quality,
                       faults), voxel grid
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
    02 Synthetic world (terrain, orebody, block model, rock quality, faults)   done
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
    15 4D walkthrough ← current
    14 Walkthrough object interaction
    15 4D walkthrough integration
    16 Integrated v0.1 demo

## Scenario document shape

    scenario
     ├─ world          size_x, size_y, depth (below terrain reference elevation)
     ├─ terrain
     ├─ orebody
     ├─ geology
     │    ├─ rockQuality
     │    └─ faults[]   (half-widths from the plane)
     ├─ blockModel
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
