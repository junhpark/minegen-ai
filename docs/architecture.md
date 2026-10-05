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

Verified at the consolidation baseline (`docs/consolidation-baseline.md` §5,
main `d58c794`), with per-package sizes and entry points. Earlier revisions of
this map attributed the tunnel sweep to `geometry/` and described
`simulation/` as solver adapters; both were aspirational and are corrected
here. Per-phase decision records below keep their original wording.

    minegen/
      core/            enums, Pydantic models, coordinate utilities, units,
                       derived-artifact filename constants
      world/           terrain, authoritative orebody solid (analytic +
                       implicit), numerical field lattice (FieldGrid),
                       SpatialFieldSet (rock quality, grade, fault
                       measurements; batch sample()), geology generators
      design/          cost field + clearance policies, level access targets,
                       motion primitives, chained Hybrid-A* decline generator,
                       smoothing + shared sample validation (Phase 05), tunnel
                       profile, tunnel mesh and development mesh
                       (gravity-aligned sweeps), constraints
      layout/          parametric layout v2: family enumeration and geometry,
                       delivered-centerline validation, section / footwall
                       trace, level-access planner, construction
                       ServiceReference, staged search and ranking
      levels/          level development builder (drift / crosscut) + payload
      network/         MineNetwork graph, builder, metrics
      shafts/          Phase 20C.2B vertical shaft planner + shafts.json contract
      capability/      Phase 20C.2B capability graph (semantics over network ids)
      assessment/      Phase 20D.3 design assessment read model (rule 189: a
                       READ-ONLY projection of the layout-v2 catalogue,
                       selection, ramp source and capability graph — never
                       persisted, never a design authority)
      analysis/        Phase 22A/B mine analysis read model (rules 197–202):
                       models (typed sections with AVAILABLE / NOT_AVAILABLE /
                       NOT_CONFIGURED), integrity (READ ≠ TRUST cross-artifact
                       checks → ANALYSIS_SOURCE_INCONSISTENT), builder (pure
                       projection: development / production / schedule /
                       ratios / economics), economics (user-authored
                       economics.json beside the scenario, sha256 revision,
                       rates), cashflow (bucket ledger, overlap allocation,
                       mid-bucket NPV); never a derived artifact.
                       layout_comparison (Phase 22C, rules 204–206): the
                       Comparable Layout Development Cost over the PERSISTED
                       layout-v2 candidate quantities — pure builder, shared
                       assessment score helpers, consumer-specific catalogue
                       shape extension; the Rules tab reuses assessment/
      mining/          Phase 21A/21B/C mining-method core (rules 192–196): methods/registry.py
                       (plan_for — the ONE dispatch authority), methods/contracts.py
                       (MiningMethodPlan protocol, access patterns, production schedule spec),
                       methods/longhole.py (longhole open stoping strategy + plan),
                       methods/cut_fill.py, methods/room_pillar.py (Phase 21B/C plans),
                       methods/solids.py (shared prism / QA / grade helpers),
                       methods/schedule_support.py, methods/unsupported.py
                       (explicit UNSUPPORTED_METHOD plans), stope models
      scheduling/      MineTask, dependencies, scheduler, timeline state
      infrastructure/  shared network domain, candidate sites, demand points,
                       coverage models, placement solver
      regression/      golden suites, comparisons and audits (CLI)
      export/          scene manifest, JSON, glTF
      exchange/        Phase 23A MineExchange v1 (rule 190): read-only
                       projection of authoritative state into a versioned,
                       deterministic bundle — DTOs (models), builder,
                       bundle (ZIP + manifest integrity), geometry
                       projections (terrain, orebody, faults, centerlines,
                       closed excavation solids through the production
                       sweep helpers), pure format writers (STL, OBJ,
                       GLB, DXF, ASC, CSV, JSON) and the typed projection
                       failure (errors.py, 409 MINE_EXCHANGE_EXPORT_FAILED);
                       network geometryRefs resolve through
                       network/geometry_refs.py; docs/mine-exchange.md
      adapters/        Phase 23B external application adapters (rules
                       207–212): manifest-driven MineExchange bundle reader
                       (integrity, DTO validation), AdapterManifest contracts
                       (five-state sources, assumptions, identity map), typed
                       ADAPTER_* failures, deterministic package writer,
                       shared consumption helpers (common.py), the plain
                       registry table (registry.py); ventsim/ (geometry /
                       network seed), anylogic/ (operational data package),
                       engine/ (GLB root-transform patcher + Unity / Unreal
                       import packages); docs/external-adapters.md §23
      results/         Phase 23C external simulation results (rules
                       213–218): MineResult 1.0 DTOs (models), package
                       reader with explicit budgets (package.py), Ventsim /
                       AnyLogic importers (importers/), canonical
                       normalization + deterministic resultId
                       (normalization.py), source-snapshot edge geometry +
                       chainage projection (geometry.py), frame builders
                       (frames.py), atomic results/ store OUTSIDE derived/
                       (store.py), canonical re-export (export.py), typed
                       RESULT_* failures; services/result_service.py binds
                       imports to ExchangeService.observe_source_snapshot /
                       observe_edge_centerlines; docs/simulation-results.md
      services/        scenario persistence, world / design / infrastructure
                       orchestration, async job service
      api/             FastAPI routers (thin; no algorithms)
      geometry/        RESERVED namespace — empty, zero importers
      simulation/      RESERVED namespace — empty, zero importers; no solver
                       and no adapter exists

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

## UI information architecture (Phase 20E)

Top-level application modes (the `AppMode` enum is unchanged; the
`INFRASTRUCTURE` value is labelled "Systems"):

    Design | Systems | 4D | Walkthrough | Analysis

Left panel:

    Scenario                     summary + ⓘ, Details / New scenario /
                                 Saved scenarios disclosures, MineExchange
                                 export and its current-contents readout
    workflow tabs                Design:  Layout → Develop → Network → Mining
                                 Systems: Communication | Sensors
    Layers                       viewer control, always reachable, collapsed
                                 by default (SliceControls stays mounted)

Design tab contents:

| Tab | Cards |
| --- | --- |
| Layout | Mine layout (candidates, selection, activation), Design assessment, Legacy decline (Hybrid-A\*) — Advanced |
| Develop | Level development, Development mesh, Ramp tunnel mesh, Shafts |
| Network | Mine network, Capabilities (two separate cards: geometry ≠ topology ≠ capability) |
| Mining | Mining method (registry selector + explicit method parameters, Phase 21B/C — Apply = scenario PUT + world regeneration), Production (method-generic action), Schedule |

Every card follows one layout: `title + ⓘ` and a status badge, then the key
metrics, then the action, then `Details ▸`. Status, key metrics and any
backend `failureReason` are ALWAYS visible; only detailed numbers move into
`Details`, and only legacy / diagnostic controls move into `Advanced`.
Technical explanations live in the ⓘ popover
(`components/ui/InfoPopover.tsx`), never as paragraphs in the primary view,
and an ⓘ never holds an action.

The primitives are `components/ui/`: `InfoPopover`, `PanelTabs`,
`StatusBadge`, `Disclosure`, `ActionButton`, `MetricRow` / `Metrics` and the
composing `WorkflowCard`, with the presentation mappings (`artifactTone`,
`nextActionVariant`) in `presentation.ts` and the pure interaction rules in
`interaction.ts`. `StatusBadge` is a PRESENTATION MAPPING of the backend
artifact status — no new status vocabulary exists.

