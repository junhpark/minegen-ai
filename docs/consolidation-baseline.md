# Architecture consolidation baseline — AC-01B

**Baseline revision: `d58c794e143c34fd63e74f5ce3948fbf10e0ef64` (main, PR #28 merged).**

This document fixes the reference point every AC (Architecture Consolidation)
step is measured against. It is a MAP and a SCOPE INDEX, not a new authority:
it changes no rule, no gate, no threshold and no engineering judgement, and it
claims no test run of its own. Where it records a past measurement it names the
run that produced it.

## 1. Baseline identity

| item | value |
|---|---|
| baseline commit | `d58c794` — "Phase 20C.4: level-access reference consistency — construction ServiceReference (#28)" |
| previous audit baseline | `9d1a8bb` (Phase 20C.3A closeout) — the Architecture Reality Report (an EXTERNAL review document, not in this repository) was written against it; its F-numbering is reproduced in §10 so a reader without it can still follow the sequence |
| production delta `9d1a8bb → d58c794` | `backend/src/minegen/layout/`: `reference.py` **+395 (new)**, `families.py` +285/−4, `search.py` +30. No other production file, backend or frontend, changed |
| rule delta | `CLAUDE.md` rule **186** (construction ServiceReference) added; no earlier rule reworded |
| verification of that revision | FULL PASS on `28e7033` (the code content of `d58c794`), backend 604 passed / 0 failed, frontend typecheck / lint / prettier / vitest 263 / build PASS, collection coverage all = full = 604, fast = 519. Recorded in `docs/verification/phase20c4_gate_c.md` §12 |

The Architecture Reality Report deliberately excluded PR #28 from its baseline
because the PR was still open. It is now merged, so the ServiceReference
(`layout/reference.py`, rule 186) IS part of the baseline: a construction
reference consumed by the SPIRAL and SWITCHBACK corridors, not a stage-4
feasibility authority. Any later AC step that lands on a newer main re-fixes
this table on that SHA and re-checks only the parts its diff touched.

## 2. Package inventory (`backend/src/minegen`, baseline)

| package | .py files | lines (`wc -l`) | note |
|---|---|---|---|
| api | 9 | 1,320 | HTTP surface + jobs |
| capability | 3 | 623 | semantic overlay over MineNetwork ids |
| core | 6 | 1,487 | models, enums, coordinates, artifact names |
| design | 15 | 5,305 | shared engineering judgement + sweeps |
| export | 2 | 231 | scene projection |
| geometry | 1 | 1 | **empty package marker** — the sweeps live in `design/` |
| infrastructure | 7 | 1,681 | communication / sensors over the physical network |
| layout | 9 | 6,556 | parametric families, sections, access, search, reference |
| levels | 3 | 1,059 | level development builder |
| mining | 5 | 604 | mining-method strategies (LONGHOLE only) |
| network | 3 | 908 | MineNetwork builder / models |
| regression | 7 | 2,583 | golden suites and audits |
| scheduling | 3 | 901 | timeline builder |
| services | 9 | 2,674 | load / cache / orchestrate / persist / invalidate |
| shafts | 3 | 1,001 | shaft planner |
| simulation | 3 | 3 | **placeholder package** — no solver exists |
| world | 8 | 2,081 | terrain, orebody solids, spatial fields |

`geometry/` and `simulation/` are reserved names, not implementations. Reading
the tree as if they were populated is the most common map error; the module map
below is the current truth.

## 3. Verification authority (post AC-01A)

Before AC-01A the persisted `fullAuthority` was `mode == "full" and not
failed`. Evidence, the identical zero-step FULL call against both revisions in
this repository:

```
BEFORE main d58c794: fullAuthority=True  gitDirty=True steps=0 feTypecheck=NOT_RUN reasons=0
AFTER  AC-01A      : fullAuthority=False gitDirty=True steps=0 feTypecheck=NOT_RUN reasons=12
```

The corrected contract, its typed reasons, the component / aggregate split and
the PR-merge-simulation SHA record are specified in
`docs/verification.md` → "Release authority (AC-01A)". Two consequences for
this baseline:

* `fullAuthority = true` values quoted in phase documents dated before AC-01A
  were produced by the weaker expression. They are kept as historical records
  and are not re-certified here.
* A FULL result is evidence for its own `certifiedSha` only. On a GitHub
  pull-request run that SHA is a synthetic merge commit, recorded distinctly
  from `ci.prHeadSha`; when the PR head cannot be read the kind is
  `PULL_REQUEST_SHA_UNVERIFIED`, never the reassuring label.

Two further defects in the same evidence layer were found while reviewing
AC-01A and are fixed with it:

* the advertised proof `collected(FULL) == collected(unfiltered)` was
  TAUTOLOGICAL — both sides were the same `collect-only` call, so
  `missingFromFull` and `unexpectedInFull` could never be non-empty. The
  substantive parts (`excludedFromFast ⊆ FULL`, `FAST ∪ excluded == FULL`)
  did hold. Authority now additionally requires `executedFull` — the count
  the junit report of the pytest step that actually ran — to equal
  `collectedFull`, which is not true by construction.
* the runner's own coverage gate checked 2 of the 5 conditions
  `collect-full` checks, so a `fastAndExcludedOverlap` printed PASS and
  exited 0. `cmd_full` and the authority judgement now share one
  `_coverage_ok`, and the proof is recorded as a `collection-coverage` step
  so a coverage-only failure is attributable in `failedSteps`.

## 4. Change prohibitions for every AC step

Unchanged in a pure consolidation step, and named explicitly in each PR:
hard gates, tolerances and thresholds, score coefficients and ranking,
golden expectations, screen authority (rule 176), coordinate transforms,
geometry sampling, and failure semantics. A step that must change observable
API behaviour or an artifact schema states that separately from the
mechanical extraction and carries its own approval.

Merge authority for a production consolidation PR is a FULL run whose
`authority.release` is true for the exact revision being merged. FAST and
FEATURE are development feedback and never substitute for it.

## 5. Module map (verified at the baseline)

The map in `docs/architecture.md` predates several phases; this is the tree as
it is. Entry points are given as `file:line` at `d58c794`.

| area | modules | authoritative entry points |
|---|---|---|
| Scenario | `core/models.py` (1,060), `services/scenario_realizer.py`, `services/scenario_service.py`, `services/scenario_migration.py` | `Scenario:1038`, `ScenarioCreate:961`; the store is the CLASS `ScenarioStore` in `scenario_service.py:28` — there is no `store.py` |
| World | `world/{synthetic_world,terrain,orebody,warped_vein,spatial_fields,field_grid,geology}.py` (2,080) | `generate_world():89`, `Orebody(ABC):41`, `AnalyticOrebody:104`, `ImplicitOrebody:120` |
| Shared engineering judgement | `design/{cost_field,constraints,profile,validation}.py` | `DesignCostEvaluator:215`, `ExactClearance:113`, `ConservativeClearance:127`, `RefinedConservativeClearance:169`, `clearance_policy_for():202` |
| Legacy ramp | `design/{targets,mine_designer,astar_3d,smoothing,motion_primitives}.py` | `generate_access_targets():173`, `ChainedDeclineGenerator:155`, `generate_level_elevations():128` |
| Parametric ramp | `layout/{families,geometry,validation,search,reference}.py` | `build_family():1299`, `enumerate_candidates():488`, `LayoutContext:537`; `reference.py` (395) is the PR #28 construction ServiceReference, built once per search (`search.py:808`) and consumed by `corridor_profile():564` / `switchback_corridor_profile():625` |
| Section / anchor | `layout/{levels,sections,access}.py` | `required_levels():66`, `build_section_geometry():333`, `build_footwall_trace():583`, `build_offset_trace():770` |
| Level development | `levels/{builder,models}.py` | `LevelDevelopmentBuilder:230`, `entries_from_level_accesses():113` |
| Shaft | `shafts/{planner,models}.py` | `ShaftPlanner:222`, `level_breakpoints():193` |
| Stope | `mining/methods/{longhole,base}.py`, `mining/models.py` | `LongholeOpenStopingStrategy:122`, `strategy_for():41`, `unsupported_method_payload():51` |
| Topology | `network/{builder,models}.py` | `MineNetworkBuilder:151`, `GeometryRef:34` |
| Capability | `capability/{builder,models}.py` | `CapabilityGraphBuilder:217`, `can_reach():162` |
| Time | `scheduling/{builder,models}.py` | `MineTimelineBuilder:184`, `solve_earliest_start():83`, `_resolve_centerline():130` |
| Infrastructure | `infrastructure/{network_domain,builder,sensors,solver,coverage,models}.py` | `InfrastructureNetworkDomain:93`, `CommunicationBuilder:56`, `SensorBuilder:55` |
| Services | `services/*.py` (8 modules, 2,673) | `DesignService:257` (1,455 lines), `WorldService`, `InfrastructureService` |
| API / export | `api/*.py` (1,319), `export/scene_manifest.py`, `main.py` | `api/design.py` — 33 routes; `deps.py` — the five dependency providers |
| Frontend | `types/scene.ts` (1,385, 93 exports), `api/client.ts`, `scene/` (28 modules, 2,483), `timeline/`, `walkthrough/` | manual mirrors of the backend payloads |

Backend python totals 29,152 lines over 78 non-`__init__` modules (99 `.py`
files); frontend non-test TS/TSX 12,676 lines. `geometry/`, `simulation/`, `simulation/haulage/` and
`simulation/ventilation/` contain only a one-line `__init__.py` and have zero
importers — reserved namespaces, not implementations. `docs/architecture.md`
is corrected accordingly in this step; its per-phase decision records keep
their original wording.

**Correction, AC-01C.** The table above is the pinned `d58c794` snapshot and
its `file:line` entry points stay pinned there. AC-01C has since split
`layout/search.py` (1,553 → 1,036 lines): the result DTOs and their
serialization moved to `layout/results.py`, the clearance certification
(`ClearanceReport`, `anchor_standoff`, `build_candidate_policy`, the new
`CandidateCertification`) to `layout/certification.py`, and the selection /
level-access materialization to `layout/materialize.py`. Every name stays
importable from `layout.search` through an explicit `__all__`, so the
`layout/search.py::…` citations elsewhere in the docs remain literally true.

**Correction, AC-01D + AC-01G.** Two more splits have landed since, and the
1,036-line figure above is stale. AC-01D lifted the verbatim pre-stage-1 setup
block into `layout/setup.py` (103 lines) so the search-object-free
certification restore executes the SAME code. AC-01G then took the section
geometry and the stage bodies out: `layout/provider.py` (158 lines) owns the
CONSTRUCTION of one run's `LevelSections`, footwall track, serviceable levels
and `ServiceReference`, and `layout/stages.py` (≈ 880 lines) owns
`StageContext`, `AnchorLens`, the cheap and detailed stages, their outcome
DTOs, the two `CandidateResult` writers and the stage helpers and score
coefficients that moved with them. `layout/search.py` is 550 lines and is now
orchestration plus the deterministic ordering authority (`run`, `_result`,
`_stage_context`, `candidate_policy`, `_family_rank`, `_shortlist_key` /
`shortlist_key`, `_rank_key`, `_event`). `__all__` is unchanged at 40 names
and every moved name re-exports as the SAME object (`search.X is stages.X`,
asserted), so every `layout/search.py::…` citation stays literally true.

## 6. Artifact dependency and invalidation

Since AC-01E the derived-artifact graph is declared ONCE, in
`core/artifact_registry.py` (a leaf: stdlib + `core/artifacts.py` only), and
two projections are derived from it by one algorithm:

* **fingerprints** — `fingerprint_paths(name)` expands each artifact's
  ORDERED `inputs` (`FILE`, `INPUTS_OF` = the consumed artifact's expanded
  list, or the `EFFECTIVE_RAMP` group = `decline_smoothed.json`,
  `layout_v2_selected.json`, `level_accesses.json`, `ramp_source.json` in
  that order) into rooted paths; `services/design_service.py::artifact_fingerprint`
  captures them with `InputFingerprint.capture` — stat-based (name / exists /
  size / mtime_ns), so a byte-identical regeneration is a NEW revision
  (rule 60). Every public `*_fingerprint()` of `DesignService` and
  `InfrastructureService` is one call to it; the ORDER is declared per
  artifact because it reaches persisted `sourceRevision` / selection
  `revision` bytes (timeline puts the ramp bundle in the middle, network
  omits `arrays.npz`, …).
* **cascading deletes** — `invalidated_by(written, active_source)` is the
  transitive closure over the declared edges (`INPUTS_OF` contributes ONLY
  the edge consumed-artifact → consumer, never its inputs; the out-edges of a
  ramp-OWNING artifact — `decline_smoothed.json`: LEGACY,
  `layout_v2_selected.json` / `level_accesses.json`: LAYOUT_V2 — are
  traversed only while it is the ACTIVE source). One method,
  `DesignService._invalidate_downstream(scenario_id, *written, source=None)`,
  runs it INSIDE the writer's store lock immediately after the write, reading
  `ramp_source.json` at that point (`set_ramp_source` passes the value it just
  wrote). No service holds a delete list of its own.

The global choke point is unchanged and NOT registry-derived:
`WorldService.invalidate` → `ScenarioStore.clear_derived` (a directory walk
that also removes `derived/world.json` and unknown files), called from world
generation, scenario PUT and a schema migration on read
(`scenario_service.py:74-77`). **AC-01F commit 3** changed HOW two of those
callers reach it, not what it does:

* scenario PUT is now ONE locked section — `WorldService.replace_scenario`
  (`store.replace` + `invalidate` under the per-scenario `RLock`), called by
  `api/scenarios.py`. At the AC-01B baseline these were two separate critical
  sections, so between them the persisted document was the NEW one while
  `arrays.npz`, `derived/` and the world cache were still the OLD one (Stage A
  §5.2, R3b/R3d). The router obtains the service from a dependency (rule 40)
  and holds no lock of its own; `ScenarioStore.replace` is unchanged;
* the migration-on-read caller still bypasses the `WorldService._cache` drop
  (`clear_derived` is called directly). That quirk no longer has an
  observable consequence: the cache entry is bound to the `scenario.json` /
  `arrays.npz` revisions it was built at, so after a migration it simply
  MISSES — the pre-change literal was a warm-cache `GET /scene` **200** with
  all 17 derived keys `null` over a store the same read had just cleared
  (Stage A §7.3 / probe 2 §4.8), now 409 `WORLD_NOT_GENERATED`.

The two INPUT files are not registry artifacts but are inside the same
protocol from AC-01F commit 3:

| file | writer protocol | read binding |
|---|---|---|
| `scenario.json` | `ScenarioStore._write` from `create` / `replace` / the migration; `replace` runs inside `WorldService.replace_scenario`'s lock | `WorldService._bound_scenario`: stat → `ScenarioStore.get` → re-stat, REPEATED while the revision moves (≤ `SNAPSHOT_ATTEMPTS` = 3, then `READ_SNAPSHOT_CHANGED`). The A10 migration rewrites the document from inside `get`; the re-read absorbs it and binds the migrated revision, so it is never reported as a race (C4). `load_bound` then re-stats the SAME file under the lock and a document that moved across the cold load is `READ_SNAPSHOT_CHANGED` for the RESULT, symmetric with the `arrays.npz` half — Stage D B1: that re-stat used to gate the CACHE PUBLISH only while the `return` was unconditional, so `GET …/world` and `GET …/world/slice` still served the R3d mixed body (measured: ONE 200 with the OLD document's `orebody.center [40.0, 20.0, -50.0]` beside the NEW world's `terrain.zMax 116.367159085105`) |
| `arrays.npz` + `derived/world.json` | `WorldService._save`, now INSIDE the store lock and only after a re-check that `scenario.json` did not move during `generate_world` (→ `JOB_INPUTS_CHANGED`; the pre-change literal was a silently published world for the REPLACED document, Stage A §7.5 case A). `world.stats` is computed BEFORE the lock and handed in, so the lock holds the two writes and the cache publish only (WARPED-301: the lock holds `_save` alone, 0.62 s wall for a 10,245,989-byte `arrays.npz`; before the hoist 0.72–0.75 s with `world.stats` 0.099 s inside) | `file_revision` captured BEFORE `np.load`, and re-checked after it: deleted in that window → `WORLD_NOT_GENERATED`, replaced → `READ_SNAPSHOT_CHANGED` (never an escaping `FileNotFoundError`). The world cache entry is `(world, scenario_revision, arrays_revision)` and is served only while BOTH still match |

Where "DISK-authoritative" comes from, split by mechanism — the two halves are
different claims and neither implies the other:

* `WorldService.is_generated` is GONE (Stage D S11). It had no production
  caller after AC-01F and was never the live guard: it probed
  `arrays_path(sid).is_file()` while the guard the code actually applies is
  `file_revision(arrays.npz) is not None` — the two disagree wherever `stat`
  succeeds on a non-regular file (`arrays.npz` replaced by a directory:
  `is_generated` False, `file_revision` not None). Its two test call sites now
  stat `arrays.npz` directly. The production disk authority is `load_bound`'s
  stat plus the reader snapshot's stat, and nothing else;
* `GET …/world`, `GET …/world/slice` and `GET …/scene` are disk-authoritative
  because the cache ENTRY is revision-bound: they still consult the cache, but
  the entry is returned only when the `scenario.json` and `arrays.npz`
  revisions stat'ed on that very request still equal the ones the world was
  built at. The world guard itself (`arrays.npz` absent → 409
  `WORLD_NOT_GENERATED`) is the disk stat taken before the probe.

`tests/test_artifact_registry.py` holds the census below as frozen literal
tables (with the pre-AC-01E file:line provenance of every row) and checks both
the derivation AND the live public `*_fingerprint()` methods against them;
`tests/test_artifact_registry_e2e.py` regenerates every artifact through its
real route under both sources and asserts the removed-file set equals the
closure.

| artifact | fingerprint inputs (ORDERED) | regenerating it deletes | read path |
|---|---|---|---|
| `targets.json` | scenario + arrays — **AC-01F**: the last derived writer to adopt the rule-60 capture/re-check protocol (captured before the evaluator, re-checked under the publish lock → `JOB_INPUTS_CHANGED`). The payload and its schema are unchanged; no provenance field was added | decline, smoothed, and the ramp-downstream chain iff active source is LEGACY | resolver, `services/artifact_reader.py` (no first-level shape precondition: no consumer subscripts it, so a wrong-shaped document is VALID and only unparseable bytes are refused) |
| `decline.json` | + targets | smoothed (+ ramp downstream iff LEGACY) | resolver, `services/artifact_reader.py` |
| `decline_smoothed.json` | + decline | ramp downstream iff LEGACY | resolver, `services/artifact_reader.py` |
| `layout_v2.json` | scenario + arrays | selection AND level accesses (+ ramp downstream iff LAYOUT_V2) | resolver, `services/artifact_reader.py` (shape: `candidates` is a list of OBJECTS — the subscript `world_service._layout_summary` performs, Stage D B2; a list of non-objects used to make `GET …/scene` a bare 500); the scene strips centerlines |
| `layout_v2_selected.json` | scenario + arrays + catalogue — the ONE list feeding the persisted `revision` = sha256([entries, layoutRevision, candidateId])[:16] written as `sourceRevision` into BOTH files (`layout/materialize.py`); captured before the search object and re-checked under the lock (pre-AC-01E an inline list, not a helper) | ramp downstream iff LAYOUT_V2; rewrites `level_accesses.json` in the same lock; the idempotent re-select (same `candidateId` + `layoutRevision`) writes and deletes NOTHING — provided BOTH halves of the rule-157 pair read VALID (Stage D S5: with `level_accesses.json` deleted or corrupt the no-op used to answer 200 and repair nothing, so the documented "repair is an explicit user write" was a measured no-op; the explicit re-select now falls through and rewrites both) | resolver, `services/artifact_reader.py` (shape = `CandidateCertification.from_selection` + `segments`; `layoutRevision` ↔ `layout_v2.json` → `LAYOUT_V2_SELECTION_STALE`; a clearance-block defect → `LAYOUT_V2_CLEARANCE_MISMATCH`; then the SYMMETRIC rule-157 pair agreement with `level_accesses.json` — checkpoint C5/C6 — so the pair is one read unit in BOTH directions and the C1 asymmetry is gone). A VALUE defect the world alone can prove is still the builders' `_selected_candidate_policy` check |
| `level_accesses.json` | written with the selection under the selection's capture (no capture of its own; the registry gives it the selection's list for its EDGES only) | — (deleted with the selection by catalogue regeneration, and by `clear_derived`; a SOURCE switch deliberately keeps it, rule 162) | resolver, `services/artifact_reader.py` (shape = `CandidateCertification.from_level_accesses` + `accesses`; `layoutRevision` ↔ catalogue and the rule-157 pair agreement with the VALID selection: `candidateId` / certification — `provenance_key`, `error_bound` AND `required_clearance`, all four keys `CandidateCertification` parses (C6) — → `LAYOUT_V2_CLEARANCE_MISMATCH`, `sourceRevision` / `layoutRevision` / orphaned half → `LAYOUT_V2_SELECTION_STALE`; a defect of the OTHER half's own certification block is STALE here with its own message, never the other artifact's text) |
| `ramp_source.json` | explicit user choice (a root: no fingerprint, outside the world closure, removed only by `clear_derived`) | on an actual change: the whole ramp-downstream chain, unconditionally; the same source is a no-op | resolver, `services/artifact_reader.py`: ABSENT → `LEGACY` (the ONE documented absent default, rule 150); present-but-unusable → `ARTIFACT_MALFORMED`, never a silent LEGACY. The post-write cascade is the ONE caller that may not raise: it deletes the union of both closures |
| `tunnel_mesh.{json,glb}` | smoothing set (scenario + arrays + targets + decline) + ramp set — 8 paths | nothing (own stale GLB only) | resolver, `services/artifact_reader.py` (two-file unit: a SUCCESS report requires its GLB; the bytes are hashed against `artifactRevision` on the `.glb` route) |
| `levels.json` | scenario + arrays + ramp set | shafts, network (+capability), stopes, timeline, communication, sensors, development mesh — **not** the tunnel mesh (rule 74) | resolver, `services/artifact_reader.py` (`LevelsPayload`) |
| `development_mesh.{json,glb}` | levels set + levels.json (the SAME 7-path list as shafts) | nothing (own stale GLB only) | resolver, `services/artifact_reader.py` (two-file unit as the tunnel, plus `sources.rampSource` ↔ the active source → `ARTIFACT_STALE`) |
| `shafts.json` | levels set + levels.json (the SAME 7-path list as the development mesh) | network (+capability), timeline, communication, sensors — not stopes, not the development mesh | resolver, `services/artifact_reader.py` (`ShaftsPayload` + `levelsRevision` ↔ `levels.json` → `SHAFTS_STALE`). **AC-01F closed the split**: the GET, the scene, `shafts()` and `shafts_if_present()` are the SAME read, so the route no longer serves 200 what the builders refuse (Stage A I-1, the canary) |
| `network.json` | scenario + ramp set + levels + shafts | timeline, communication, sensors, capability graph | resolver, `services/artifact_reader.py` (`NetworkPayload`) |
| `capability_graph.json` | scenario + network + shafts | nothing | resolver, `services/artifact_reader.py` (`CapabilityGraphPayload` + `networkRevision` ↔ `network.json`, and AC-01F also cross-checks the recorded `networkSourceRevision` against the network payload's own — deferring when the network itself cannot be parsed) |
| `stopes.json` | scenario + arrays + levels (no ramp) | timeline | resolver, `services/artifact_reader.py` (`StopesPayload`) |
| `timeline.json` | scenario + network + stopes + ramp set + levels + shafts | nothing | resolver, `services/artifact_reader.py` (`TimelinePayload`) |
| `communication.json` / `sensors.json` | scenario + network + ramp set + levels + shafts — sensors declares the same list as communication (asserted by the registry test) | nothing | resolver, `services/artifact_reader.py` (`CommunicationPayload` / `SensorPayload`) |
| `derived/world.json` | UNREGISTERED — since the AC-01F.2 correction the world COMMIT RECORD `WorldService._save` publishes LAST (`{publication: {scenarioId, scenarioRevision, arraysRevision}, stats}`; before it, an unread statistics snapshot). Still no fingerprint lists it and no cascade deletes it: it is publication provenance, not dependency authority (A12) | — | only `clear_derived` removes it |

Two structural facts this table makes explicit, both inputs to later AC steps:

* `WorldService.scene` **since AC-01F commit 2** takes ONE
  `ArtifactReader.snapshot` of every registered derived file under the
  per-scenario store lock — the same lock every writer holds across its write
  AND its cascade — and then classifies each artifact OUTSIDE the lock. The
  seventeen unsynchronised raw `json.loads` with no schema validation and no
  revision check are gone: `null` now means ABSENT and nothing else, and any
  STALE / MALFORMED artifact refuses the WHOLE scene with 409
  `SCENE_ARTIFACT_INVALID`, every failure listed in `detail.artifacts[]` with
  its own specific code. The scene also applies the same DISK-authoritative
  world guard as `require` (`arrays.npz` absent → 409 `WORLD_NOT_GENERATED`,
  even with a warm world cache). **AC-01F commit 3** binds that snapshot to
  the scenario and world it describes: `WorldService.load_bound` returns the
  two revisions the document and the arrays were taken at, the snapshot is
  acquired with `expect_scenario_revision` / `expect_arrays_revision`, and a
  mismatch re-runs the load — at most `SNAPSHOT_ATTEMPTS` (3) times, after
  which the read answers 409 `READ_SNAPSHOT_CHANGED` (never
  `JOB_INPUTS_CHANGED`, which is a GENERATION whose inputs moved). No
  `generate_world`, `np.load` or `build_orebody` ever runs inside the lock.
* `InfrastructureService` no longer reaches into a `DesignService` private:
  its two fingerprints call the module-level `artifact_fingerprint` (AC-01E;
  the pre-AC-01E `design._ramp_input_paths` access was the only cross-service
  private access, AC-F04). `core/artifacts.py` owns every derived filename
  constant and `RAMP_OWNING_ARTIFACTS`; the graph itself is
  `core/artifact_registry.py`.
* `frontend/src/scene/invalidation.ts` mirrors these cascades in 16 exported
  `after*` helpers (13 `*Regen` cascades plus the three rule-169 identity
  helpers) — a second, hand-maintained copy of the same graph (AC-01I; the
  comment in `frontend/src/components/panels/developmentMeshScope.ts` still
  names the removed `DesignService._delete_levels_artifact`, corrected there).

**Correction, AC-01E.** The AC-01B version of this section was checked line
by line against the code before the registry was written; six statements did
not hold and are corrected above: (1) `targets.json` had NO fingerprint — the
row claimed "scenario + arrays (TABULAR only)", but `generate_targets` never
captured one and the registry adds none (a capture would add a 409 path to
`POST …/design/targets`). **AC-01F added exactly that capture** (A3, the last
unfingerprinted derived writer): the registry declaration is unchanged, the
payload and its schema are unchanged, and the new 409 path is
`JOB_INPUTS_CHANGED` on a race only — the row above is the AC-01F state; (2) `derived/world.json` and `ramp_source.json`
lie outside every cascade — only the `clear_derived` directory walk removes
them (the registry test pins `closure(arrays.npz) ∪ {ramp_source.json}` ==
every registered derived artifact as a consistency fact, not as the
mechanism); (3) the line references `:245-254`, `:478-488` and `:643-663`
had drifted (at the AC-01E base: `InputFingerprint` `:251-272`, the ramp set
`:497-507`, the selection provenance check `:710-743`) — the census tables
in `tests/test_artifact_registry.py` carry the base-tree provenance of every
row, so this map no longer cites design_service.py lines for them;
(4) shafts and the development mesh shared ONE 7-path input list; (5) the
selection fingerprint was an inline list captured twice (before the search
object and again under the lock), not a `_*_input_paths` helper — it is the
14th ordered list, and its double capture is what the stale-input check
compares; (6) "ten per-artifact, three cascades" undercounted:
`_delete_levels_artifact` (levels + development mesh + shafts, used ONLY by
the ramp cascade) and `_delete_network_artifact` (network + capability graph)
were cascades too, so the ramp-downstream set was 12 files (tunnel_mesh
json+glb, levels, development_mesh json+glb, shafts, stopes, timeline,
communication, sensors, network, capability_graph). The registry closure
reproduces every one of the 36 (artifact × source) delete cells and all 14
ordered lists of the base tree; the old-vs-registry proof ran live in AC-01E
commit 1 (`tests/test_artifact_registry_transition.py`, removed with the
helpers in commit 2).

## 7. Search stage authority and the restart path

| stage | role | note |
|---|---|---|
| 1 | finite family enumeration + geometry construction | family order and candidate ids are a behaviour contract |
| 2 | cheap hard checks on the delivered geometry + the geometric access screen | the screen runs anchor/connector search for every cheap-feasible candidate — "cheap" names the gate set, not the cost |
| 3 | `(blockedLevels, proxy, family order, id)` + per-family slot, bounded shortlist | the screen never rejects; it re-orders (rule 176) |
| 4 | candidate clearance refinement, full validation, level-access planning, scoring | the feasibility authority |
| 5 | deterministic ranking of feasible candidates | ranking / tie contract |

**Correction, AC-01G.** Each stage now has a module and an explicit signature.
Stages 1–5 are module functions of a frozen `StageContext` (`layout/stages.py`)
with no `self` to reach through; the section geometry they need comes from a
`SectionProvider` (`layout/provider.py`) built once per run, and
`LayoutV2Search` keeps exactly ONE private data attribute, `_ctx`, the post-run
compatibility slot `context` / `candidate_policy` read. Stage 2 and stage 4
RETURN frozen outcomes (`CheapEvaluation`, `DetailedEvaluation`); `apply_cheap`
and `apply_detailed` are the only functions that write the persisted
`CandidateResult` (plus `run()`'s own run-level fields), each refusing an
out-of-order transition with a `ValueError`, never an `assert`. The rule-176
authority split is carried by the lens types: `screen_lens(sc)` takes no
candidate and can only produce the world policy at the coarse stand-off under
the `"WORLD"` trace token, while `detailed_lens(sc, clearance)` requires a
`CandidateClearance` whose token the certification recipe derived from its own
`world_policy` argument.

Consuming a SAVED design re-runs the whole search. Verified call path:
`generate_levels` / `generate_shafts` / mesh generation →
`_selected_candidate_policy` (`design_service.py:630`) → `_layout_object`
(`:556`) → `LayoutV2Search(scenario, world).run()` on a cache miss, where the
cache key is world OBJECT IDENTITY (`cached[0] is world`, `:564`). A fresh
process therefore re-evaluates every candidate to rebuild the policy of the
one that was already selected (AC-F02, owner AC-01D; AC-01C prepares the
boundary).

**Correction, AC-01D.** The call path above is gone. Downstream of a
selection, `_selected_candidate_policy` now restores the selected
candidate's certification from its RECIPE —
`layout.certification.restore_candidate_policy`: the shared search setup
(`layout.setup.build_search_setup`, the verbatim pre-stage-1 block
`LayoutV2Search.run()` itself executes), the world search policy /
evaluator (`world_search_policy`, shared with `LayoutV2Search.__init__`)
and the selected candidate's persisted `centerline.points` from
`layout_v2.json` (`candidate_points_from_catalogue`, normalised to a
C-contiguous float64 `(N, 3)` array) go through the SAME
`build_candidate_policy` recipe stage 4 used, with the serviceable required
levels — and the result is CHECKED against the recorded certification
(`CandidateCertification.verify`: basis, refinement provenance key, error
bound with `None → 0.0`, isclose 1e-9). A recorded number is never turned
into a policy; any mismatch is `ClearancePolicyReconstructionError` (409
`LAYOUT_V2_CLEARANCE_MISMATCH`) — never a re-run, never a fallback to the
whole-body policy, never a file write. The restore is cached per (world
object, catalogue revision, selection revision) so one builder chain pays it
once. The selection document, the catalogue text and both file revisions
are read as ONE snapshot under the per-scenario store lock (the lock every
writer of those files holds), and the entry is keyed by the SNAPSHOT's
revisions — a re-selection that lands while a rebuild runs carries a new
selection revision and misses (PR #31 review: reading content and revision
separately let one candidate's policy be cached under another's revision).
The entry keeps a strong reference to its world object until the next
restore for that scenario replaces it (the pattern `_layouts` already had);
a stale entry can never be served because the key requires the CURRENT world
object and the current revisions. Present-but-malformed selection documents (a null or list
`clearance` block, a non-numeric bound, a refinement the provenance key
cannot digest) are the same typed 409, never a bare exception. `generate_levels`, `generate_shafts`, `generate_tunnel`,
`generate_development_mesh` and everything below them make ZERO
`LayoutV2Search.run` calls, cold or warm; the idempotent re-select /
re-activate of the already selected candidate at the same `layoutRevision`
also never runs it. The two sync API branches (`POST …/design/tunnel?sync`,
`POST …/design/development-mesh?sync`) now route `LayoutSelectionStaleError`
/ `ClearancePolicyReconstructionError` through `_guard` (409 with the
existing codes) instead of leaking a 500.

The ONE remaining re-run is `select_layout_candidate` →
`_layout_object` → `LayoutV2Search(scenario, world).run()` for a DIFFERENT
candidate than the persisted selection (or a first selection) in a process
that did not generate the catalogue — explicitly DEFERRED, not hidden:
materialization needs the full typed `CandidateResult` (`access_plan`
objects, `anchors`, `level_service`, `diagnostics`), which the catalogue
does not persist losslessly (no `from_dict` reconstructors exist and
`anchors` are not in `layout_v2.json`); serving it cold means either a
catalogue payload change (golden bytes) or exact-fidelity deserializers — a
schema / provenance design of its own. Follow-up candidate:
catalogue-restorable `CandidateResult` (owner to be assigned, likely
alongside AC-01G's candidate-state work).

## 8. CLAUDE.md rule scope index

**No rule is added, deleted, reworded or renumbered by this index.** Every
rule keeps its text and its number; what follows says which rule carries the
CURRENT authority for a subject, so a reader does not have to hold 186 rules
at once. Where a rule is marked superseded, its text still describes a live
code path — usually the legacy one — and stays as the record of that path.
Classification was checked rule by rule against the tree at the baseline.

**Superseded — the authority moved, the text stays**

| rule | subject | current authority | evidence |
|---|---|---|---|
| 39 | block-model ore semantics, `ore_fraction` | **127** — no block/SMU semantics; the world is terrain + solid + field lattice | `tests/test_no_block_semantics.py:19-41` bans the identifiers in production code; `BlockModel` survives only in the v1→v2 migration and legacy-artifact detection |
| 42 (rock-quality clause) | "rock quality interpolated from the block model" | **128** — `world.fields.rock_quality.sample` | `design/cost_field.py:248,:257`. Rule 42's separation of geological measurement from cost interpretation is unchanged and live |
| 64 | "Phase 06 consumes the Phase 05 artifact" | **149 / 150** — the source-neutral Effective Ramp | `services/design_service.py:1226`, `services/effective_ramp.py` |
| 71 | level drift anchored at the Phase 05 LEVEL_ENTRY, along the orebody strike | **154** (entry owned by a validated level access) + **179 / 180** (curved section-trace backbone) | `levels/builder.py:113`, `:361-362` |
| 72 | crosscut layout from the orebody strike extent | **159** (generic backbone; longhole stations only for LONGHOLE) + **180** | `levels/builder.py:350-356`, `:189`, `:254` |
| 73 | Phase 08 MineNetwork topology | **160** (ramp junction / level access edges) + **184** (shaft nodes and edges) | `network/builder.py:284-285`, `:375-376` |
| 74 | Phase 08 dependency contract | **79 / 151 / 162 / 184** | `services/design_service.py:502-512`, `:1128-1133` |
| 140 (level-layout clause) | WARPED is world / visualization only | partially **180** — curved level development exists; the Phase 09 stope boundary is still typed and live | `levels/builder.py`, `mining/methods/longhole.py:142-144` |
| 43 (scope, not authority) | footwall access line | still LIVE — the layout-v2 TABULAR anchor uses the exact rule 43 line (`layout/access.py:359`, `TABULAR_RULE_43`); for every other orebody **178 / 179** carry it | `layout/access.py:326`, `:359` |
| 158 (non-TABULAR half) | anchor from the level section's principal axis | **178 / 179** — footwall trace + offset backbone; the PCA backbone is gone | `layout/sections.py:583`, `:770` |

**Legacy-algorithm scope — true for the Hybrid-A\* chain and the TABULAR
frame, not for the whole platform**

Rules **21–25, 47–59, 61–63** describe the Phase 03–05 chain. That chain
is now ONE of two ramp sources and is gated behind an EXACT-distance +
TABULAR guard (`services/design_service.py:272-275`, `:292-293`;
`api/design.py:78-84` answers 422 `UNSUPPORTED_OREBODY_FOR_LEGACY_LAYOUT`),
so they do not constrain the parametric path. Their layout-v2 analogues are
rules 141–152 (enumeration, delivered-centerline judgement, clearance policy,
scores) and 153–176 (junctions, level access, screen authority). Rules
**75–77** and **130** are TABULAR / LONGHOLE scope through
`mining/methods/longhole.py:142-144`; rule **123** is narrowed by **135**
and **146**.

**Rules that embed a past measurement**

**55, 56, 59, 146, 165, 168, 170, 176, 177, 178** quote numbers from a
specific experiment (ε = 2 solving in 3,152 expansions; the < 40 % single-arc
docking measurement; the 1.5 × lattice-diagonal derivation; the AUC values;
the 56 false blocks; the −4.9 m pre-audit envelope separation; the 2.97 M /
11.9 M section-cell measurements). Those numbers are EVIDENCE for a decision,
not thresholds to re-derive: they are pinned by `backend/golden/*.json` and
the reports under `docs/verification/`. A future change to such a rule cites
a new measurement; it never silently edits the old number.

**Operational rules** (process, not code): **2** (phase order), **38**
(completion reports quote executed commands), **126** (remote-write
approval), **132** (golden regression before and after a migration), **181**
(verification tiers never weaken FULL — see §3 for the AC-01A correction).

Every rule not named above is a live invariant with code evidence at the
baseline; the per-rule evidence table produced for this index is reproducible
by re-running the same cross-check against a newer main.

## 9. Consolidation sequence

Each step is one PR. The prohibitions in §4 apply to all of them.

| step | scope | additional prohibition | verification / done when |
|---|---|---|---|
| **AC-01A** ✅ | FULL component vs release authority, start/end source identity, PR-merge-SHA record | production, golden, the gate SET itself | dirty / missing frontend / failed gate / changed source → authority false; only a complete clean run true; a real FULL |
| **AC-01B** ✅ | this document: baseline SHA, verified module + lifecycle map, rule scope index, prohibitions | deleting or rewording a CLAUDE rule; claiming a run that did not happen | every claim carries file:line; links resolve |
| **AC-01C** | extract the search materialization / certification DTOs and the public access boundary | search order, parameters, serialization, gates, geometry | existing selection / clearance restart tests, TABULAR + WARPED canaries, payload equivalence, FULL |
| **AC-01D** | restore the selected certification from its recipe; remove the full-search re-run | trusting a recorded number as a policy; auto-repairing stale state | cold and warm results and failures equal; zero `search.run` calls downstream; recipe mismatch fails closed; FULL + affected goldens |
| **AC-01E** ✅ | artifact dependency registry expressing today's fingerprint / delete sets; services stay facades | widening or narrowing a delete set; changing stat-revision semantics | source switch, candidate switch, regeneration, shaft / capability sibling preservation; FULL |
| **AC-01F** ✅ | one validated read resolver for the scene and the per-artifact APIs, in three commits: (1) the resolver + the old-vs-new characterization proof, additive; (2) every consumer switched to it + one `api/errors.guard` table + GLB validation + the `generate_targets` fingerprint; (3) the world / scenario revision binding (`load_bound`, the stat-bound world cache, the scenario-PUT mutation boundary, the world-generate publish guard, the bounded snapshot retry) | auto-regenerating stale data; changing upstream geometry | stale partial snapshot / restart / concurrent invalidation cases; API error changes approved explicitly; FULL |
| **AC-01G** | section provider vs search stage boundary; less candidate-state coupling | reimplementing the screen; redesigning shortlist or ranking | candidate ids / order / status / winner, EXACT vs CONSERVATIVE authority, stage-4 trace weld; FULL + affected goldens |
| **AC-01H** | after proving old/new equivalence, collapse the duplicated CI FULL run | weakening coverage or trigger authority | old and new gate sets compared on one revision; one release verdict |
| **AC-01I** | geometry resolver / API schemas / frontend invalidation mirror, where needed | payload enum, null or coordinate meaning | malformed ref / endpoint / shaft tests, API contract, frontend gates, FULL; browser acceptance if the UI changes |

AC-01D is not merged into AC-01C: it carries schema and provenance design.
AC-01F's stale-read unification changes observable behaviour and is separated
from AC-01E's mechanical extraction. AC-01H may run early once AC-01A's
evidence is in place.

## 10. Open findings register

Numbering follows the Architecture Reality Report (2026-09-10, audit baseline
`9d1a8bb`). Status is against THIS baseline.

| id | finding | status |
|---|---|---|
| F01 | FULL authority flag did not prove release authority | **resolved by AC-01A** (§3) |
| F02 | consuming a saved design re-runs the whole search | **resolved by AC-01D (downstream)**: zero `LayoutV2Search.run` calls below a selection, cold or warm; the cold re-run of `select_layout_candidate` for a DIFFERENT candidate is deferred and recorded in §7 |
| F03 | search context and candidate state mutate across stages | **resolved by AC-01G**: `_sections` / `_track` / `_reference` are deleted (`_ctx` alone survives, pinned by an AST guard AND a runtime guard over the COMPLETE attribute set); the 21 census reach-in sites are gone — every stage is a module function of a frozen `StageContext` and takes the delivered centerline as an argument; the section geometry has ONE construction owner per run (`layout/provider.py`, allowlisted); and `CandidateResult` has exactly two writers plus `run()`'s run-level fields, with every stage-transition precondition an explicit `ValueError` (zero `assert` statements remain in `search.py` / `stages.py` / `provider.py`, proved under `python -O`). Behaviour proof, in TWO layers (the review of PR #35 showed one commit's identical tree ``75b67c6`` green on the FULL runner and red on the ordinary CI runner in hundreds of last bits of `footprintDistance` / `referencePosition` / `cheapProxy`, so an IEEE bit pattern is not a property of the source tree across runners): LAYER A, a committed DISCRETE characterization (C1–C6 over four cases with every float leaf and numeric list REMOVED — never rounded — and two declared-literal subtrees kept verbatim; baselines generated from a clean `git archive` of the freeze SHA and reproducible by a documented command; compared exactly on any runner), and LAYER B, a same-runner base-vs-HEAD numeric equivalence (`scripts/characterization_observe.py` run twice from one interpreter on one machine, once on the freeze-SHA archive and once on HEAD, the full float-bearing observations compared exactly with provenance — CPU, NumPy build, enabled SIMD dispatch — asserted equal; the CI checkouts use `fetch-depth: 0` so the base commit is always present and the test fails, never skips, without it), plus the offset-trace build-KEY multiset unchanged (154 keys, 0 added, 0 removed). **Residuals**: the layout-v2 golden comparison records a per-candidate array it never reads, so for the five cases outside the freeze its per-candidate resolution is status + failure reasons + screened/accessible counts + shortlist/ranking ORDER only; the freeze itself is FULL-tier (`slow`), so between FULL runs the inner loop is unguarded; the `LevelSections` failure path re-raises one cached exception object with a growing traceback and a shared `diagnostics` dict (pre-existing, module out of AC-01G scope); `candidate_policy` still pairs a caller-supplied `result` with `self._ctx` without a binding check (pre-existing, unreachable through `DesignService`, which caches `(world, search, result)` as one tuple); and LAYER A compares no float, so a behaviour change confined to a numeric value that flips no decision is caught only by LAYER B on the runner that executes it — never by the committed record alone. (The earlier residual that the `ServiceReference` build had moved inside `performance.setupSeconds` was closed by the review correction: the build runs after the early-return guards again, so `setupSeconds` / `constructAndCheapSeconds` keep their pre-AC-01G meaning.) |
| F04 | artifact lifecycle is several hand-maintained lists | **resolved by AC-01E**: one declarative registry (`core/artifact_registry.py`) derives every ordered fingerprint list and every source-conditional delete cascade; the 13 `_delete_*` helpers, 12 `_*_input_paths` lists, the inline selection capture and the `InfrastructureService` reach-in are gone; census + e2e proofs in §6. The frontend mirror (`scene/invalidation.ts`) stays AC-01I |
| F05 | the same artifact is stale-checked differently per read path | **resolved by AC-01F (commit 2)**: ONE validated read authority (`services/artifact_reader.py`) over a per-artifact spec table; every direct GET, every builder's upstream read, both GLB routes, the async job path and the scene classify an artifact identically (ABSENT / VALID / STALE / MALFORMED) and answer the same typed code — with ONE declared exception, the GLB CONTENT HASH, which is deliberately route-local (`docs/api.md`, "Two-file (GLB) units: what is checked where"): the PRESENCE of the `.glb` is checked on every surface, but its bytes are hashed against the report's `artifactRevision` only on the two binary routes, so a TRUNCATED `tunnel_mesh.glb` is 409 `ARTIFACT_MALFORMED` on `GET …/mesh.glb` and 200 on the report GET and in the scene. That is the declared cost trade-off (R1), not a second classification path. `tests/test_no_raw_artifact_reads.py` is the static proof that no module outside the authority reads — or presence-probes — a derived artifact; `tests/test_artifact_read_api.py` pins the contract through the real API. The frontend mirror stays AC-01I |
| F06-A | reads are not taken against a coherent, revision-bound snapshot | **F06-A resolved in-process (AC-01F commit 3)**: every response is a serializable snapshot — there is one instant at which every scenario, world and derived statement in it was simultaneously true on disk (the lock hold; for a world-cache hit, the instant at which that entry was published under the lock). Commit 2 closed the derived half (one lock-held observation per scene / per `require`, one observation per file, the disk-authoritative world guard); commit 3 closed the scenario / world half (the bound document read `_bound_scenario`, `load_bound`, the revision-bound world cache, the typed cold-load window — a vanished `arrays.npz` is `WORLD_NOT_GENERATED` and a replaced one `READ_SNAPSHOT_CHANGED`, never an escaping `FileNotFoundError` — the one-locked-section scenario PUT, the world-generate optimistic publish guard, the bounded retry → `READ_SNAPSHOT_CHANGED`). Reproductions R1, R2, R3b, R3d, R4 and the non-injected migration-on-read case are now impossible; **residuals: cross-process** (`ScenarioStore.lock` is a `threading.RLock`; no OS lock exists or is added) **and crash residue** (a torn or half-published derived artifact is a TYPED refusal rather than a silent projection; a torn **`arrays.npz` OR `scenario.json`** stays an unmapped 500 as at HEAD — `ScenarioStore.get` parses the document with an unlocked `json.loads(path.read_text())` and `_write` is a non-atomic truncate+write, so a reader landing INSIDE the document write sees neither side: measured at commit 3 with `scenario.json` = `{`, `GET …/scene`, `GET …/world`, `GET …/design/decline`, `GET …/design/levels` and `GET /api/v1/scenarios/{id}` all 500 with no `detail.code`, at the same rate as base `12d7725`. The revision re-check cannot fire because the read itself throws, which is also the exact qualification the "one mutation boundary" claim needs: it holds for reads that SUCCEED. That was the F06-B residual, and **AC-01F.2 closed it for this process**: `_write` and `_save` publish atomically, so a torn `scenario.json` / `arrays.npz` can no longer be produced here (one left by an EXTERNAL writer is still an unmapped 500, and the measurement above stands as the BEFORE). A SEPARATE case, not fixed by publication atomicity: an `arrays.npz` that is present but unloadable satisfies the stat-based world guard, so `/world`, `/world/slice` and `/scene` answer 500 while **every derived GET answers 200** — the guard proves a file exists, never that it parses) |
| F06-B | publication is not atomic (a writer's `write_text` is not temp + fsync + replace) | **per-FILE publication atomicity: resolved by AC-01F.2. GENERATION COHERENCE across files: resolved by the AC-01F.2 CORRECTION** (the first PR claimed F06-B closed; per-file atomicity leaves a reader unable to tell a NEW `scenario.json` beside an OLD `arrays.npz` from a coherent pair, so the finding was only half closed — see the correction paragraph at the end of this cell). AC-01F.2: all 22 write sites publish through ONE leaf helper (`core/publication.py` — temp sibling `.<name>.<8 hex>.tmp` → `flush` + `os.fsync` → `os.replace` → best-effort directory fsync; any failure before the replace removes the temp and leaves the previous file, or its absence, untouched). `tests/test_publication.py` is the static proof that no raw `write_text` / `write_bytes` / `np.savez*` / write-mode `open` remains outside it; `tests/test_publication_fault_injection.py` drives every one of the 22 sites through the real LEGACY and LAYOUT_V2 stacks under three injected faults (replace, fsync, truncated temp write) and asserts the previous bytes, the absent temp, the OSError-class propagation and the un-run cascade; `tests/test_publication_cross_process.py` measures a subprocess reader against the real publish loop. MEASURED (scratch `xproc_race.py`, 12 s per artifact, one reader process): at 450f9df `derived/stopes.json` 7,679 torn reads of 164,384 (4.67 %) over 1,843 publishes and `arrays.npz` 357,563 of 357,563 (100 %, `zipfile.BadZipFile`) over 487 publishes; after the change 0 and 0. Byte identity: the frozen Stage A oracle reports 0 differing units, and a sha256 comparison of every persisted file of a fresh LEGACY + LAYOUT_V2 build at 450f9df vs after is identical for `arrays.npz`, every GLB, `targets.json`, `decline_smoothed.json` and `ramp_source.json`, and equal under the 15 measured volatile leaves (plus the random scenario `id`) for every other JSON. (`world.json` was byte-identical at AC-01F.2 and is NOT after the correction, which changes its content; the two mesh reports and every other served payload stay byte-identical — see below.) The stat semantics of `file_revision` / `InputFingerprint._stat` are UNCHANGED (rule 60): `os.replace` installs the temp inode, so every publication is a new `(size, mtime_ns)` — no content hash was introduced. **Residuals**: (1) a PAIR is two atomic publications ORDERED as D3 (on SUCCESS the GLB before its report, `level_accesses.json` before `layout_v2_selected.json`, `arrays.npz` before `derived/world.json`), not one atomic pair — a crash between the two leaves the half the read authority classifies most conservatively (ABSENT artifact / typed forward orphan), which `tests/test_publication_pair_order.py` measures against the opposite order; (2) cross-process readers still take NO lock — they now see whole FILES, not a coherent sequence of them, and F06-A's cross-process residual is untouched; (3) the directory fsync is best effort (ignored `OSError`), so the RENAME's durability across a power loss is not guaranteed on filesystems that refuse it; (4) a crash before the replace can leave a `.<name>.<hex>.tmp` sibling — invisible to every reader and to the cascade, and removed by `clear_derived` only UNDER `derived/` (it walks that directory and unlinks `arrays.npz` by its exact path), so a temp beside `scenario.json` / `arrays.npz` in the scenario root survives every invalidation and is removed only by `ScenarioStore.delete`; no startup sweep is added; (5) a torn `scenario.json` or `arrays.npz` written by an EXTERNAL process is still an unmapped 500, while a torn REGISTERED artifact under `derived/` from an external writer is the typed 409 `ARTIFACT_MALFORMED` AC-01F already answers; (6) the publication installs a NEW INODE, so mode, ownership and symlink identity of an existing target are not preserved (the temp is created `0o666` masked by the process umask and owned by the publishing uid, and a symlinked target is replaced by a regular file) — nothing in MineGen sets a special mode, owner or link on a persisted file; (7) two narrow windows survive by design: a non-`OSError` raised inside the best-effort directory fsync escapes AFTER the replace (the artifact IS published and the caller nonetheless aborts), and an interrupt inside the temp `unlink` of the exception path leaves the residue of (4). The D3 pair order has ONE deliberate exception: on the FAILED mesh path (`result.glb is None`) the FAILED report is published FIRST and the stale GLB unlinked after it, because unlinking first would open a window in which a failing report publish leaves the previous SUCCESS report beside no GLB — the `ARTIFACT_MALFORMED` half D3 exists to avoid (`tests/test_publication_pair_order.py` measures both halves)  **AC-01F.2 CORRECTION (generation coherence).** `derived/world.json` becomes the world COMMIT RECORD (`{publication: {scenarioId, scenarioRevision, arraysRevision}, stats}`), published LAST so its publication is the commit point of a generation; a world whose record does not name the two live files is refused 409 `WORLD_PUBLICATION_STALE` at five enforcement points sharing ONE definition (`ArtifactReader.require_world`): `_read_bound`, `WorldService.load_bound` (after the arrays load, so `WORLD_ARTIFACT_INCOMPATIBLE` keeps precedence), `DesignService._ramp_snapshot`, `set_ramp_source` and the layout select idempotency probe — the last three never passed through `_read_bound` and were the surfaces that still answered 200 on a mixed generation. `publish_bytes` / `publish_text` / `publish_npz` now RETURN the rule-60 identity of the file they installed, taken from the temp file's own `os.fstat` before the rename: a post-hoc stat of the path can name a file ANOTHER process installed, which made a two-process interleaving record a foreign generation and pass the check. Each mesh pair commits itself the same way, in an INTERNAL sidecar `derived/<mesh>.commit.json` (`{reportRevision, glbRevision}`, published LAST, unregistered like `world.json`), so every surface detects a GLB/report generation mixture without hashing bytes and WITHOUT changing the served report or scene payload. The first draft of this correction put a `glbRevision` field in the PUBLIC report instead, which leaked publication provenance into the public projection and forced both the AC-01D warm/cold comparison and the frozen oracle to be widened; the review rejected that and this sidecar is the corrective. The content hash cannot see the mixture at all: a mesh rebuild is deterministic, so the crash installs identical bytes and `artifactRevision` agrees. **Correction residuals**: (a) the publish-then-cascade window of the REGISTRY couplings is NOT closed — a death between `publish_text(levels.json)` and `_invalidate_downstream` leaves NEW levels beside OLD stopes/network/timeline, and A12 forbids the generic `sourceRevision`-vs-recomputed-fingerprint rule that would close it. MEASURED on this working tree (Stage D D4-5): the two mesh reports are the only derived artifacts carrying NO upstream identity at all — `tunnel_mesh.json` records `artifactRevision` / `meshUrl` and nothing about the centerline it was swept from, and `development_mesh.json` records a source NAME, never a revision — so after a publish-then-cascade death on the Phase 05 artifact, `GET …/design/tunnel`, the GLB route and `GET …/scene` all answer 200 and one scene ships a NEW effective centerline beside a mesh swept from the previous one. This correction certifies the report ⇄ GLB coupling only, which is the weaker of the two; the centerline ⇄ mesh coupling has no persisted evidence and is out of B1/B2/B3 scope; (b) a cross-process reader can catch a live writer between `arrays.npz` and the record and get the 409 although a retry would succeed; (c) concurrent generators can lose an update (regeneration required) — never a wrong answer; (d) any content-preserving mtime change to `scenario.json` or `arrays.npz` now invalidates the world until it is regenerated (rule 60's existing stat semantics, made visible on the world); (e) a world or mesh published before the correction carries no commit record / no sidecar and is refused until regenerated; a sidecar left beside a cascade-deleted report is inert (the artifact is then ABSENT, so the read never reaches its checks) and is removed by `clear_derived`; (f) a rule-60 revision collision is now the SOLE false-pass channel for world generation coherence, and the world is a NEW dependent of an identity that governed derived fingerprints only — a harmful collision needs DIFFERENT arrays content at identical compressed size AND an mtime tick collision (measured on this host: 20,000 rewrites → 20,000 distinct mtimes, smallest delta 56,612 ns; 40 same-size 10,245,989-byte publications → 40 distinct revisions; 2,000 same-size 100-byte publications → 0 collisions), and the directive forbids replacing rule 60 with a content hash, so it is recorded, not closed; (g) two provenance recorders still stat a PATH after reading the bytes they describe (`shafts.levelsRevision` at `design_service.py:1147`, `capabilityGraph.networkRevision` at `:1204`). They are safe only INCIDENTALLY: both artifacts' fingerprints name the file they stat and both builders re-check the fingerprint under the lock before publishing, so any movement in that window raises `StaleInputsError` and nothing is persisted. `core/publication.py` now states the opposite discipline as a package rule; these two exceptions are recorded rather than rewritten, out of B1/B2/B3 scope. |
| F07 | level development rebuilds search-side section / track state | open — NOT addressed by AC-01G. The provider is a per-RUN authority, not a per-PROCESS one: `levels/builder.py` still builds its own `LevelSections` + footwall track for `levels.json`, and `certification.restore_candidate_policy` its own through `build_search_setup` (by design — AC-01D's search-object-free restore). Measured unchanged by AC-01G |
| F08 | `ci.yml` and `verify-full.yml` both run the whole gate set | **in progress — AC-01H commit 1 (additive)**: `verify-full.yml` now has two component jobs (`--backend-only`, `--frontend-only`, one runner implementation) and a `Release Authority` job that aggregates their published summaries into ONE fail-closed verdict (`verify.py authority`, `if: always()`, a missing component is a typed withheld verdict); every evidence upload sees the dotted `.verification/` and errors when empty (the pre-AC-01H uploads published 0 artifacts). `ci.yml` is retired only after same-revision old/new equivalence is shown on the transition commit |
| F09 | typed-API principle vs `dict[str, Any]` layout payloads | open — AC-01C / AC-01I |
| F10–F16 | resolver duplication, local import cycles, large builders, owner-string duplication, CLAUDE.md accumulation, marker/fixture coupling, search timing labels | open, P2 — handled inside the step that touches the module, never as a standalone rewrite |

## 11. Measurement plan

Compared on one machine, one scenario set and one source revision, before and
after a step. No target value is promised in advance.

* cold-process time to selected levels / shafts / mesh, and the number of full
  `LayoutV2Search.run` calls it costs.

  **Measured, AC-01D** (one machine, `backend/.venv`, main `a91c3c1` BEFORE vs
  the AC-01D tree AFTER; a fresh `DesignService` after `activate` = the cold
  process, then a fresh `WorldService` + `DesignService` for the cold
  `generate_levels`; run counts are the contract, seconds are advisory):

  | case | cold policy BEFORE | cold policy AFTER | cold levels BEFORE | cold levels AFTER |
  |---|---|---|---|---|
  | TABULAR-small (EXACT) | 4.33 s / 1 `run()` | 0.02 s / 0 `run()` | 4.38 s / 1 | 0.06 s / 0 |
  | WARPED-301 default (REFINED_CONSERVATIVE, factor 2) | 61.13 s / 1 `run()` | 5.25 s / 0 `run()` | 74.82 s / 1 | 12.49 s / 0 |

  The second builder in the same fresh process (tunnel after levels) made 0
  calls before and after. The AC-01C byte-identity witness reproduced the
  catalogue / ramp / access / certification hashes exactly after the `run()`
  setup extraction (0 differing lines), and levels.json, the tunnel and
  development-mesh reports, both GLBs and network.json were equal between a
  warm and a cold service over the same selection on both cases.
* FAST / FEATURE / FULL wall time and CI runner minutes.
* the number of lifecycle sites a new artifact must touch.
* for a behaviour-preserving extraction: payload, geometry, ranking and
  failure differences — required to be **0**.
