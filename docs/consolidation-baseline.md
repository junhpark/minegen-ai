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

## 6. Artifact dependency and invalidation, as-is

Three mechanisms carry the whole lifecycle, all in
`services/design_service.py` unless noted:

* **fingerprints** — `InputFingerprint.capture` over a per-artifact
  `_*_input_paths` list (`:245-254`), stat-based (name / exists / size /
  mtime_ns), so a byte-identical regeneration is a NEW revision (rule 60).
* **cascading deletes** — 13 `_delete_*` helpers (ten per-artifact, three
  cascades) invoked at write time inside the per-scenario store lock.
* **the source-neutral ramp input set** — `_ramp_input_paths` (`:478-488`)
  injects the four Effective-Ramp-deciding files (`decline_smoothed.json`,
  `layout_v2_selected.json`, `level_accesses.json`, `ramp_source.json`) into
  every downstream fingerprint.

The single global choke point is `WorldService.invalidate` (`world_service.py:184-191`)
→ `ScenarioStore.clear_derived` (`scenario_service.py:106-121`), called from
world generation (`world_service.py:76`), scenario PUT (`api/scenarios.py:81`)
and a schema migration on read (`scenario_service.py:74-77`).

| artifact | fingerprint inputs | regenerating it deletes | read path |
|---|---|---|---|
| `targets.json` | scenario + arrays (TABULAR only) | decline, smoothed, and the ramp-downstream chain iff active source is LEGACY | raw `json.loads` |
| `decline.json` | + targets | smoothed (+ ramp downstream iff LEGACY) | raw |
| `decline_smoothed.json` | + decline | ramp downstream iff LEGACY | raw |
| `layout_v2.json` | scenario + arrays | selection AND level accesses (+ ramp downstream iff LAYOUT_V2) | raw; the scene strips centerlines |
| `layout_v2_selected.json` | + catalogue | ramp downstream iff LAYOUT_V2; rewrites `level_accesses.json` in the same lock | raw to serve; revision + clearance provenance checked when a builder needs the policy (`:643-663`) |
| `level_accesses.json` | written with the selection | — (deleted only with the selection; a SOURCE switch deliberately keeps it, rule 162) | raw |
| `ramp_source.json` | explicit user choice | on an actual change: the whole ramp-downstream chain | raw, silent LEGACY fallback if missing (`effective_ramp.py:75-84`) |
| `tunnel_mesh.{json,glb}` | smoothing set (scenario + arrays + targets + decline) + ramp set — 8 paths | nothing (own stale GLB only) | raw |
| `levels.json` | scenario + arrays + ramp set | shafts, network (+capability), stopes, timeline, communication, sensors, development mesh — **not** the tunnel mesh (rule 74) | **validated** |
| `development_mesh.{json,glb}` | levels set + levels.json | nothing | raw |
| `shafts.json` | levels set + levels.json | network (+capability), timeline, communication, sensors | **validated + `levelsRevision` 409** |
| `network.json` | scenario + ramp set + levels + shafts | timeline, communication, sensors, capability graph | **validated** |
| `capability_graph.json` | scenario + network + shafts | nothing | **validated + `networkRevision` 409** |
| `stopes.json` | scenario + arrays + levels (no ramp) | timeline | **validated** |
| `timeline.json` | scenario + network + stopes + ramp set + levels + shafts | nothing | **validated** |
| `communication.json` / `sensors.json` | scenario + network + ramp set + levels + shafts (`infrastructure_service.py:41-50`) | nothing | **validated** |

Two structural facts this table makes explicit, both inputs to later AC steps:

* `WorldService.scene` (`world_service.py:128-175`) reads thirteen derived
  documents in one loop and four more below it (`layout_v2`,
  `layout_v2_selected`, `level_accesses`, `ramp_source`) — seventeen raw
  `json.loads`, with no schema validation and no revision check — so a stale file that a per-artifact API would refuse with 409 is
  still projected into the scene (AC-F05, owner AC-01F).
* `InfrastructureService` reaches into `design._ramp_input_paths`
  (`infrastructure_service.py:47`) — the only cross-service private access
  (AC-F04, owner AC-01E). `core/artifacts.py` owns eight filename constants
  and `RAMP_OWNING_ARTIFACTS`; it is not a dependency graph, and
  `LEVELS_ARTIFACT` is imported by no module.
* `frontend/src/scene/invalidation.ts` mirrors these cascades in 16 exported
  `after*` helpers (13 `*Regen` cascades plus the three rule-169 identity
  helpers) — a second, hand-maintained copy of the same graph.

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
| **AC-01E** | artifact dependency registry expressing today's fingerprint / delete sets; services stay facades | widening or narrowing a delete set; changing stat-revision semantics | source switch, candidate switch, regeneration, shaft / capability sibling preservation; FULL |
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
| F02 | consuming a saved design re-runs the whole search | open — AC-01D (boundary in AC-01C); call path verified in §7 |
| F03 | search context and candidate state mutate across stages | open — AC-01C / AC-01G |
| F04 | artifact lifecycle is several hand-maintained lists | open — AC-01E; map in §6 |
| F05 | the same artifact is stale-checked differently per read path | open — AC-01F; `WorldService.scene` raw reads listed in §6 |
| F06 | revision is a stat fingerprint, publication is not atomic | open — AC-01E / AC-01F; the stat semantics are rule 60 and are NOT to be replaced by a content hash without a decision |
| F07 | level development rebuilds search-side section / track state | open — AC-01G |
| F08 | `ci.yml` and `verify-full.yml` both run the whole gate set | open — AC-01H |
| F09 | typed-API principle vs `dict[str, Any]` layout payloads | open — AC-01C / AC-01I |
| F10–F16 | resolver duplication, local import cycles, large builders, owner-string duplication, CLAUDE.md accumulation, marker/fixture coupling, search timing labels | open, P2 — handled inside the step that touches the module, never as a standalone rewrite |

## 11. Measurement plan

Compared on one machine, one scenario set and one source revision, before and
after a step. No target value is promised in advance.

* cold-process time to selected levels / shafts / mesh, and the number of full
  `LayoutV2Search.run` calls it costs.
* FAST / FEATURE / FULL wall time and CI runner minutes.
* the number of lifecycle sites a new artifact must touch.
* for a behaviour-preserving extraction: payload, geometry, ranking and
  failure differences — required to be **0**.