Tab identity is frontend-local viewer state (`viewerStore.designTab` /
`systemsTab`): it is never persisted to a scenario, and switching a tab
issues no request. Every panel stays MOUNTED for every tab and renders only
in its own context (`active` / `view` props), so each job poll, query and
effect keeps its pre-20E lifetime.

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
  CROSSCUT geometry, rule 71), `shafts.json` (Phase 20C.2B typed
  ShaftsPayload — the validated geometry artifact owning shaft axes,
  stations and station drives, rule 182; optional), `capability_graph.json`
  (Phase 20C.2B typed CapabilityGraphPayload — capability semantics over
  MineNetwork ids, no geometry, rule 185), `stopes.json` (the ACTIVE production artifact — Phase 09 StopesPayload / Phase 21B/C
  CutFillPayload / RoomPillarPayload, one method-typed union at the legacy path, rules 75, 194), `network.json` (Phase 07/08 typed
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
- "Reset from here" (hardening H1 §4.4): the same registry closure, run on
  request instead of after a write. `services/workflow_stages.py` is the
  ONE stage → artifact table (WORLD · TARGETS · DECLINE · SMOOTH · LAYOUT ·
  LEVELS · EXCAVATION · SHAFTS · NETWORK · CAPABILITY · PRODUCTION ·
  SCHEDULE · COMMUNICATION · SENSORS) and `reset_plan(stage, source,
  derived_dir)` is the ONE function: the stage's own artifacts plus
  `invalidated_by(own, active source)`, filtered to the files present on
  disk. `GET …/design/reset-plan?from=<stage>` returns that plan (read-only;
  the confirm dialog lists `willDelete`); `DELETE …/design/stages/{stage}`
  computes the same plan under the scenario lock and unlinks exactly it
  (maximal loop, one OSError afterwards, like the write cascade), dropping
  the in-memory caches keyed on the deleted artifacts. STALE / MALFORMED
  artifacts are deleted without being read (a recovery path);
  `ramp_source.json` is never a stage target (rule 162); WORLD is a
  preview-only root (its reset is the scenario PUT / world regeneration,
  rules 40 / 46 — `RESET_STAGE_NOT_DELETABLE`); a stage none of whose own
  artifacts exist is `RESET_TARGET_NOT_GENERATED` (404). An unusable
  `ramp_source.json` plans the UNION of both chains, never a guessed
  LEGACY (AC-01F A7). The frontend sends a stage id and empties the scene
  slots named in `deleted[]` (`scene/artifactSlots.ts`, a file → slot
  presentation mapping); it carries no dependency graph beyond the two
  Effective-Ramp identity halves of rule 169.
- Long-running work (rule 60): `services/job_service.py` — in-memory
  registry + 2-worker thread pool; one job per scenario at a time. Algorithms
  emit `ProgressEvent`s through a plain callback (`design/progress.py`);
  the job service records them; `GET /jobs/{id}` and `/ws/jobs/{id}` expose
  them. Jobs capture an input-revision fingerprint and re-verify it under
  the per-scenario store lock before persisting; mutated inputs →
  `JOB_INPUTS_CHANGED`, nothing written (rule 60). Job state is lost on
  restart (v0.1). No queue, no database.

## Validated artifact read authority (AC-01F)

READ ≠ TRUST. Every persisted derived artifact is read through ONE authority,
`backend/src/minegen/services/artifact_reader.py`: one generic read ALGORITHM
(exists → lock-held bytes + stats → parse → payload model / first-level shape
→ provenance agreement with the OTHER observations of the same snapshot →
typed state) over a per-artifact SPEC TABLE (`READ_SPECS`). Every direct GET,
every builder's upstream read, both GLB routes, the async job path and the
scene classify an artifact identically:

| state | meaning | direct route | `GET …/scene` |
|---|---|---|---|
| ABSENT | the fingerprint file does not exist | its own `*_NOT_GENERATED` code | `null` |
| VALID | parses, satisfies its model / shape, passes every provenance check of the SAME snapshot (a `status: "FAILED"` payload is VALID) | 200 | the payload |
| STALE | well-shaped, but a persisted provenance field disagrees with the live revision of the upstream file it names, or a co-published pair disagrees | 409 (rule-named code where one exists, else `ARTIFACT_STALE`) | the whole scene is refused |
| MALFORMED | present but not a usable document (unreadable bytes, not a JSON object, failed model / shape, incomplete two-file unit, GLB bytes ≠ the report's content hash) | 409 `ARTIFACT_MALFORMED` | the whole scene is refused |

ABSENT is expected and quiet; STALE and MALFORMED are loud on every surface.
There is no third outcome — no partial projection, no fallback to raw, no
repair. Repair is always an explicit user write (regenerate, `PUT
…/design/ramp-source`, regenerate the world), never a read.

**Ownership split (the registry is NOT the resolver).**

| concern | owner |
|---|---|
| artifact names, which files one artifact owns, ORDERED fingerprint inputs, ramp-source gating, the invalidation closure | `core/artifact_registry.py` (leaf, unchanged) |
| read, parse, model / shape validation, freshness (stat) comparison, provenance agreement, read-state typing, the lock-held snapshot | `services/artifact_reader.py` |
| the writer protocol (capture → build → lock → re-check → write → cascade) | `world_service` / `design_service` / `infrastructure_service` |
| wire mapping (status + code) | `api/errors.py`, one `guard` table for all four routers |

The reader CALLS the registry (`derived_artifacts()` = what a snapshot
captures, `spec(name).files` = the two-file units, `invalidated_by()` = the
consistency test) and the registry never calls the reader or holds a read
semantic. A test asserts that every provenance link the read specs declare is
an edge the registry owns.

**The snapshot boundary.** A builder's reads are coherent-or-rejected (it
captures a rule-60 fingerprint before its reads and re-checks it under the
publish lock), but the scene publishes nothing, so it gets ONE explicit
boundary:

    GET /scene
      scenario, world, srev, arev = worlds.load_bound(sid)   # OUTSIDE the lock
      with store.lock(sid):                                  # ONE hold: stats + bytes
          re-stat scenario.json / arrays.npz; observe every registered file
          mismatch → release, repeat load_bound (at most 3 attempts)
      # OUTSIDE the lock: parse, validate, provenance-check, assemble

`generate_world`, `np.load`, `build_orebody` and `world.stats` NEVER run
inside the store lock; the protocol is optimistic (stat → expensive work
outside → `with lock:` re-stat and publish). Measured on WARPED-301
(`RANDOM_WARPED_VEIN` seed 301, one fault): the lock now holds `_save`
alone — 0.62 s wall for a 10,245,989-byte `arrays.npz`; before the hoist it
held 0.72–0.75 s because `world.stats` (0.099 s) ran inside it (three
independent runs on the same 10,245,989 bytes). `world.stats` is computed by
`generate` before it enters the lock and handed to `_save`, so the lock now
holds the two writes and the cache publish and nothing else — the compressed
NPZ write is what remains, and it is the reason nothing expensive may join it.

The cost of that hold is CONTENTION, and it is new: `POST /world/generate` now
holds the per-scenario lock across the NPZ write, and every read of the same
scenario now enters the same lock (the reader snapshot, the world cache probe,
the publish re-check). A reader that arrives inside the window WAITS for it,
and a reader whose `arrays.npz` or `scenario.json` revision moved across it
fails CLOSED with 409 `READ_SNAPSHOT_CHANGED` rather than serving a mixed
body — that is the intended trade (a bounded wait or a retryable refusal
instead of a silently inconsistent 200), stated here because the hold itself
was documented and its consequence for concurrent readers was not. Measured
hold: 0.62 s on WARPED-301's 10,245,989-byte `arrays.npz`, 32.6 ms on the
small scenario.

The scenario / world half of the same guarantee:

* `WorldService._bound_scenario(sid) -> (scenario, scenario_revision)` is the
  ONE bound document read: stat → `ScenarioStore.get` → re-stat, repeated
  while the revision moves (at most `SNAPSHOT_ATTEMPTS` = 3; exhaustion is
  `READ_SNAPSHOT_CHANGED`). Both halves are needed — capturing only before the
  read reports the migration-on-read as a race that never happened, capturing
  only after leaves the read outside the guarded window (a PUT between `get`
  and the stat would bind an OLD document to the NEW revision).
* `WorldService.load_bound(sid) -> (scenario, world, scenario_revision,
  arrays_revision)` adds `file_revision(arrays.npz)`, captured before
  `np.load`; the in-memory world cache entry carries both revisions and is
  served only while both still match, so a warm world can never answer for a
  replaced document or a deleted `arrays.npz`. In the cold-load window the
  file may go away under the reader, and both outcomes are typed rather than
  an escaping exception: deleted → `WorldNotGeneratedError`, replaced →
  `ReadSnapshotChangedError` (the world in hand cannot be attested to the
  captured revision). The SCENARIO half of the same window is SYMMETRIC
  (Stage D B1): a `scenario.json` that moved between the bound document read
  and the publish re-check is `ReadSnapshotChangedError` for the RESULT, not
  only for the cache entry. Commit 3 re-stat'ed the document but gated only
  the cache publish while the `return` was unconditional, so `GET …/world`
  and `GET …/world/slice` still served the R3d mixed body — measured,
  ONE 200 carrying the OLD document's `orebody.center [40.0, 20.0, -50.0]`
  beside the NEW world's `terrain.zMax 116.367159085105`. `load(sid)` is the
  unchanged two-value wrapper every engineering consumer still calls. The world guard is
  `file_revision(arrays.npz)` — `load_bound`'s own stat and the reader
  snapshot's, and nothing else (Stage D S11 deleted the caller-less
  `is_generated` helper, whose `Path.is_file` probe was never that guard).
* `WorldService.generate` re-checks the scenario revision under the lock
  before `_save` + cache: a scenario PUT landing during generation fails the
  generation closed (`JOB_INPUTS_CHANGED`) instead of publishing a world for
  the replaced document. Because the document read was bound, that check is
  now only ever true of a real third-party mutation.
* `PUT /scenarios/{id}` is ONE locked section (`WorldService.replace_scenario`
  = document write + `invalidate`), so external readers see one mutation
  boundary instead of a window in which the document is new and the world old
  — for reads that SUCCEED. AC-01F.2 closed the "SUCCEED" qualification for
  this process: `ScenarioStore._write` publishes `scenario.json` atomically
  (below), so a reader landing inside the document write now sees the whole
  previous document or the whole new one, and a torn `scenario.json` can no
  longer be produced here.
* Retry exhaustion is its own code: 409 `READ_SNAPSHOT_CHANGED` (a READ whose
  snapshot kept moving — nothing was built and nothing discarded), never
  `JOB_INPUTS_CHANGED` (a GENERATION whose inputs moved).

**Scope, honestly stated.** The store lock is a `threading.RLock`: the
guarantee is IN-PROCESS. Multiple processes over one `data/scenarios` tree are
unsupported (no OS-level lock exists or is added). `ScenarioStore.get`'s
Phase 18 migration-on-read is the ONE documented exception to "a read must not
write" (it rewrites the document and clears derived state); the protocol
TOLERATES it rather than reporting it, and the read authority adds no
migration and no repair of its own. Concretely: the rewritten document misses
the revision the caller captured, so `_bound_scenario` reads it again and
binds the migrated revision. The migration also calls `clear_derived`, so
what the repeated read then FINDS decides the answer — where that deletion
removed a world, the repeat finds no `arrays.npz` and the read answers 409
`WORLD_NOT_GENERATED` (regenerating is the explicit user repair); where there
was nothing to delete, the read is simply repeated and succeeds, which is why
`POST …/world/generate` on a schemaVersion-1 document is a 200.
Crash residue (a torn or half-published file left by a killed
process) becomes a typed refusal rather than a silent projection for every
registered derived artifact, and `load_bound`'s "replaced →
`READ_SNAPSHOT_CHANGED`" outcome presumes a COMPLETE replacement — which
AC-01F.2 makes the only replacement this process performs.

**Publication is atomic per file (AC-01F.2, finding F06-B).** Every persisted
file — `scenario.json`, `arrays.npz` and every file under `derived/` — is
written through ONE leaf helper, `backend/src/minegen/core/publication.py`
(`publish_bytes` / `publish_text` / `publish_npz`): the bytes go to a temp
sibling `.<name>.<8 hex>.tmp` in the target's own directory, the handle is
`flush()`ed and `os.fsync`ed, `os.replace` installs it (atomic on POSIX), the
directory is fsynced best-effort, and any failure before the replace removes
the temp and leaves the previous file — or its absence — untouched. The 22
in-place `write_text` / `write_bytes` / `np.savez_compressed` sites are gone
(`tests/test_publication.py` is the static proof), and a reader in ANOTHER
process now observes whole files: measured at 450f9df, a subprocess reading
`derived/stopes.json` under a real publish loop saw 7,679 of 164,384 reads
torn (4.67 %) and `arrays.npz` was unreadable for 357,563 of 357,563 reads
(100 %); after the change both are 0. Those two rates are the Stage A
measurement protocol — an ARTIFICIAL back-to-back publish loop on one
filesystem, with a reader doing nothing but re-read — so they size the window,
they are not production probabilities.

Publication ATOMICITY is per file; GENERATION COHERENCE is what the AC-01F.2
correction adds on top of it. `derived/world.json` is the world COMMIT RECORD —
`{"publication": {scenarioId, scenarioRevision, arraysRevision}, "stats": …}`,
published LAST, after `arrays.npz`, so its publication is the commit point of a
generation — and every world read refuses a world whose record does not name the
two live files (409 `WORLD_PUBLICATION_STALE`, one definition,
`ArtifactReader.require_world`, at five enforcement points). That closes the
state a process death between `ScenarioStore.replace` and
`WorldService.invalidate` used to leave PERMANENTLY: a NEW `scenario.json`
beside an OLD `arrays.npz`, which a fresh process had no evidence to distinguish
from a coherent pair and served as 200. Both recorded revisions are the rule-60
stat identity the PUBLISHER installed — `publish_bytes` / `publish_text` /
`publish_npz` return it from the temp file's own `os.fstat` before the rename —
never a stat of the path afterwards, which across processes can name another
generation's file. The same mechanism commits each mesh pair: `derived/<mesh>.commit.json` names
the report and GLB identities its own publication installed, so every surface
detects a GLB/report generation mixture — which the content hash cannot see at
all, because a deterministic rebuild installs identical bytes — without hashing
anything and without adding a field to the served report or the scene.

Two costs are stated rather than discovered. The record is validated in
`load_bound` AFTER the arrays load, so a Phase-17 `arrays.npz` keeps its
stricter `WORLD_ARTIFACT_INCOMPATIBLE` (A1); the price is that while a world is
uncommitted EVERY request pays one full `np.load` of `arrays.npz` before the
409 — measured 0.62 s for a 10.2 MB WARPED-301 artifact — and it keeps paying
it until the world is regenerated, because a refusal is never cached. And the
record observation is the first thing that makes `GET …/world` and
`GET …/world/slice` touch `derived/` at all: one extra stat plus a small read
per snapshot, and an unstattable record is treated as ABSENT so those two
routes keep the robustness they had before.

