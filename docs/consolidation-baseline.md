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
`WorldService.invalidate` (`world_service.py:184-191`) →
`ScenarioStore.clear_derived` (`scenario_service.py:106-121`, a directory
walk that also removes `derived/world.json` and unknown files), called from
world generation (`world_service.py:76`), scenario PUT (`api/scenarios.py:81`)
and a schema migration on read (`scenario_service.py:74-77` — this caller
bypasses the `WorldService._cache` drop, an as-is quirk recorded here and not
changed).

`tests/test_artifact_registry.py` holds the census below as frozen literal
tables (with the pre-AC-01E file:line provenance of every row) and checks both
the derivation AND the live public `*_fingerprint()` methods against them;
`tests/test_artifact_registry_e2e.py` regenerates every artifact through its
real route under both sources and asserts the removed-file set equals the
closure.

| artifact | fingerprint inputs (ORDERED) | regenerating it deletes | read path |
|---|---|---|---|
| `targets.json` | NONE — `generate_targets` captures no fingerprint and has no stale-input check (the TABULAR guard is a precondition); the registry declares the dependency scenario + arrays for its edges only | decline, smoothed, and the ramp-downstream chain iff active source is LEGACY | raw `json.loads` |
| `decline.json` | + targets | smoothed (+ ramp downstream iff LEGACY) | raw |
| `decline_smoothed.json` | + decline | ramp downstream iff LEGACY | raw |
| `layout_v2.json` | scenario + arrays | selection AND level accesses (+ ramp downstream iff LAYOUT_V2) | raw; the scene strips centerlines |
| `layout_v2_selected.json` | scenario + arrays + catalogue — the ONE list feeding the persisted `revision` = sha256([entries, layoutRevision, candidateId])[:16] written as `sourceRevision` into BOTH files (`layout/materialize.py`); captured before the search object and re-checked under the lock (pre-AC-01E an inline list, not a helper) | ramp downstream iff LAYOUT_V2; rewrites `level_accesses.json` in the same lock; the idempotent re-select (same `candidateId` + `layoutRevision`) writes and deletes NOTHING | raw to serve; revision + clearance provenance checked when a builder needs the policy (`_selection_snapshot` / `_selected_candidate_policy`) |
| `level_accesses.json` | written with the selection under the selection's capture (no capture of its own; the registry gives it the selection's list for its EDGES only) | — (deleted with the selection by catalogue regeneration, and by `clear_derived`; a SOURCE switch deliberately keeps it, rule 162) | raw |
| `ramp_source.json` | explicit user choice (a root: no fingerprint, outside the world closure, removed only by `clear_derived`) | on an actual change: the whole ramp-downstream chain, unconditionally; the same source is a no-op | raw, silent LEGACY fallback if missing / malformed (`effective_ramp.py:75-84`) |
| `tunnel_mesh.{json,glb}` | smoothing set (scenario + arrays + targets + decline) + ramp set — 8 paths | nothing (own stale GLB only) | raw |
| `levels.json` | scenario + arrays + ramp set | shafts, network (+capability), stopes, timeline, communication, sensors, development mesh — **not** the tunnel mesh (rule 74) | **validated** |
| `development_mesh.{json,glb}` | levels set + levels.json (the SAME 7-path list as shafts) | nothing (own stale GLB only) | raw |
| `shafts.json` | levels set + levels.json (the SAME 7-path list as the development mesh) | network (+capability), timeline, communication, sensors — not stopes, not the development mesh | **validated + `levelsRevision` 409** in `shafts_if_present` (the builders' read); `GET …/design/shafts` uses `shafts()` and serves a stale artifact without the 409 (as-is, AC-01F) |
| `network.json` | scenario + ramp set + levels + shafts | timeline, communication, sensors, capability graph | **validated** |
| `capability_graph.json` | scenario + network + shafts | nothing | **validated + `networkRevision` 409** |
| `stopes.json` | scenario + arrays + levels (no ramp) | timeline | **validated** |
| `timeline.json` | scenario + network + stopes + ramp set + levels + shafts | nothing | **validated** |
| `communication.json` / `sensors.json` | scenario + network + ramp set + levels + shafts — sensors declares the same list as communication (asserted by the registry test) | nothing | **validated** |
| `derived/world.json` | UNREGISTERED — the world statistics snapshot `WorldService._save` writes; no fingerprint lists it and no cascade deletes it | — | only `clear_derived` removes it |

Two structural facts this table makes explicit, both inputs to later AC steps:

* `WorldService.scene` (`world_service.py:128-175`) reads thirteen derived
  documents in one loop and four more below it (`layout_v2`,
  `layout_v2_selected`, `level_accesses`, `ramp_source`) — seventeen raw
  `json.loads`, with no schema validation and no revision check — so a stale file that a per-artifact API would refuse with 409 is
  still projected into the scene (AC-F05, owner AC-01F).
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
`POST …/design/targets`); (2) `derived/world.json` and `ramp_source.json`
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
| **AC-01F** | one validated read resolver for the scene and the per-artifact APIs | auto-regenerating stale data; changing upstream geometry | stale partial snapshot / restart / concurrent invalidation cases; API error changes approved explicitly; FULL |
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
| F03 | search context and candidate state mutate across stages | open — AC-01C / AC-01G |
| F04 | artifact lifecycle is several hand-maintained lists | **resolved by AC-01E**: one declarative registry (`core/artifact_registry.py`) derives every ordered fingerprint list and every source-conditional delete cascade; the 13 `_delete_*` helpers, 12 `_*_input_paths` lists, the inline selection capture and the `InfrastructureService` reach-in are gone; census + e2e proofs in §6. The frontend mirror (`scene/invalidation.ts`) stays AC-01I |
| F05 | the same artifact is stale-checked differently per read path | open — AC-01F; `WorldService.scene` raw reads listed in §6 |
| F06 | revision is a stat fingerprint, publication is not atomic | open — AC-01F (AC-01E deliberately kept the stat semantics); the stat semantics are rule 60 and are NOT to be replaced by a content hash without a decision |
| F07 | level development rebuilds search-side section / track state | open — AC-01G |
| F08 | `ci.yml` and `verify-full.yml` both run the whole gate set | open — AC-01H |
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
