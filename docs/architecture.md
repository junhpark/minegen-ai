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
    05 Ramp smoothing + revalidation   ← next
    06 Tunnel mesh (gravity-aligned sweep)
    07 MineNetwork
    08 Levels & crosscuts
    09 Stopes & mining method
    10 4D mining sequence
    11 Communication OSP
    12 Generic sensor OSP
    13 First-person walkthrough
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
     └─ mining

Future geology members (water, lithology, alteration, joint sets, stress)
go under `geology`, not at the scenario root.

## Persistence and jobs (v0.1)

- Scenarios: `data/scenarios/{id}/scenario.json` + `arrays.npz` + `derived/`.
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