What is NOT claimed: a PAIR is two atomic publications, not one atomic pair —
the order is fixed (on SUCCESS the GLB before its report, `level_accesses.json`
before `layout_v2_selected.json`, `arrays.npz` before `derived/world.json`) so
a crash between them leaves the half the read authority classifies most
conservatively, and the read-side checks stay the durable answer. The FAILED
mesh path is the deliberate exception to the GLB order: there the FAILED report
is published FIRST and only then is the stale GLB unlinked, because unlinking
first would open a window in which a failing report publish leaves the previous
SUCCESS report beside no GLB — exactly the `ARTIFACT_MALFORMED` half the
SUCCESS order exists to avoid. Cross-process readers still take no lock; they
now see whole files rather than a coherent sequence of them. A crash before the
replace can leave a `.tmp` sibling, which no reader and no cascade looks at;
`clear_derived` removes one under `derived/`, while a temp beside
`scenario.json` / `arrays.npz` in the scenario root is removed only by
`ScenarioStore.delete` — no startup sweep exists. The publication also installs
a NEW inode, so mode, ownership and symlink identity of an existing target are
not preserved (nothing in MineGen sets any of them). A torn `scenario.json` or
`arrays.npz` written by an EXTERNAL process is still an unmapped 500; a torn
registered artifact under `derived/` is the typed 409 `ARTIFACT_MALFORMED`
(AC-01F).

## Non-goals (v0.1)

Production reserve estimation, regulatory certification, full geostatistics,
FEM/DEM, CFD ventilation, full-wave RF, dispatch optimization, NPV
optimization, multi-user, photorealism. APIs are shaped so these can be
attached later; the `simulation/` package is a reserved empty namespace, not
an adapter layer.

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

**Decline-only scope (rule 103, Phase 13–15)**: the walkable excavation was
the Phase 06 decline ONLY. DRIFT/CROSSCUT developments owned centerlines,
not volumetric meshes, and the frontend never inflates them into fake
tunnels; timeline, communication and sensor semantics are untouched.
Walkthrough visibility is DERIVED (tunnel mesh + passive terrain), never a
mutation of the user's stored layers.

**Phase 20D.2 static branch walkthrough (rule 187)**: once Phase 20D.1
emits `development_mesh.glb` with typed junction apertures, the STATIC_FINAL
walkthrough consumes it the same way it consumes the ramp GLB —
`walkthrough/developmentRuntimeGeometry.ts` splits the loaded scene by
`geometry.userData` role/kind (`DEVELOPMENT` tubes for LEVEL_ACCESS / DRIFT
/ CROSSCUT, `<KIND>_CAP` caps only where the writer emitted one), validates
every primitive (position/index present, Float32 / Uint16|Uint32, triangle
shaped, in-range indices, finite vertices, known role and kind, role/kind
agreement, no duplicate semantic primitive, no orphan cap, no cap carrying
`ranges`) and every tube's writer `ranges` table (string ids, integer
triangle-aligned `indexOffset` / `indexCount`, contiguous in buffer order
without overlap or gap, covering the primitive exactly, unique piece ids,
reveal metadata accepted by the shared `readRevealMeta`), and reuses the
source vertex buffer and index arrays EXACTLY under the shared
`toThreePositions` transform. `DevelopmentColliderSet` mounts one fixed
trimesh per emitted batched primitive (`WALK:COLLIDER:DEVELOPMENT:<kind>`,
`WALK:COLLIDER:DEVELOPMENT_CAP:<kind>`) — the validated ranges keep piece
identity for a later time-aware activation, but no piece split, no resweep,
no proxy corridor, no frontend aperture or floor patch, default physics
material and the unchanged PERSON capsule — so the player walks PORTAL →
RAMP → LEVEL_ACCESS → DRIFT → CROSSCUT and back through the declared
apertures, and an emitted cap is a real dead end.

*Composition and visibility.* `resolveDevelopmentPhysics` decides the mount
(STATIC_FINAL and a SUCCESS development mesh with a meshUrl);
`resolveWalkthroughComposition` pins the three cases — Case A (no
development artifact) ramp-only baseline, Case B (advertised + valid
runtime geometry) ramp AND development colliders in ONE physics world, Case
C (advertised but malformed) fail closed. The development GLB is loaded and
validated by a wrapper that OWNS the URL (`StaticDevelopmentRuntime`) before
the core runtime mounts, so hook order never depends on whether a
development mesh exists and the physics world never exists without the
colliders it was promised; a contract violation exits the walkthrough
through `onGeometryError`, never a silent ramp-only fallback. Walkthrough
visibility is the AUTHORITY set (`walkthroughAuthorityLayers`: ramp always,
development iff its physics is mounted), never an intersection with the
user's stored toggles — the same predicate feeds `MineCanvas` (colliders)
and `MineScene` (layers), so "collider without geometry" and "toggle off →
boundary gone" cannot occur; the stored preference is bypassed, never
mutated.

*Endpoint-cap audit (§10) and the typed cap cut.* The pre-20D.2 walks
wedged when returning up a crosscut that starts at a drift extremity.
Measured on both acceptance fixtures with a ray-cast audit along the
drift ↔ crosscut path: every crosscut whose station sits on a drift END
(TABULAR 8 of 20, all WARPED-301 levels) hit `DRIFT_CAP` at 0.4–1.4 m,
every interior station hit nothing — the crosscut axis lies in the cap
plane, so the cap's crosscut-side half stood inside the mouth (a cap is a
separate primitive the quad rules never saw). The fix is the same typed
local cut the child floor receives, on a cap fan instead of a quad grid
(`design/junctions.py::cut_cap`, `CapCut`, `_clip_triangle`): fan triangles
inside-or-on the child envelope are omitted, outside ones kept, straddling
ones clipped by bisection on their own edges with the remainder
fan-triangulated into new cap vertices (UV interpolated barycentrically);
the end wall stays on the rock side, the chord meets the crosscut's open
start plane, caps no junction reaches are bit-identical and crosscut faces
are never cut. The render builder reports it additively (`omittedTriangles`
/ `clippedTriangles` / `replacementTriangles` on a cut cap primitive,
`renderCap*` per development, `parentCap*` per junction opening;
`removedTriangles` now counts tube AND cap originals not emitted as-is)
and the base-sweep closedness QA always judges the UNCUT fans. Two
junctions clipping one fan triangle are an explicit conflict. Post-fix, the audit is clean on every interior station of both
fixtures; the WARPED-301 extremity stations still register a graze on the
kept half-cap's boundary edge, which is the traffic CORNER of the L-shaped
union (the station sits on the drift end), not surface inside the mouth —
the capsule rounds it and both browser walks pass it in both directions.
The same audit exposed a second defect class at the same stations
(closed in 20D.2.1, the PR #42 review blocker): at every drift-extremity
station the half of the crosscut's OPEN start ring beyond the drift end
faced unexcavated rock with no surface (TABULAR 8 / 20, WARPED-301
28 / 187 stations) — the 20D.1 OPEN policy assumes a T-junction. The
backend now emits the typed CHILD MOUTH CAP (`cut_mouth_cap`, the mirror
of `cut_cap`: the crosscut's start-ring fan judged against the DRIFT
envelope, inside-or-on fans omitted so the mouth stays open into the
drift, outside fans kept, straddling fans clipped at the drift boundary;
a `CROSSCUT_CAP` primitive flagged `junctionMouthCap`), for the typed
DRIFT_CROSSCUT junction only; interior T-junctions get nothing and stay
bit-identical, faces are untouched, the logical mesh / OPEN QA are
unchanged, and the frontend still adds no collider (`docs/algorithms.md`,
§10 closeout).

*TIMELINE_SNAPSHOT.* The temporal walkthrough keeps its ramp-only
collider contract, frontier barrier and snapshot freeze; since the ramp GLB
now carries a RAMP_ACCESS aperture at every turnout, every declared
aperture (tunnel report `junctions.byType.RAMP_ACCESS`) is closed by
ephemeral wall-line barrier pieces (`walkthrough/apertureBarrier.ts`,
`ApertureBarrierSet`): one thin gravity-aligned cuboid per effective
centerline interval inside the cut window (2 widths, plus 1 width margin)
on the branch side decided by the authoritative access centerline, mounted
only on ACTIVE segments (an inactive branch side is already closed by the
frontier). The inputs are frozen with the plan at mount; apertures
declared but not locatable (level accesses missing / failed, a count
mismatch, a junction not welded to the ramp centerline, unusable ramp
dimensions) fail the temporal session closed. Final development geometry
never leaks into a snapshot; temporal branch traversal is deferred.
Minimap / ramp-chainage teleport stay ramp-based (a CH readout inside a
branch refers to the main ramp); branch teleport, network maps, temporal
branch physics and branch infrastructure interaction are later scope.

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
splittable mesh geometry to do better. Phase 20B.2-F delivered that for the
4D ORBIT view only (rule 173): the ramp / development GLB SEGMENT
primitives carry ring-interval reveal metadata and
`scene/TemporalExcavationLayer.tsx` shows the actual excavation meshes cut
at the last completed ring of the Phase 10 progress through draw ranges /
draw groups over the shared loaded buffers (`timeline/excavationReveal.ts`,
fail-closed mapping; unmapped developments keep their centerline). The
walkthrough volumetric rule above is unchanged. Phase 20C.1-V added the
excavation direction contract (rule 174): the −u-side drift pieces of every
level are stored in +u point order (face → entry), so before 20C.1 their
reveal grew from the face toward the ramp (117 of 221 DRIFT edges on the
acceptance scenario; RAMP / LEVEL_ACCESS / CROSSCUT were already correct).
The timeline now names each development's `excavationStartNode` and
`progressDirection`; `clipPolylineByFractions` and `revealedIndexRange`
reveal the suffix for −1 developments, geometry untouched. Availability is resolved ONLY
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
direction (pitch flies), which makes ramp following natural. A ramp
teleport select ("Go to…") jumps to the portal or any ramp turnout via
the SAME deterministic spawn rules at the station chainage. Hardening
H0 §3.2: the authority is the backend `RAMP_JUNCTION.chainage` (network
node); without a network the same chainage is read from the level
accesses (`rampJunctionChainage`), and failing that from the Effective
Ramp's own segment boundaries (rule 155 — a PARAMETRIC_V2 segment ends at
its `rampJunction`, a LEGACY segment at the level entry on the ramp), so
the list exists whatever the level development did. The old
LEVEL_ENTRY-within-15-m test is gone: a layout-v2 level entry sits
≥ 6 × tunnel width off the ramp at the end of its access branch and is a
branch teleport (later scope), never a ramp station. In temporal
snapshots the station list derives from the ACTIVE-prefix centerline, so
beyond-frontier turnouts are never offered. The minimap gained a
longitudinal CH-RL profile strip fed by the same ACTIVE-prefix chainage
points.

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
        ↓ enumerate_candidates  (SPIRAL 36 · LONGITUDINAL 8 · SWITCHBACK 48 = 92;
                                 Phase 20C.1-S station axis {0, 50 m} doubled the switchbacks)
    families.py  closed-form primitives from the authoritative portal
        SPIRAL        R = ΔZ/(2π·g·n), drifting helix along the footwall track
        LONGITUDINAL  one-direction along-strike descent, corridor clipped to the world
        SWITCHBACK    stacked antiparallel legs, L = ΔZ/(k·g) − π·R_min − s, constant hairpin
                      sense; hairpin = arc(π) for s = 0, arc(π/2)+straight(s)+arc(π/2) for a
                      station s > 0 (leg spacing 2·R_min + s)             ← rule 175
        ↓ delivered polyline (sampleSpacing 2 m)             ← rule 144
    geometry.py   per-edge gradient, chord plan radius, unwrapped heading,
                  family signatures, exact level crossings          ← rule 145
    levels.py     required levels = generate_level_elevations (rule 141);
                  in-plane footprint sections on `contains` + KD-tree + bisection
                  (upper-bound access distance)                     ← rule 144
    search.py     STAGE 1 enumerate → 2 cheap (grade, radius, bounds, monotone,
                  level service, geometric access screen ← rule 176)
                  → 3 shortlist (12, ordered by blocked levels then the
                  lower-bound proxy) → 4 detailed
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

Footwall-contact guard (hardening H0 §3.1, rule 141). The generator measures
the top level from the bounding-box top — the HANGING-WALL top edge of a
dipping slab — while the footwall top edge sits `thickness·cos(dip)` lower.
A TABULAR level inside that band has ore above it and no footwall contact
next to it: the legacy access targets reject it (`OUTSIDE_OREBODY_DIP_EXTENT`,
`design.targets.has_footwall_contact`) and layout-v2 now applies the SAME
function in `LevelSections` (`NO_FOOTWALL_CONTACT_AT_LEVEL`, excluded from
the serviceable set, reported in `requiredLevels[]` as `serviceable = false`
with `exclusionReason`, the down-dip `overshootM` and the dip-aware hint
`minimumTopMiningMarginM = thickness·cos(dip)`). The level generator itself
is untouched. `levels.json` reports every REQUIRED level without a
development in `excludedLevels[]` (typed reason: the footwall guard, the
section exclusion recorded by the catalogue, or `NO_LEVEL_ENTRY`) and the
adjacent pairs that therefore carry no production in `unservedIntervals[]`
(rules 76 / 195). Measured: RANDOM_TABULAR seed 42 (dip 61.6°, 24.9 m
thick) — L01 overshoots by 2.12 m, every crosscut on it missed the slab by
exactly that |sdf|; with the guard the layout serves L02–L13 (12 levels,
SUCCESS). Golden census: RANDOM_TABULAR-101 / -105 / -106 overshoot 2.82 /
7.14 / 1.68 m on L01 (the legacy chain already excluded them); every
layout-v2 FULL_SUITE TABULAR case 0 (goldens unchanged). A
`topMarginReference` option is a later, golden-changing item.

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
baseline `golden/phase20a_layout_v2.json` at the time — retired to its CSV summary under the Phase 20B.3 retention policy below; smoke in CI) alongside the
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
  a conservative clearance policy (COARSE_CONSERVATIVE, or the stage-4
  REFINED_CONSERVATIVE window) the stand-off is raised to
  `required + errorBound + 1 m` so the entry itself is clear.
* `plan_level_accesses` — per serviceable level: a finite lattice of ramp
  junction candidates every `junctionSearchSpacing` (10 m) whose ramp
  elevation lies within `junctionWindowAbove` (45 m) / `junctionWindowBelow`
  (10 m) of the level and within `maximumAccessLength` of the anchor; for
  each candidate and both turnout senses a G1 one-turn CS connector
  (Phase 20B.2-A: S / L+S / R+S — one arc of R = minTurnRadius tangent to
  the ramp heading, then one straight to the anchor point; terminal heading
  free, sweep ≤ π, exact endpoints, z linear in delivered chord length so
  every edge carries one gradient); rejection reasons NO_JUNCTION_IN_WINDOW,
  CONNECTOR_UNAVAILABLE (entry inside the turning circle / behind the
  junction), GRADE_LIMIT, TURN_RADIUS, ACCESS_TOO_SHORT / LONG,
  WORLD_BOUNDS, SURFACE_COVER, RESTRICTED_ZONE, OREBODY_CLEARANCE,
  ENVELOPE_INVALID (profile boundary points through `envelope_masks`),
  JUNCTION_SPACING_CONFLICT (`minimumRampJunctionSpacing`, 40 m);
  deterministic selection = min (selection cost, length, junction chainage,
  sense S < LS < RS). No clamping, no optimizer, no randomness.
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
(strike extent minus the fixed `GENERIC_BACKBONE_END_CLEARANCE`; independent
of `stope_length` / `minimum_pillar`) and an explicit UNSUPPORTED_METHOD
production status. MineNetwork emits
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
for the walkthrough / minimap. Golden: `golden/phase20b_layout_v2.json` (full JSON retired to `phase20b_layout_v2.csv` + comparison files, Phase 20B.3 policy)
(6 cases incl. ACCESS-INFEASIBLE and CUT_AND_FILL) records junction
chainages, entries, access lengths / gradients / radii and typed failures;
`golden/phase20b_full.json` re-runs the legacy suite.

#### Phase 20B closeout v3 — manual-acceptance fixes (rules 163–168)

1. **Preferred access length** (`layout/access.py`,
   `LevelAccessConfig.preferredAccessLength`). The old selection
   `min (length, chainage, sense)` hugged the 15 m hard floor. The planner
   now orders VALID candidates by `access_length_cost(L, P) = |L − P| +
   LONG_ACCESS_COEF · max(0, L − P)` with `P = effective preferred length`
   (`max(minimumAccessLength, 6 × tunnel_width)` unless an explicit,
   schema-validated value is given) and `LONG_ACCESS_COEF = 0.5` (a
   documented provisional module constant). Hard limits are checked before
   the cost exists; every access reports the preferred length, its deviation
   and the selection cost; the plan summary reports the preferred source
   and the mean / max |ΔP|. Purpose: usable turnout development and room for
   future sump / services / ore-pass connections — a planning default, not
   a regulation and not a mandatory minimum.
2. **Stage-2 screen** (`layout/search.py::level_screen_problems`).
   ACCESS_REACH_EXCEEDED (same-RL crossing → footprint distance) is a
   heuristic that feeds the stage-3 proxy and never rejects a candidate;
   NO_RL_CROSSING (the main ramp does not vertically cover the level —
   e.g. a LONGITUDINAL ramp that runs out of strike length above the
   bottom level) stays hard. Stage 4 (`plan_level_accesses`) is the final
   authority. Golden effects are explained in
   `golden/phase20b_closeout_vs_phase20b_layout.json`.
3. **Shortlist starvation audit** (`LayoutV2Search.run(detailed_all=True)`,
   `python -m minegen.regression layout-v2-audit`,
   `golden/phase20b_closeout_shortlist_audit.json`): exhaustive detailed
   validation of every cheap-feasible candidate against the bounded
   production shortlist. The audit reports the feasible candidates the
   shortlist never validated and whether the exhaustive winner or a
   feasible family is missed; the production shortlist changes only when it
   does.
4. **Development excavation meshes** (`design/development_mesh.py`,
   `derived/development_mesh.{json,glb}`, `GET/POST …/design/development-mesh`).
   `DevelopmentSpec`s are built from the owning artifacts (access branches
   OPEN-OPEN, one continuous drift tube per level from its consecutive
   pieces CAP-CAP, crosscuts OPEN-CAP), swept through the Phase 06
   `build_ring_chain` / `build_logical_mesh` / `build_render_mesh` (now
   with a `caps` switch) with `secondary_profile` tessellation (arch
   segments halved, subdivision spacing doubled — polyline vertices are
   always rings), validated by `validate_development_topology` (OPEN:
   manifold with boundary, exactly K boundary edges per open end on the end
   rings; CAP-CAP: watertight + signed volume) and
   `validate_development_envelope` (drift / access context, crosscut
   context), then batched per kind (`batch_render`: one tube + one cap
   primitive per kind, `ranges` extras → development / piece ids) into one
   GLB. The frontend `DevelopmentMeshLayer` assigns the shared tunnel
   materials by role; centerline overlays stay independent layers. Phase
   20D.1 (`design/junctions.py`, `docs/algorithms.md` "typed junction
   union") opens the three declared junction kinds (RAMP → LEVEL_ACCESS,
   LEVEL_ACCESS → DRIFT, DRIFT → CROSSCUT) by omitting the blocking quads of
   the RENDER meshes locally; centerlines, profile, artifacts and lifecycle
   are unchanged, the logical mesh keeps its QA semantics on a junction-
   locally refined tessellation, `geometricallyClosed` describes the emitted
   mesh (with `baseSweepGeometricallyClosed` for the pre-aperture weld QA),
   and a general boolean / CSG union stays out of scope.
5. **UX hierarchy** (`LayoutPanel`, `DesignPanel`, `LegacyDeclinePanel`,
   `LayerPanel`): Layout v2 is the primary workflow and names the current
   design; the mine-development chain (levels → excavation meshes →
   network → stopes → timeline) follows; the legacy Phase 03–05 chain and
   the explicit source switch are one collapsed Advanced section that
   auto-expands only for a scenario with legacy work under the LEGACY
   source (`rampSource.ts::legacySectionAutoOpen`); `accessTargets` /
   `rawSearchPath` default OFF and are hidden on activation.
6. **Effective Ramp identity** (rule 169, `scene/invalidation.ts`).
   Downstream preservation is decided on the identity (source, selected
   candidate, layout revision), not on `activeSource` alone: replacing the
   selected candidate while LAYOUT_V2 is ALREADY active changes the ramp
   just as a source switch does and invalidates the whole chain. The two
   halves each have exactly one comparison — `afterLayoutSelect`
   (candidate / revision) and `afterRampSourceChange` (source) — and
   `afterLayoutActivate` composes them for the activate call, preserving the
   level accesses owned by the activated selection.
7. **Level development under an implicit body**
   (`DesignService.generate_levels`). The drift and crosscut evaluators are
   built with the world's own clearance policy (`clearance_policy_for`,
   rule 146) instead of the exact-only `self.evaluator`: TABULAR stays
   EXACT and numerically identical, while a WARPED_VEIN now REACHES
   `LevelDevelopmentBuilder` and answers the intended typed Phase 20B
   boundary — `200` with `status = FAILED` and
   `LEVEL_DEVELOPMENT_UNSUPPORTED_FOR_IMPLICIT_OREBODY` — instead of the
   legacy evaluator's 422. Rule 135 still guards the LEGACY Hybrid-A* chain
   (access targets / decline / smoothing), which is a different path. The
   development mesh keeps sweeping the validated access branches, and its
   `sources.levels` flag reports CONTRIBUTION (a persisted but FAILED levels
   artifact contributes nothing).
8. **Out of scope**: the ramp / footwall / access stand-off semantics audit
   (rule 168, roadmap item S1); boolean junction openings and an
   all-development watertight union (Phase 20D; the typed local apertures
   landed in 20D.1 and the STATIC_FINAL development walkthrough in 20D.2,
   see "Phase 20D.2 static branch walkthrough" under Phase 13).

#### Phase 20D.3 — Design Assessment & Candidate Comparison (rule 189)

The last Phase 20 closeout answers two questions from artifacts that
already exist — "why was this layout selected?" and "how well does the
selected design satisfy MineGen's engineering / design checks?" — without
adding a search, a gate, a threshold or a persisted file.

- **Read model, not an artifact.** `DesignService.design_assessment` takes
  ONE `ArtifactReader.snapshot` of `layout_v2.json`,
  `layout_v2_selected.json` (+ its co-published `level_accesses.json`),
  `ramp_source.json`, `network.json` and `capability_graph.json`, applies
  the world guard, resolves the ACTIVE ramp source first and hands the
  VALID documents to the pure `assessment/builder.py` projection. Under
  LAYOUT_V2 the catalogue is required (`LAYOUT_V2_NOT_GENERATED`
  otherwise); under LEGACY it is optional (PR #43 review correction): a
  LEGACY-only design keeps its generic network / capability / egress
  checks (`layoutScope = NONE`, layout checks `NOT_APPLICABLE`, empty
  comparison), and a dormant catalogue / selection is reported with the
  explicit `INACTIVE_LAYOUT_V2` scope on every layout-v2 check and
  `activeDesignCandidateId = null` — never conflated with the active
  design. The selection and the capability graph are optional when ABSENT
  (dependent checks answer `NOT_EVALUATED`); any present artifact that is
  STALE or MALFORMED raises its own typed refusal
  (`LAYOUT_V2_SELECTION_STALE`, `CAPABILITY_GRAPH_STALE`,
  `ARTIFACT_MALFORMED`) through the design router's `_fail` — no fallback,
  nothing generated, nothing written (`derived/` is byte-identical before
  and after a read). The assessment also owns a consumer-specific
  structural boundary (PR #43 re-review): `validate_catalogue_shape`
  checks every catalogue field the projection reads (candidate ids,
  family, status, rank, requiredLevels, failureReasons, the scores /
  clearance / access / validation blocks, ranking consistency, id
  uniqueness) once, names the JSON path, and its `CatalogueShapeError` is
  translated by the service into `ArtifactMalformedError(layout_v2.json,
  …)` — a syntactically valid catalogue that the shared reader accepts but
  the projection cannot consume is a typed 409, never a bare 500, while
  NO_FEASIBLE_CANDIDATE / INFEASIBLE / NOT_VALIDATED and permitted null
  optional blocks keep projecting.
- **Authority model.** `AssessmentCheck{id, title, category, status,
  authority, summary, evidence, sourceArtifact, sourceField}` with
  `status ∈ SATISFIED | NOT_SATISFIED | NOT_APPLICABLE | NOT_EVALUATED`
  and `authority ∈ HARD_DESIGN_RULE | DERIVED_VALIDATION | ADVISORY |
  INFORMATIONAL`. Evidence is numbers, flags and ids only. Checks, in a
  fixed order: LAYOUT_SELECTED (selection artifact), ACTIVE_RAMP_SOURCE
  (info), SELECTED_IS_RANKING_WINNER (info), CANDIDATE_FEASIBLE (hard:
  `candidates[].status`), ALL_REQUIRED_LEVELS_ACCESSIBLE (hard:
  `accessibleLevels == requiredLevels`, unserved ids from
  `access.failures`), CLEARANCE_VALIDATED (hard: `clearance.satisfied`),
  GEOMETRY_VALIDATED (validation: `validation.invalidSampleCount == 0`),
  CAPABILITY_GRAPH_VALID (validation), REQUIRED_CAPABILITY_PATHS
  (validation: `requiredPaths[].satisfied`, with `physicalReachable` and
  `capabilityReachable` projected separately, rule 185) and
  DUAL_EGRESS_ADVISORY (advisory: `egressAdvisory.perNode` counted —
  required routes, surface nodes, underground / meeting / failing node
  counts and ids, minimum independent routes; the summary always ends
  "This is a design advisory, not a statutory compliance determination").
- **Candidate comparison.** Rows are the catalogue `ranking` entries in
  their stored order — the ranking winner plus the top FEASIBLE
  alternatives (default 5 rows), the selected candidate always included —
  each carrying the catalogue's own rank / status / stage / scores /
  accessible-vs-required levels / clearance / access summary / failure
  reasons and `deltas = candidate − winner` per score group (plain
  subtraction). A ranking entry that is not FEASIBLE is a catalogue
  inconsistency and is refused, never shown; INFEASIBLE and NOT_VALIDATED
  candidates are never alternatives. The templated `summary` ("Selected …
  Rank: 1 of N feasible … Compared with rank 2 …") is fixed sentences over
  recorded numbers, never persisted reasoning.
- **Frontend.** `LayoutPanel` reads `GET …/design/assessment` through
  react-query for every loaded scene (key = `assessmentKey(scene)`: the
  scenario id plus the scene object's IDENTITY — every backend mutation
  produces a new scene object, so a regenerated catalogue with the same
  winner / count / ranking but changed values can never leave a stale read
  model on screen; the backend validated read stays the authority) and
  renders the scope line ("active design: Layout v2 · id" / "active design:
  LEGACY · layout-v2 checks describe the INACTIVE layout-v2 selection" /
  "· no layout-v2 catalogue"),
  `DesignAssessmentList` (✓ / ✗ for hard rules and validations, "!" and a
  dashed *advisory* tag for the egress advisory, "i" for info, "?" and
  NOT EVALUATED / NOT APPLICABLE otherwise — a satisfied advisory is never
  a check-mark badge) and `AlternativesTable` (● winner, "(selected)",
  rank, total score, Δ, accessible / required, status) in the delivered
  order; a typed read refusal is shown as "design assessment unavailable —
  CODE". No client-side check, score, delta, sorting or inference.
- **Non-regression.** Winner, ranking, scores, goldens, characterization,
  network, capability graph, geometry, meshes, walkthrough and timeline are
  untouched — the module only reads them.

## Golden retention policy (Phase 20B.3)

The full detailed layout-v2 JSON of one phase is ≈ 90,000 lines; keeping
every phase's copy makes the repository heavy while diff / review — the
whole point of a golden — happens on the CSV summary and the comparison
files. Git LFS is deliberately not used. Policy:

- Only the LATEST phase keeps its full detailed layout-v2 / warped-vein JSON
  (`golden/phase20bx_layout_v2.json`, `golden/phase20a_warped_vein.json`).
- Every earlier phase keeps its CSV summary plus the comparison / audit JSON
  files (`*_vs_*_layout.json`, `*_shortlist_audit.json`, `*_turning_burden_audit.json`,
  …); its full JSON is deleted when the next phase's baseline lands.
- HISTORICAL_DIAGNOSTIC artifacts (the failure census, the reference audit, the gate shadow,
  the F1 investigation, survey before/after tables) are not retention targets and are never
  deleted; a superseded phase's full layout golden keeps its provenance in git history
  (the deleted blob is one `git show <sha>:backend/golden/<file>` away).
- A golden a test references is exempt from deletion (grep `backend/tests`
  before deleting — `phase17_baseline.json`, `phase19_warped_vein.json`,
  `phase20bx_layout_v2.json` are referenced today).
- The legacy 22-case golden files (`phase17_baseline`, `phase18_after_migration`,
  `phase19_full`, `phase20a_full`, `phase20b_full`, `phase20b_closeout_full`)
  are the regression lock of rule 132 and are NEVER deleted.

Phase 20B.3 applied it: `phase20a_layout_v2.json`, `phase20b_layout_v2.json`,
`phase20b_closeout_layout_v2.json` and `phase20b1_layout_v2.json` were removed
(13 MB → 3.9 MB); their CSVs and comparisons stay.


## Phase 20C.2A — curved WARPED level development

The whole-section principal-axis (PCA) backbone for implicit orebodies is
GONE. Level development for every non-TABULAR body now follows the curved
SECTION_FOOTWALL_OFFSET_TRACE backbone built from authoritative section(z)
geometry (`layout/sections.py`, rules 177–180; algorithm details in
`docs/algorithms.md`): a contains()-only occupancy grid (resolution
contract + cell budgets), 4-connected dominant component, marching-squares
outer contour, a contains()-verified footwall trace seeded (orientation
only) by `track.w_h`, and a development backbone extracted as the level set
of the DESIGN CLEARANCE POLICY at the anchor stand-off — smoothed at the
stand-off scale and re-validated against the required design clearance.
Anchors, the geometric access screen and stage 4 share the same section
semantics (they differ only in clearance policy / stand-off); every
section-geometry failure is typed and per-level. The level builder
dispatches by the development-geometry contract carried by the level-access
anchors (never isinstance), rebuilds the backbone under the SELECTED
candidate's certified policy (rule 172, SECTION_TRACE_MISMATCH fails
closed) and emits curved drifts, chainage stations and
contains()-bisection crosscuts through the unchanged hard gates.
`levels.json` declares `developmentGeometry`; the TABULAR path is
bit-compatible; WARPED stopes remain the typed Phase 09 boundary. The
artifact ownership, invalidation chains and downstream builders (network,
development mesh, timeline, communication, sensors) are unchanged — they
consume the same `levels.json` contract.

## Phase 20C.2B — shaft infrastructure + capability graph

Three layers are kept apart (rules 182–185):

| layer | owner | says |
|---|---|---|
| geometry | `layout_v2_selected.json` / `decline_smoothed.json`, `level_accesses.json`, `levels.json`, **`shafts.json`** | where things are |
| topology | `network.json` (MineNetwork) | what connects to what |
| capability | **`capability_graph.json`** | what a connection may be used for |

**Shaft** (`shafts/`, rules 182–184). A shaft is an infrastructure
primitive ADDED to the selected layout — never a layout-v2 family, never a
replacement for the ramp, never placed by an optimizer. `scenario.shafts`
declares explicit `ShaftSpec`s (empty = no shaft; every no-shaft artifact
is unchanged). The deterministic planner puts a vertical axis on a terrain
collar (explicit plan position, or the documented default: `collarStandoff`
beyond the footwall-most level-development extent along the away-from-ore
direction through the target-level entry centroid), one SHAFT_STATION per REQUIRED level at the elevation of that
level's nearest EXISTING development node (LEVEL_ENTRY or drift
breakpoint), a straight validated station drive to that node, and a sump
bottom; axis and circular envelope pass the shared `DesignCostEvaluator`
gates under `DesignContext.shaft` (orebody buffer hard — penetration
forbidden; restricted zones and world bounds hard; terrain break-through
only in the collar zone; no surface-cover rule because a shaft breaks the
surface by definition). Every failure is typed (`ShaftFailureCode`); one
infeasible required station fails the shaft. `shafts.json` owns the
geometry in one flat `centerlines` list so `GeometryRef{artifact,
segmentIndex}` is unchanged. Lifecycle: levels → shafts → network;
`levelsRevision` binds the artifact to the levels it was planned against
(409 SHAFTS_STALE otherwise). MineNetwork adds SHAFT_COLLAR /
SHAFT_STATION / SHAFT_BOTTOM nodes, VERTICAL `SHAFT` edges (null
gradients, `verticalDrop`, CIRCULAR section) and `SHAFT_STATION_ACCESS`
edges welded onto the existing level node; PORTAL ∪ SHAFT_COLLAR is the
surface set of the rule-70 advisory. The timeline sinks each segment from
the collar and drives stations from the shaft (rule 174 start nodes); the
infrastructure domain treats both new edge types as physical tunnel
geometry (network-geodesic = 3-D length). Shaft mesh, inclined shafts,
placement optimization and shaft-only mines are out of scope (rule 26
reserves a parallel-transport frame for near-vertical sweeps).

**Capability graph** (`capability/`, rule 185). A semantic overlay that
references MineNetwork node / edge ids and owns nothing else. Each edge's
capability set comes from an EXPLICIT source — the declared (or module
default) set per physical edge type, or the owning shaft's declared set for
shaft edges — and node `supports` are derived from incident edges. It
validates references, duplicates and revision synchronization
(`networkRevision` = the file revision of `network.json`; 409
CAPABILITY_GRAPH_STALE when the network moved on), evaluates required
capability paths (portal → level entries, collar → stations for shafts
declaring personnel / haulage, one EMERGENCY_EGRESS route for every
personnel-reachable underground node) and reports the edge-disjoint egress
advisory on the capability-filtered subgraph — an advisory, not a
compliance claim (Phase 20D). `can_reach(source, target, capability)`
answers physical and capability reachability separately
(`GET …/design/capability-graph/path`). Capability ≠ capacity: no
tonnes/hour, people/hour, airflow or hoist cycle is modelled. Lifecycle:
network → capability graph; regenerating the graph touches nothing else.

## Verification tiers (VA-01)

Verification is tiered so the inner loop is fast while release evidence stays
complete (`scripts/verify.py`; details and the baseline profile in
`docs/verification.md`):

| tier | command | scope | authority |
|---|---|---|---|
| FAST | `python scripts/verify.py fast` | ruff · format · mypy · pytest `-m "not slow and not golden and not survey and not e2e and not legacy_regression and not benchmark"` (491 of 564 tests at VA-01) incl. cached canaries | development only |
| FEATURE | `python scripts/verify.py feature` | FAST ∪ `canary` (clean TABULAR-REFERENCE / WARPED-301 pipelines, fixture freshness) | milestone gate |
| FULL | `python scripts/verify.py full [--closeout] [--legacy]` | every old-CI gate, pytest UNFILTERED, frontend gates, mechanical coverage proof; `--closeout` adds golden / survey / screen-audit compact summaries, `--legacy` the 22-case suite | merge evidence for its exact HEAD |
| BENCHMARK | `python scripts/verify.py benchmark` | reference-case stage runtimes → `runtime-summary.json` | observation only |

Invariants: `collected(FULL) == collected(unfiltered)` and
`excludedFromFast ⊆ FULL` (`verify.py collect-full`, pinned by
`tests/test_verification_tiers.py`); markers are assigned centrally in
`backend/tests/conftest.py` (module / test / expensive-fixture tables) under
`--strict-markers`. Session-shared upstream fixtures are read-only with a
teardown fingerprint check. Cached verification fixtures
(`backend/tests/fixtures/verification/`, generator
`scripts/generate_verification_fixtures.py`) carry a content fingerprint that
FULL re-derives cleanly — a mismatch is an explicit STALE VERIFICATION
FIXTURE failure. Outputs: `backend/.verification/verification-summary.json`
plus per-step logs (git-ignored). CI: `verify-fast.yml` (feedback) and
`verify-full.yml` (backend + frontend component jobs aggregated by the
`Release Authority` job — the ONE CI release verdict, AC-01H); the original
`ci.yml` was retired after same-revision equivalence was proven.

## Phase 23A — MineExchange Core v1 (rule 190)

`docs/mine-exchange.md` is the contract document. Architecture summary:

- **Boundary.** `services/exchange_service.py` takes ONE validated
  `ArtifactReader.snapshot` of every source (scenario, arrays, ramp source and
  both ramp owners, level accesses, levels, shafts, network, capability
  graph, tunnel / development reports + GLB bytes), verifies the world
  binding against it, resolves the active Effective Ramp exactly as the
  design service does, feeds `exchange/builder.py::build_exchange` (pure:
  authoritative documents + world → `BundleSpec`), writes the ZIP through
  `exchange/bundle.py::write_bundle` and re-snapshots before returning
  (`READ_SNAPSHOT_CHANGED` on any revision / presence drift). Nothing is
  persisted; the ZIP is not a derived artifact and has no lifecycle.
- **Export ≠ engineering.** Closed excavation solids are the CAP–CAP logical
  sweeps produced by the SAME helpers the production mesh builders continue
  from — `design/tunnel_mesh.py::ramp_logical_sweep` and
  `design/development_mesh.py::closed_sweep`, extracted behaviour-preserving
  (existing tunnel / development GLB bytes proven bit-identical before /
  after) — with the same junction refinement points. No search, planner,
  ranking or centerline is re-run; the render GLBs are copied verbatim.
- **Formats are pure.** `exchange/formats/` writers map typed geometry to
  bytes only (own binary STL / OBJ / ESRI ASC / CSV / minimal ASCII DXF
  writers with independent readers for round-trip tests; GLB through the
  existing `design/glb_writer.write_glb` with an ADDITIVE root-node matrix
  and extras — bytes unchanged when omitted). No new dependency.
- **Frontend.** `api.exportMineExchange` downloads the blob with the
  server-declared filename; the Scenario panel button is enabled once a world
  exists and shows `Preparing export…`; the backend manifest is the only
  authority on what the bundle contains.

## Phase 23B — Full External Application Adapters + MineExchange 1.3 (rules 207–212)

`docs/external-adapters.md` §23 is the contract. Architecture summary:

- **MineExchange 1.3 (rule 208).** `exchange/builder.py::project_timeline`
  projects the MineTimeline artifact into `operations/timeline.json`
  (`ExchangeTimeline`: tasks with an external `targetReference`, development
  progress, production state machines, metrics) and `operations/tasks.csv`;
  `TIMELINE_ARTIFACT` joins the export snapshot; the preflight binds every
  task / progress / state to exported edges, centerlines and production
  entities. Additive over 1.2 — geometry binaries byte-identical, the
  `TIMELINE` omission now `ARTIFACT_ABSENT` / `SOURCE_NOT_SUCCESS`.
- **Boundary (rule 207).** `services/adapter_service.py` runs the
  MineExchange export (one coherent snapshot) and hands the adapter the
  bundle BYTES; `adapters/bundle_reader.py` re-reads them by manifest (safe
  paths, SHA-256 of every listed file, no unlisted entry, DTO validation on
  demand, DXF handles from `files[].dxfEntities`, `LOCAL_ENU_Z_UP` metre
  contract). The adapter import graph never reaches a MineGen service,
  artifact reader or store (`tests/test_adapters_core.py`); nothing is
  persisted. `adapters/registry.py::ADAPTERS` maps the four targets to
  `bytes → AdapterPackage` builders; `adapters/common.py` holds the shared
  consumption helpers (five-state mapping, network / centerline / timeline
  documents, NOT_PROVIDED assumptions); `adapters/package.py` writes the
  deterministic ZIP with `adapter_manifest.json` (`AdapterManifest`) last.
- **Ventsim (rule 210).** `adapters/ventsim/adapter.py`: the bundle DXF
  copied verbatim (full fidelity), one airway row per network edge with an
  owning centerline (weld and length verified, never repaired), node table,
  handle ↔ entity ↔ edge identity map, every ventilation property
  NOT_PROVIDED, RAISE a typed omission.
- **AnyLogic (rule 211).** `adapters/anylogic/adapter.py`: requires 1.3 +
  network + timeline; normalized `data/*.csv` (nodes, edges, centerline
  points, capabilities, production units with retained / backfill flags,
  tasks, development progress, production states) with referential
  integrity re-verified, plus a blank `templates/simulation_inputs.csv`.
- **Unity / Unreal (rule 212).** `adapters/engine/glb.py` splits / joins the
  GLB container and adds ONE root node with the mine → glTF matrix to a
  copied `LOCAL_ENU_Z_UP` render GLB (binary chunk preserved, never twice);
  `adapters/engine/package.py` emits `scene/assets/*.glb`, the
  `scene/entities.json` identity authority, verbatim network / capability /
  timeline documents and `import_settings.json` with engine notes.
- **API + frontend (rule 209).** `api/adapters.py`: `POST …/export/{ventsim
  | anylogic | unity | unreal}` → `application/zip` with adapter headers;
  typed `ADAPTER_*` refusals. The Scenario panel's compact export selector
  (`describeExportTargets`, `api.exportAdapter`) offers MineExchange plus the
  four adapters with one Export button; the download mutates no viewer state.

## Phase 23C — External Simulation Results & MineGen Overlay (rules 213–218)

`docs/simulation-results.md` is the contract. Architecture summary:

- **Contract.** MineResult 1.0 (`results/models.py`, `MINE_RESULT_VERSION =
  "1.0.0"`; MineExchange stays 1.3.0) — a result is an OBSERVATION bound to
  the exact MineExchange `sourceSnapshot` and to MineNetwork edge ids; it is
  never a mine authority, never a fingerprint input, never exported back.
- **Observation, once.** `ExchangeService.observe(…)` is the ONE observation
  the export and the result binding share: `observe_source_snapshot` yields
  the snapshot identity (no world load), `observe_edge_centerlines` the edge
  identity space through the same `exchange/builder.py::assemble_centerlines`
  (extracted from `_excavations`, byte-identical export) and `project_network`.
- **Import.** `services/result_service.py`: observe → `results/package.py`
  (ZIP safety, budgets, manifest, version) → bind (scenario, snapshot) →
  `results/importers/{ventsim,anylogic}.py` (explicit identity, canonical
  units through `results/units.py`, declared axis, sorted NaN-missing arrays)
  → `results/normalization.py` (canonical digest, deterministic resultId,
  NPZ) → re-observe under the scenario lock → `results/store.py` atomic
  publication under `data/scenarios/{id}/results/<resultId>/`.
- **Reads.** COMPATIBLE / STALE against the current snapshot on every read;
  `results/frames.py` slices the stored arrays (hold-last ventilation,
  same-edge vehicle interpolation, hold-last edge metrics) and
  `results/export.py` rebuilds the canonical ZIP through the deterministic
  adapter package writer. `api/results.py` maps every `ResultError` to its
  wire code and status.
- **Kits.** `adapters/roundtrip.py` adds the additive `roundtrip/` folder to
  the Ventsim / AnyLogic packages (adapters 0.2.0).
- **Frontend.** `types/results.ts`, `api/client.ts` (upload / list / detail
  / delete / export / geometry / frames), `stores/resultsStore.ts`
  (frontend-only, reset by `scenarioSession`), `results/` (format, colour
  scale, overlay geometry, `SimulationOverlayController` outside the canvas),
  `components/panels/SimulationResultsPanel.tsx` + `…Body.tsx` (the fifth
  Analysis tab, mounted beside the read panel), `scene/VentilationResultLayer`
  and `scene/OperationsResultLayer` behind the `ventilationResult` /
  `operationsHeatmap` / `operationsVehicles` layers.

## Phase 21A — Mining Method Core, Longhole migration, MineExchange 1.1 (rule 192)

- **One registry.** `mining/methods/registry.py::plan_for(method)` is the
  single authority that maps a `MiningMethodType` to its `MiningMethodPlan`
  (`mining/methods/contracts.py`, a Protocol: `method`,
  `implementation_status`, `display_name`, `production_development(scenario)`,
  `production_lattice(scenario)`, `generate_production(...)`). Every enum
  member is registered EXPLICITLY — `LongholeOpenStopingPlan`
  (`methods/longhole.py`, IMPLEMENTED) wraps the untouched
  `LongholeOpenStopingStrategy`; CUT_AND_FILL, ROOM_AND_PILLAR,
  SUBLEVEL_CAVING and SHRINKAGE_STOPING are `UnsupportedMethodPlan`s
  (`methods/unsupported.py`). `plan_for` never returns `None` and an
  unregistered member is a typed `UnknownMiningMethodError`, so no path can
  fall back to longhole geometry. `methods/base.py` (`strategy_for`) is gone.
- **WHAT vs WHERE.** The plan owns the declarative intent: the
  `ProductionDevelopment` status / reason the level builder records, the
  station lattice (`ProductionLattice(pitch = stope_length + minimum_pillar,
  margin = stope_length / 2 + minimum_pillar)` — the exact Phase 08 / 20C.2A
  arithmetic, `None` for an unsupported method) and the production generator.
  `levels/builder.py::LevelDevelopmentBuilder` keeps WHERE and validity: it
  asks `self.plan` for the lattice offsets and develops the generic backbone
  drift for every method; `services/design_service.py::generate_stopes` calls
  `plan_for(method).generate_production(...)`. No method `if` remains in
  either consumer (`tests/test_mining_method_registry.py` scans the sources).
- **Longhole parity gate.** `tests/test_mining_method_parity.py` compares the
  migrated `levels.json` / `stopes.json` against structural summaries and
  canonical-JSON digests captured on the pinned pre-migration HEAD 39c293e
  (`tests/fixtures/phase21a/longhole_parity.json`, written once by
  `scripts/phase21a_capture_parity.py`, which refuses any other HEAD):
  TABULAR legacy (34 stopes), TABULAR layout-v2, CUT_AND_FILL (generic
  backbone, UNSUPPORTED_METHOD, FAILED stopes) and WARPED-301 (the rule 135
  `ExactDistanceRequiredError` typed boundary). The gate is two-tier
  (`phase21a_parity_support.py::parity_differences`): HARD — structure,
  ids, counts, station indices, ordering, strings, bools exact; NUMERIC —
  floats within 1e-10 rel / abs (the same code printed
  `1085.4613279254309` on one CI runner and `…306` on another; byte
  identity across CPUs is not a Longhole invariant). The full digests are
  recorded as an advisory property, never asserted. Goldens untouched. No new persisted artifact
  (no `mining_method_plan.json`), `Stope.method` stays the
  `LONGHOLE_OPEN_STOPING` literal, every pre-21A failure string is preserved.
- **MineExchange 1.1** (`docs/mine-exchange.md`): `stopes.json` joins the
  export snapshot; `semantics/mining_method.json` (always present),
  `production/stopes.json` + one authoritative closed prism per stope
  (STL / OBJ / GLB, independent closed-solid QA, volume agreement), the
  `STOPE` entity kind, STOPES omission semantics `ARTIFACT_ABSENT` /
  `SOURCE_NOT_SUCCESS` (TIMELINE stays `NOT_IN_V1`), and
  `check_method_authority` (scenario ↔ levels ↔ stopes method agreement, a
  typed 409). Stopes export without a network; with one, access node ids are
  cross-checked. The export projects; it never creates.
- **Frontend.** `build_scene` adds the read-only `miningMethod` block
  (method, display name, implementation status, parameters) computed from
  the registry; the Mining tab shows it as a `WorkflowCard` above Stopes
  (Implemented / Not implemented, parameters in Details, no selector — an
  unsupported method is a feature boundary, not a mine failure). The export
  contents readout gains the "Mining method" and "Stopes" rows. `PanelTabs`
  arrow / Home / End keys now move DOM focus with the selection
  (`ui/interaction.ts::focusTab`, Phase 20E §37 follow-up).
- **Non-scope (at 21A).** Cut & Fill (21B) and Room & Pillar (21C) production
  geometry, drawpoint / pillar / backfill / room / cut / bench entities —
  delivered by Phase 21B/C below.

## Phase 21B/C — Cut & Fill + Room & Pillar production methods (rules 193–196)

- **Registry table.** `plan_for` now resolves CUT_AND_FILL to
  `methods/cut_fill.py::CutFillPlan` and ROOM_AND_PILLAR to
  `methods/room_pillar.py::RoomPillarPlan` (both IMPLEMENTED); SUBLEVEL_CAVING
  and SHRINKAGE_STOPING stay `UnsupportedMethodPlan`s. The plan protocol grew
  three members every consumer uses INSTEAD of the method:
  `production_access_pattern(scenario)` — `StationLatticeAccessPattern`
  (Longhole, the exact Phase 08 arithmetic, defines the drift extent) or
  `FixedAccessPattern` (one central production CROSSCUT per level at offset
  0, drift extent from the generic backbone) — consumed by
  `levels/builder.py`; `production_identity(payload)` and
  `production_schedule(scenario, payload, ctx)` consumed by
  `scheduling/builder.py`. The source scan in
  `tests/test_mining_method_registry.py` keeps every consumer free of
  `if method ==`.
- **One production artifact.** `derived/stopes.json` is the legacy path of
  the ACTIVE production artifact; its payload is the `method`-discriminated
  union `ProductionPayload = StopesPayload | CutFillPayload |
  RoomPillarPayload` (`mining/models.py`), parsed structurally by the
  `ArtifactReader` through the new generic `ReadSpec.parser`. `POST/GET
  …/design/production` is the method-generic route (`DesignService.
  generate_production` / `production`); `…/design/stopes` stays Longhole-only
  and answers 409 `PRODUCTION_METHOD_MISMATCH` otherwise. The scene's
  `stopes` slot carries the union and `miningMethod` grows
  `methodParameters`, `productionKind` and the registry's `availableMethods`
  table with canonical `defaultParameters`.
- **Parameters.** `MiningConfig.methodParameters` is the typed union
  `CutFillParameters (liftHeightM 4, cutLengthM 15) | RoomPillarParameters
  (roomWidthM 8, pillarWidthM 6, headingHeightM 5, benchCount 1|2,
  boundaryPillarM 6)`: resolved to canonical defaults when omitted for a
  method that has one, 422 for a block under a method without one or of the
  wrong kind, omitted from serialization for Longhole (document unchanged).
- **Cut & Fill geometry** (`methods/cut_fill.py`, TABULAR-only, typed
  `METHOD_GEOMETRY_NOT_IMPLEMENTED` otherwise): per adjacent level interval,
  lifts are the equal partition of the down-dip span into ≈ `liftHeightM`
  vertical slices (`dv = liftHeight / |v_z|`), cuts the equal partition of
  the strike extent into ≈ `cutLengthM`; order is lowest lift first, cuts in a
  snake (even lifts −u → +u, odd +u → −u); each cut is an 8-corner prism in the
  analytic frame under the Phase 09 hard QA (`methods/solids.py::build_solid`:
  closed solid, volume agreement, hard samples, finite) with the rule 130
  grade proxy; backfills are 1:1 semantic records (`sourceCutId`, volume);
  the access is the lower level's central CROSSCUT. No partial SUCCESS.
- **Room & Pillar geometry** (`methods/room_pillar.py`, TABULAR-only):
  alternating room / pillar bands along u and v with pitch `roomWidth +
  pillarWidth` centred so u = 0 / v = 0 fall in a room band, the panel inset
  by `boundaryPillarM`; a cell is ROOM iff its u-band OR v-band is a room
  band, else PILLAR; `RoomCell` is a semantic parent of its extraction units
  HEADING / BENCH_1 / BENCH_2 (`thickness_stages`: a heading ≥ thickness →
  one HEADING); pillars are retained solids (`tonnesEquivalent`, no
  evaluator, never scheduled); access = the level nearest the cell's v
  centroid. Metrics are geometric planning quantities (extraction fraction =
  mined / panel). `MAX_PRODUCTION_SOLIDS = 8000` (default scenario: 7,322)
  is the typed complexity limit.
- **Timeline.** `MineTimelineBuilder` keeps the development schedule and
  executes the plan's `ProductionScheduleSpec` (tasks + `TaskBasis`, per-unit
  transitions bound to task boundaries, `tasks_per_unit` aggregate check);
  the Longhole spec is the Phase 10 stope chain moved verbatim (bytes
  unchanged). Cut & Fill: one conservative chain PREP → STOPING → MUCKING →
  BACKFILL → CURE per cut after its access task and the previous cut's CURE
  (`targetKind = CUT`, states ACTIVE / MINED / VOID / BACKFILLED). Room &
  Pillar: PREP → STOPING → MUCKING per extraction unit, HEADING → benches in a
  cell, cells outward from the central cell by Manhattan index distance
  (`targetKind = ROOM_EXTRACTION`, states ACTIVE / MINED / VOID), pillars
  never scheduled. `TimelinePayload.production {method, targetKind, units}`
  and `production*` metrics exist only for non-Longhole methods.
- **Longhole regression gate.** `tests/fixtures/phase21bc/longhole_baseline.json`
  (LEGACY default 34 stopes / LEGACY welded 105 edges, 275 tasks / LAYOUT
  small 15 stopes, 49 edges, 124 tasks / WARPED typed boundary) captured on
  the pinned HEAD 7052606 by `scripts/phase21bc_capture_baseline.py`;
  `tests/test_longhole_baseline_21bc.py` compares levels, stopes, network and
  timeline under the rule 192 two-tier gate. One cross-runner artefact is
  classified, never absorbed: a sampled `pointCount` / `fractionCount` that
  flips by exactly one where the piece length sits within float noise of an
  exact `SAMPLE_SPACING` multiple (measured on PR #47 CI: `DRIFT:L01:09`,
  10.00000000000001 m → 7 points locally, 10.0 m → 6 on the CI CPU); it is
  recorded as a test property and every other difference stays BLOCKING.
  The rule 192 parity fixture is untouched; its CUT_AND_FILL case is
  retained as a historical record and explicitly superseded.
- **PR #47 review round.** (1) The rule 159 regression test compares the
  backbone DRIFT pieces AND the single central production CROSSCUT of two
  Longhole-parameter variants pairwise. (2) `mining/methods/integrity.py`:
  `cut_fill_integrity` / `room_pillar_integrity` run at the entry of each
  plan's `production_schedule` — a structurally valid but corrupted
  production payload (a cut without its backfill record, two backfills for
  one cut, a backfill volume disagreeing with its cut, a duplicate room /
  unit / pillar id, a room ↔ unit membership mismatch) is a typed FAILED
  timeline (`tests/test_production_timeline.py`). (3) Frontend isolation:
  `scenarioStore.replaceScenarioDocument` + `activateScenarioRevision`
  make a same-id scenario PUT a revision transition (epoch + 1, scene / jobs
  / slice / day cursor / scenario-scoped viewer state cleared; regression in
  `stores/scenarioSession.test.ts`), and the Mining-method card's draft is
  keyed by the revision identity through `reconcileMiningDraft`
  (`MiningMethodCard.test.tsx`). (4) Rendering: `scene/productionBatches.ts`
  + `solidGeometry.mergeSolids` batch the production solids per (kind,
  validity) and per 4D state; measured on the default Room & Pillar
  scenario (7,322 solids, SwiftShader): Design 14,797 → 157 draw calls per
  frame and 638 → 213 ms per frame, 4D 14,744 → 106 draw calls and 619 →
  199 ms, 20-step 4D scrub 75.7 s → 24.6 s. Second review round: the 4D
  merged geometries are keyed by the state revision (`transitionDays` /
  `stateRevisionAt`, membership constant between transition days) instead of
  the day, and replaced / unmounted merged geometries are disposed — playback
  frames inside one revision rebuild nothing. (5) A reserved method reports
  `productionKind = null`; the UI shows the sublevel interval only and a
  disabled "Not implemented" production action. (6) The exporter's
  `_flat_triples` guard turns a ragged / non-numeric coordinate list into a
  typed `ExchangeExportError`.
- **MineExchange 1.2.0** (`docs/mine-exchange.md`): typed method-parameter
  DTOs in `semantics/mining_method.json`, `production/cut_fill.json` +
  `production/cut_fill/cuts/<id>.{stl,obj,glb}` (CUT solids, BACKFILL
  semantic entities referencing their cut, no geometry file),
  `production/room_pillar.json` + `production/room_pillar/{benches,pillars}/`
  (ROOM semantic parents, BENCH / PILLAR solids), one production omission
  group per bundle (the active method's), the shared `_export_prism`
  exporter (verbatim vertices, independent closed-solid QA, volume
  agreement), and `check_method_authority` extended to the payload SHAPE.
- **Frontend.** `MiningMethodCard` (selector over `availableMethods` with
  Implemented / Not implemented labels, method-specific parameter inputs,
  Apply = `PUT /scenarios/{id}` → `POST world/generate` → scene reload),
  the generic Production card (`Generate Stopes / Cut & Fill / Room &
  Pillar`, kind-specific details), `scene/production.ts` adapter,
  `ProductionLayer` (kind colours: stope / cut / bench / pillar) and
  `TimelineProductionLayer` (states from the backend transitions; pillars
  drawn as retained material), the Layers row "Production", export-contents
  row named after the active production kind.
- **Non-scope.** Sublevel Caving, Shrinkage Stoping, WARPED_VEIN production
  geometry, production-room walkthrough colliders, geotechnical pillar
  design.

## Phase 22A/B — Mine Analysis Core + Planning Economics (rules 197–202)

- **Position in the architecture.** A downstream READ-ONLY projection like
  the Phase 20D.3 assessment: `services/analysis_service.py` binds the
  scenario document through `ScenarioStore.get_bound` (the stat → get →
  re-stat protocol extracted from `WorldService._bound_scenario`, which now
  delegates to it — PR #48 review blocker), takes ONE `ArtifactReader`
  snapshot of `network.json`, `stopes.json` (the active production
  artifact) and `timeline.json` with `expect_scenario_revision` = the bound
  revision (a same-id PUT between the two is `READ_SNAPSHOT_CHANGED`, never
  an old document beside new artifacts), observes `economics.json` under the
  same store lock, projects through the pure `analysis/builder.py`, then
  re-observes every consumed source — scenario, arrays, the world commit
  record, the three artifacts, `economics.json` — and answers
  `READ_SNAPSHOT_CHANGED` on any movement. Nothing is generated, persisted or invalidated; no job runs;
  no `derived/analysis.json` exists. Ramp / levels / shafts are not read —
  the network is the development authority — so they are not part of the
  consistency set.
- **Sections and availability.** `MineAnalysisPayload {status, sources,
  development, production, schedule, ratios, economics}`; each section carries
  `availability` (AVAILABLE | NOT_AVAILABLE | NOT_CONFIGURED) and a backend
  `reason`. An absent or FAILED source is a normal partial 200; a world that
  is not generated makes every derived section NOT_AVAILABLE (derived files
  are never trusted without a VALID world, AC-01F). A SUCCESS timeline whose
  network or production owner is missing is `ANALYSIS_SOURCE_INCONSISTENT`,
  never a partial section.
- **Integrity boundary (`analysis/integrity.py`).** Network: unique node /
  edge ids, endpoints exist, finite positive `length3d` and `analyticArea`,
  declared `NetworkMetrics` counts exact and lengths within 1e-6 m of the
  edge sums (never overwritten; residuals reported in `crossCheck`).
  Production: method agreement with the scenario, unique unit ids, finite
  non-negative quantities, the Cut & Fill / Room & Pillar semantic
  relations through the SAME `mining/methods/integrity.py` helpers the
  timeline builder and MineExchange use, and the persisted `metrics` block
  re-derived from the records (`verify_production_metrics`: counts, level
  intervals, the lift ↔ cut partition, total volume / tonnes, heading /
  bench counts, retained pillar volume, the extraction fraction against
  `panelVolumeM3`, the tonnage-weighted grade proxy; the orebody-relative
  fraction and `stationsPerInterval` are not re-derivable and stay as
  persisted). Timeline: unique task ids, `0 ≤
  start ≤ end`, duration = end − start, dependencies exist, every
  DEVELOPMENT target is a network edge with a metre basis equal to its
  `length3d` and every edge has exactly one development task, every
  production target is a production object with STOPING / MUCKING bases
  equal to its tonnes and a BACKFILL basis equal to the backfill volume
  (the Cut & Fill backfill record, the Longhole stope volume; unit `m3`),
  the method's required task types per unit (Longhole /
  Room & Pillar: STOPING + MUCKING; Cut & Fill: + BACKFILL), and
  `metrics.firstStopingDay` equal to the earliest STOPING start.
- **Development (22A).** Categories in `EdgeType` order (RAMP, LEVEL_ACCESS,
  DRIFT, CROSSCUT, RAISE, SHAFT, SHAFT_STATION_ACCESS) with edge count, total
  length and `grossExcavationVolumeM3 = Σ length3d × analyticArea`; totals
  named `grossDevelopmentVolumeM3` (junction overlap not unioned).
- **Production (22A).** Method-generic summary (`productionObjectCount`,
  `totalProductionVolumeM3`, `totalPlannedMinedTonnes`,
  `weightedMeanGradeProxy` — informational) plus a discriminated `detail`:
  Longhole `{stopeCount, levelIntervalCount}`, Cut & Fill `{cutCount,
  liftCount, backfillCount, totalBackfillVolumeM3}` (backfill is not
  production), Room & Pillar `{roomCount, extractionUnitCount, pillarCount,
  headingCount, benchCount, retainedPillarVolumeM3,
  retainedPillarTonnesEquivalent, geometricExtractionFraction}` (pillars are
  retained material). No resource / reserve tonnage exists anywhere.
- **Schedule and ratios (22A).** Task counts, `startDay`, `endDay`,
  `mineDurationDays`, `rampCompletionDay`, `firstProductionDay` (earliest
  STOPING start, generic); `developmentMetresPerKt` and
  `grossDevelopmentM3PerKt` when planned mined tonnes > 0, else null with a
  reason.
- **Economics config (22B, `analysis/economics.py`).** `EconomicsConfig`
  (version 1, `currencyCode ^[A-Z]{3}$`, seven development rates per metre —
  one per `EdgeType`, RAISE included —,
  three production rates per tonne, processing / backfill / fixed-opex /
  gross-revenue rates, initial capital, annual discount rate ≥ 0, bucket days
  > 0; every float finite and non-negative) is persisted as
  `data/scenarios/{id}/economics.json` by `publish_text` (atomic) with
  revision `sha256(canonical JSON)`. It is not registered, not a fingerprint
  input, not cascaded: `PUT …/analysis/economics-config` leaves every derived
  file byte- and stat-identical (test B-5), and a scenario PUT does not
  delete it. Absent → `{configured: false, revision: null, config: null}`;
  malformed → 409 ARTIFACT_MALFORMED; invalid input → 422.
- **Costs, cashflow, NPV (22B, `analysis/cashflow.py`).** Rule 202 fixes the
  allocation and the discounting convention; `BucketLedger` holds one column
  per cost / revenue kind, `allocate_linear` gives overlap fractions summing
  to 1 (a zero-length interval is a point event; the last bucket is closed at
  the mine end), `build_buckets` derives net / cumulative / discounted per
  bucket. The summary's `totalCost` is the sum of its six components; bucket
  columns reconcile with the summary; rate 0 ⇒ NPV = undiscounted net.
- **Wire.** `GET …/analysis` (sync), `GET / PUT …/analysis/economics-config`;
  new code 409 `ANALYSIS_SOURCE_INCONSISTENT` in the shared `api/errors.py`
  table; `ArtifactMalformedError` / `ReadSnapshotChangedError` reused.
- **Frontend.** `AnalysisWorkspace` (Overview | Economics) for the existing
  `ANALYSIS` mode: `AnalysisPanel` runs two read-only react-query reads keyed
  on the scenario epoch, the scene identity and the economics revision (a
  response of a previous scenario / revision never populates the current
  one) and one mutation (save assumptions → `setQueryData` +
  `invalidateQueries(['mine-analysis'])`; no epoch bump, no scene clear,
  no generation). `EconomicsConfigEditor` edits explicit strings under the
  identity `scenarioId:economicsRevision` (`economicsDraft.ts`), validates
  client-side only to enable Save (the backend 422 stays the authority) and
  offers "Use demo assumptions — DEMO / SYNTHETIC ASSUMPTIONS" on an explicit
  click. `CashflowTable` renders the backend buckets and an inline SVG (no
  chart dependency). Labels: "Planned mined tonnes", "Gross development
  volume", "Grade proxy", "Baseline duration", "Planning NPV"; the disclaimer
  is always visible on the Economics tab.
- **Tests.** `tests/analysis_support.py` (hand-built round-number mine),
  `tests/test_analysis_builder.py` (A-1…A-11, B-2…B-4, B-6…B-20 with a
  hand-calculated NPV), `tests/test_analysis_api.py` (e2e: partial 200,
  config roundtrip / revision / 422, B-5 zero invalidation, Longhole / Cut &
  Fill / Room & Pillar chains, determinism, corruption 409, snapshot race,
  one config over three methods); frontend `AnalysisPanel.test.tsx`,
  `economicsDraft.test.ts`, `workflowPreservation.test.ts`.
- **Non-scope.** IRR / tax / depreciation / royalty / inflation /
  sensitivity, candidate what-if economics, ventilation / haulage /
  capacity, external adapters (23B).

## Phase 22C — Design Rulebook + Layout Development Economics (rules 203–206)

- **Design Rulebook (rule 203).** The Analysis **Rules** tab is a
  presentation of the Phase 20D.3 design assessment: `AnalysisPanel` reads
  `GET …/design/assessment` under the SAME react-query key the Layout panel
  uses (one cache entry, one read model) and `RulebookPanel` renders every
  `AssessmentCheck` as Category · Rule · Status · Authority · Scope ·
  Evidence through the pure mappings in `panels/rulebook.ts`
  (`rulebookStatus`, `evidenceText`). Hard rules / validations keep ✓ / ✗ /
  ? / —, an advisory reads "Advisory satisfied / not satisfied" with the
  non-statutory note and never the ✓ mark, an informational row reads
  "Info", NOT_EVALUATED stays NOT EVALUATED, and no overall score exists.
  No backend change and no second evaluator.
- **Layout comparison (rules 204–206, `analysis/layout_comparison.py`).**
  `AnalysisService.layout_comparison` follows the 22A/B protocol — bound
  scenario read, ONE snapshot of `layout_v2.json`,
  `layout_v2_selected.json`, `level_accesses.json` (the selection's pair
  unit) and `ramp_source.json` at that revision, `economics.json` observed
  beside them, the ramp source resolved FIRST, projection through the pure
  `build_layout_comparison`, every source re-observed
  (`READ_SNAPSHOT_CHANGED` on movement). The builder applies the shared
  `validate_catalogue_shape` and then the consumer-specific
  `validate_layout_economics_shape` (finite non-negative
  `diagnostics.length3d` / `access.totalAccessLength` for every RANKED
  candidate; `CatalogueShapeError` → 409 `ARTIFACT_MALFORMED`; the fields
  stay optional for the assessment) and emits one
  `LayoutDevelopmentComparisonRow` per ranking entry in the persisted order:
  the two persisted lengths, `length × rate` costs (`None` when
  `economics.json` is absent — NOT_CONFIGURED keeps the geometry rows),
  plain `candidate − winner` / `candidate − selected` cost deltas and the
  20D.3 `ComparisonScores` / `ScoreDeltas` through the now-public
  `assessment.builder.comparison_scores` / `score_deltas`. `comparisonBasis`
  names the included (`RAMP`, `LEVEL_ACCESS`) and excluded kinds. Nothing is
  written, ranked, selected or recomputed; no per-candidate artifact exists.
- **Wire.** `GET …/analysis/layout-comparison` (sync, 200 for absent
  catalogue / economics, typed 409 refusals through the shared error
  ladder — no new code). Frontend: `ANALYSIS_TABS` = Overview | Economics |
  Rules | Layout comparison; `LayoutComparisonPanel` (summary card, ranking-
  order table, optional bar chart, scores in Details) keyed on epoch + scene
  identity + economics revision; saving the assumptions invalidates
  `mine-analysis` and `layout-comparison` only.
- **Tests.** `tests/test_layout_comparison.py` (C-1 formula, C-2 ranking
  preservation, C-3 no hidden economics, C-4 scope, C-5 malformed → typed
  shape error / 409 and the assessment isolation, C-6 races on scenario /
  catalogue / selection / economics, C-7 read-only proof, C-8 no generation
  entry point, C-9 vocabulary, C-10 determinism, plus the REAL catalogue
  e2e); frontend `RulebookPanel.test.tsx`, `LayoutComparisonPanel.test.tsx`,
  `analysisIsolation.test.ts`.
- **Non-scope.** Candidate regeneration, candidate NPV / IRR / payback,
  tax / royalty / depreciation / inflation, pricing / grade revenue /
  recovery, ventilation / haulage / fleet / capacity, Monte Carlo,
  auto-selection or optimization, 23B adapters, calibration, resources /
  reserves.
