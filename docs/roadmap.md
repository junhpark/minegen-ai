# MineGen-AI roadmap

## Product name and direction

**Synthetic Mine Design & Simulation Sandbox.**

MineGen-AI generates *synthetic* underground mines: a seeded geological
world, an engineering-constrained decline, level development, stopes, a
scheduling baseline and infrastructure planning, all reproducible from a
persisted scenario document.

**"Digital Twin" is reserved** for a separate future track: measured mines
captured by LiDAR / 3DGS survey of real workings. The two threads must never
share the term. A synthetic sandbox mine is not a twin of anything, and a
measured twin is not generated. Keeping the vocabulary disjoint keeps the
claims honest — nothing in this repository is calibrated against a real
mine.

## Phase order

Active core sequence (Park, Phase 18 directive): the Hugging Face public
demo (D0) is **deferred** and is no longer the next phase.

| Phase | Purpose | Key change |
| --- | --- | --- |
| 17.1 | Scenario / viewer stabilisation | scenario isolation, 4D raw-path suppression, Field Slice toggle, Parameters UI — done |
| 18 | Spatial Field Core | remove BlockModel/SMU semantics, batch field API, replace longhole grade proxy, golden-scenario harness — done |
| 19 | Implicit Geological Orebody | WARPED_VEIN: authoritative implicit solid (φ), variable thickness, pinch & swell, warped mid-surface, asymmetric outline → derived approximate clearance → derived marching-cubes mesh; legacy layout stays TABULAR-only — done |
| 20A | Parametric Layout Family Search — families & Effective Ramp | SPIRAL / LONGITUDINAL / SWITCHBACK finite grids, numerical level service, delivered-centerline validation, EXACT / CONSERVATIVE clearance, hierarchical search + 3-group ranking, source-neutral Effective Ramp (LEGACY \| LAYOUT_V2) driving tunnel → levels → network → timeline → walkthrough for TABULAR; WARPED_VEIN candidates / ranking / rendering — done (Phase 20 NOT complete) |
| 20B | Ramp junctions, level access drives, method-aware level development | RAMP_JUNCTION → LEVEL_ACCESS → LEVEL_ENTRY topology, level-development anchors, finite deterministic access planning with hard validation, access length in ranking, `level_accesses.json`, method split (LONGHOLE lattice vs generic backbone; CUT_AND_FILL typed boundary), network / timeline / infrastructure connectivity, Phase 20A circumradius closeout — done. Closeout v3: preferred access length (6 × tunnel width planning default), stage-2 reach screen demoted to a heuristic (NO_RL_CROSSING stays hard), shortlist-starvation audit, LEVEL_ACCESS / DRIFT / CROSSCUT excavation meshes with CAP / OPEN endpoint QA, Layout v2 as the primary UX with the legacy decline chain as an Advanced section — done. Drifts / crosscuts for implicit bodies and the WARPED_VEIN walkthrough stay deferred |
| 20B.3 | Viewer cleanup + robustness + golden policy | material-level brightness (single shared material path, walkthrough rebalanced), independent 4D ramp / development mesh toggles, fail-closed reveal metadata (centerline fallback never disappears), golden retention policy (latest full JSON only; legacy 22-case lock never deleted) — done |
| 20C.1 | Switchback hairpin station + shortlist yield + WARPED diagnosis | hairpin arc–straight–arc level station as a declared finite grid axis (`switchback_station_length_m ∈ {0, 2 × minimum_turnout_straight_buffer}`) competing on score, no threshold change — GEOMETRY-STRESS must recover or its remaining constraint be proven; shortlist yield audit (family-internal cheap rank vs detailed pass) before any reservation change; WARPED multi-seed feasibility diagnosis (≥ 30 seeds, diagnostic only); runtime report ≤ 20 s on TABULAR-REFERENCE. Delivered: V (rule 174 excavation direction), S (rule 175 station axis), Q (rule 176 geometric access screen — GEOMETRY-STRESS SUCCESS in production, missed winner / family 0 / 7), W (32 seeds, 9 SUCCESS; dominant failure LEVEL_ACCESS_INFEASIBLE / GRADE_LIMIT, clearance never binding → 20C.2 input); TABULAR-REFERENCE measured 23.4 s (> 20 s target, reported). Closeout: screen authority is the clearance policy's (56 false blocks measured on the conservative side, 0 on EXACT; the ordering change was attempted and reverted on the family-yield acceptance), pooled AUC re-derived pair-weighted within case (0.673 / 0.507, verdicts unchanged), 32-seed survey re-run identical |
| 20C.2 | WARPED level development (section(z)) + shaft / capability graph | implicit-orebody horizontal section contract (z-slice polylines → local tangent / normal / footwall side / span / ore contact) so level drifts follow the local trace; shaft + capability graph (who may use which edge) ahead of 20D compliance. **20C.2A delivered** (rules 177–180): contains()-authoritative section geometry (4-connected dominant component, marching-squares contour, resolution contract + cell budgets), footwall trace (w_h orientation seed only, typed SECTION_FOOTWALL_AMBIGUOUS, no PCA), offset development backbone as the CLEARANCE-POLICY level set at the stand-off (an in-plane 2-D offset measured 82 % under-clearance on WARPED-301 — rejected), stand-off-scale smoothing with clearance re-validation, curved anchors with identical screen / stage-4 semantics, curved drifts / chainage stations / contains()-bisection crosscuts (WARPED-301 E2E levels + development mesh SUCCESS; WARPED stope stays the typed Phase 09 boundary). **20C.2B delivered** (rules 182–185): core-enum unification, `scenario.shafts` explicit vertical shaft specs → deterministic planner (terrain collar, stations at existing level nodes, validated station drives, typed ShaftFailureCode) → `shafts.json` → MineNetwork SHAFT / SHAFT_STATION_ACCESS integration (timeline sinking precedence, infrastructure geodesics) → `capability_graph.json` (explicit per-edge capability sets, required paths, egress advisory, `can_reach`); shaft optional, ramp coexists, capability ≠ capacity; shaft mesh / inclined shafts / placement optimization deferred |
| 20C.3 | Bounded local repair + FIGURE_EIGHT / HYBRID | bounded local A* / repair inside the family corridor, FIGURE_EIGHT / HYBRID families; horizontal surface entries (adit). **20C.3A delivered (diagnose-before-build): failure locality census, BOUNDED LOCAL REPAIR = DEFERRED.** 147 DETAILED candidates of the 13 NO_FEASIBLE seeds of the 32-seed WARPED survey were localized on the delivered polyline (`golden/phase20c3a_failure_census.json`, `docs/verification/phase20c3a_failure_census.md`, production changes 0): LEVEL_ACCESS_PROBLEM 76, MULTI_CLUSTER_CLEARANCE 37, PORTAL_APPROACH 22, FIRST_LEG_GLOBAL_ABOVE_TERRAIN 6, LOCAL_REPAIR_GEOMETRY_RULE 5 of which PHYSICALLY_LOCAL_REPAIRABLE 3 (expected seed recovery 0–1); Hybrid A* has no terminal-heading goal contract and Phase 05 smoothing rebuilds the whole segment, so a repair engine would be a planner / smoother redesign for ≈ 2 % of the failures. The census is a historical diagnostic baseline, never an optimization target or a preserved threshold. 76 + 37 = 113 is a reference-consistency INVESTIGATION population (HYPOTHESIS_NOT_YET_CAUSALLY_CONFIRMED: corridor from the global footwall track edge vs anchors from the conservative offset trace), 22 + 6 = 28 a portal / family-approach grouping. 20C.4 (next row) executed the reference-consistency investigation and closed the 113 population; portal / family-approach geometry is the next diagnostic target; new families are not justified by this census |
| 20C.4 | Level-access reference consistency (construction ServiceReference) | **Delivered (Gate A causal proof → Gate B contract → Gate C implementation → Gate D controlled comparison; rule 186).** Gate A (`golden/phase20c4_reference_audit.json`): the LEVEL_ACCESS_PROBLEM population was REFERENCE_CAUSED — corridor from the global track edge vs anchors on the certified level set, nearest approach p50 6.8 m on 122 failed levels, every control ≥ 23.7 m, corridor the moving side. Gate B: one CONSERVATIVE CONSTRUCTION `ServiceReference` (the WORLD-policy offset traces stage 4 caches) consumed by the SPIRAL rim and the SWITCHBACK stack — `delta = max(0, support + 6 widths − current)` over the ramp's own along-extent, outward only, exact 0 on TABULAR / explicit stand-off, LONGITUDINAL deferred. Gate C step 0 resolved F1 (window artefacts + genuine hairpin encroachment, no crossing). Gate D: layout-v2 goldens — four EXACT cases byte-identical, WARPED-301 winner unchanged with the rim 4–10 m further out, WARPED-307 NO_FEASIBLE → SUCCESS (12 feasible); 20C.3A census re-run on its 13 seeds — 9 SUCCESS, LEVEL_ACCESS_PROBLEM 76 → 0, MULTI_CLUSTER 37 → 6, PORTAL_APPROACH 22 → 42 (typed, secondary); 32-seed survey 19 → 28 SUCCESS (9 flips, 0 regressions), feasible candidates 104 → 283, level-access rejections 589 → 9, winner family SWITCHBACK 18 → 7 / SPIRAL 1 → 21 (a switchback stack consumes the pair-band maximum of delta and so pays the longer accesses; no coefficient changed). No hard gate, threshold, score weight, screen semantic or planner authority changed. Remaining NO_FEASIBLE seeds (302, 306, 309, 321) are the portal / first-leg approach population (ABOVE_TERRAIN at the fixed start) — the next diagnostic target. Open observation: ramp ↔ level-drift proximity is measured by no gate; a separation diagnostic (never a gate) is a follow-up. **PR #28 closeout follow-up:** the SWITCHBACK consumption window is DERIVED from the stacking mechanics (delta applied exactly at every near-leg start; one window `[z − drop − dz/2, z + dz/2 + ε]` on the absolute requirement; a parity edge term for far-first stacks) — the 925ce25 double ± 2·drop band is gone and the pair-window test is recorded red on it (`phase20c4_gate_c.md` §11). Gate D re-run: survey 28 → 29 / 32 (309 recovered, 0 regressions), census 9 → 10 / 13 (PORTAL_APPROACH 42 → 28, FEASIBLE 85 → 94), SWITCHBACK corridors move a mean 15.3 m less far outward (975 candidates, max 50.7 m), SPIRAL bit-identical, four EXACT goldens byte-identical |
| 20D | Rulebook compliance + unified development mesh + branch walkthrough | explicit rulebook compliance reporting ("two independent escape routes" once the capability graph defines shared edges), multi-candidate comparison; typed-junction minimum union (not a general Boolean engine), branch walkthrough; legacy A* kept as baseline. **20D.1 delivered**: typed local junction union of the ramp / development render meshes (`design/junctions.py`; RAMP→LEVEL_ACCESS, LEVEL_ACCESS→DRIFT, DRIFT→CROSSCUT identified from the declared topology, blocking quads omitted inside a 2-width window with junction-local ring refinement, exact per-interval reveal offsets); no CSG, no centerline / lifecycle / layout change; branch walkthrough and the all-development watertight union remain. **20D.1.1**: corrected parent-side typed aperture semantics so boundary-contacting wall quads do not survive as a full-height blocker (surface-overlap rule on non-floor parent quads, red-test-first at every declared junction); parent floor remains authoritative, no general CSG introduced. **20D.1.2** corrected child-side typed-union floor semantics at straddling junction quads: the portion of a child floor inside the parent excavation is removed while the exterior child floor is retained (typed local child-floor boundary clipping at the same tolerance surface, deterministic bisection on the quad's own edges, render-only), eliminating shallow-angle floating floor slabs without changing centerlines, profiles, planning or introducing general CSG. **20B.x (RAMP_ACCESS vertical continuity, rule 188)**: the level-access connector follows the ramp floor elevation through the plan overlap (junction-windowed ramp query) and hands off through a bounded parabolic vertical curve (1 % grade change per metre) to one constant tail at the exact entry — the design-side seam step the clipping exposed (+0.30 … +1.10 m) is 0 along the traffic centerline; plan geometry, junctions, entries, ramp and topology unchanged; the un-banked far-end wall-line residual (≈ 0.2 m) is the recorded limitation for the 20D unified mesh; GEOMETRY-STRESS golden loses its winner for hard-gate reasons pinned by an explicit oracle test, baseline re-generated as `phase20bx_layout_v2` **20D.2 delivered** (rule 187): STATIC_FINAL walkthrough consumes both authoritative ramp and development GLB collision geometry (`walkthrough/developmentRuntimeGeometry.ts` with validated `ranges`, `DevelopmentColliderSet`; one physics world; no frontend resweep, proxy or collision-only geometry); RAMP_ACCESS → LEVEL_ACCESS → DRIFT → CROSSCUT and the reverse are physically traversable through the typed junction apertures in the browser (PERSON capsule unchanged); composition fails closed on a malformed advertised development GLB and keeps the ramp-only walkthrough without one; walkthrough visibility is the authority set (visual = collidable); the §10 endpoint-cap audit reproduced a real DRIFT_CAP obstruction at every drift-extremity crosscut station and the cap is now cut by the same typed local rule as the child floor (`cut_cap`); TIMELINE_SNAPSHOT remains safely ramp-contained (ephemeral wall-line aperture barriers, fail-closed identity, browser-verified) — temporal development traversal deferred; **20D.2.1** (PR #42 review blocker): at drift-extremity crosscut stations (an L-junction — the drift ends AT the station) the half of the crosscut's OPEN start ring beyond the drift end faced rock with no surface (TABULAR 8 / 20, WARPED-301 28 / 187 stations); closed by the typed CHILD MOUTH CAP (`cut_mouth_cap`, mirror of `cut_cap` against the parent envelope, DRIFT_CROSSCUT only, render-only; interior T-junctions bit-identical, faces untouched, no frontend collider); minimap / teleport stay ramp-based (branch teleport, temporal branch physics, branch infrastructure interaction later); **20D.3 delivered** (rule 189): READ-ONLY design assessment + candidate comparison (`assessment/`, `GET …/design/assessment`, `LayoutPanel` DESIGN ASSESSMENT / ALTERNATIVES) projected from the catalogue, selection, ramp source and capability graph — typed checks with explicit authority (hard rule / validation / advisory / info), ranking and scores preserved exactly, dual-egress an explicitly labelled design advisory, no persisted artifact, no statutory claim. **Phase 20 COMPLETE** |
| 23A | MineExchange Core v1 — **DELIVERED** (rule 190, `docs/mine-exchange.md`) | versioned (`1.0.0`), read-only, deterministic interoperability bundle projected from authoritative state: terrain node grid (CSV / ESRI ASC / open TIN), orebody authority JSON + derived closed mesh (TABULAR / ELLIPSOID / WARPED_VEIN, QA'd), fault planes, individual closed excavation solids through the production sweep helpers (never unioned; `mine_multibody.stl` is a concatenation), verbatim render GLBs, centerlines CSV / DXF, network and capability DTOs; world-only exports with manifest omissions; `POST …/export/mine-exchange` (sync, no persisted artifact); Scenario-panel button. Stopes / mining-method contract delivered by 21A as MineExchange 1.1 |
| 21A | Mining Method Core + Longhole migration + MineExchange 1.1 — **DELIVERED** (rule 192; the former 21A.2 is folded in) | ONE mining-method registry (`mining/methods/registry.py::plan_for`, explicit for every `MiningMethodType`, no `None`, no longhole fallback) resolving a declarative `MiningMethodPlan` (WHAT: production-development intent, station lattice pitch / margin, production generation) consumed by `LevelDevelopmentBuilder` (WHERE / validity) and `DesignService.generate_stopes`; the longhole geometry algorithm is untouched and its outputs are proven unchanged against the committed pre-migration parity fixture (two-tier gate: structure / ids / counts exact, floats within 1e-10; canonical digests advisory) (`tests/fixtures/phase21a/longhole_parity.json`: TABULAR legacy, TABULAR layout-v2, CUT_AND_FILL, WARPED typed boundary); goldens unchanged. Reserved methods (CUT_AND_FILL, ROOM_AND_PILLAR, SUBLEVEL_CAVING, SHRINKAGE_STOPING) are explicit unsupported plans (generic backbone + UNSUPPORTED_METHOD + FAILED stopes). MineExchange **1.1.0**: `semantics/mining_method.json` (always present), `production/stopes.json` + one authoritative closed prism per stope (STL / OBJ / GLB, independent QA), `STOPE` entity kind, STOPES omission semantics ARTIFACT_ABSENT / SOURCE_NOT_SUCCESS (TIMELINE stays NOT_IN_V1), method-authority mismatch a typed 409, stopes exportable without a network. Frontend: read-only "Mining method" card at the top of the Mining tab (Implemented / Not implemented, parameters in Details, NO selector), export contents rows, keyboard tab focus follows the arrow keys. No drawpoint / pillar / backfill / room / cut / bench entities |
| 21B/C | Cut & Fill + Room & Pillar — **DELIVERED** together (rules 193–196) | Both methods are first-class registered plans (`methods/cut_fill.py`, `methods/room_pillar.py`; `methods/solids.py` shared prism helpers) — the registry table is now Longhole / Cut & Fill / Room & Pillar IMPLEMENTED, Sublevel Caving / Shrinkage UNSUPPORTED; `plan_for` remains the only method authority (access pattern → level builder, production schedule → timeline builder, typed payload → scene / MineExchange). ONE active production artifact at the legacy path `derived/stopes.json`, typed `ProductionPayload` union; `POST/GET …/design/production` method-generic, `…/design/stopes` Longhole-only (409 otherwise); `MiningConfig.methodParameters` typed union with backend defaults. Cut & Fill: dip-aware equal-partition lifts, snake-ordered cuts, 1:1 semantic backfills, single conservative PREP→STOPING→MUCKING→BACKFILL→CURE chain. Room & Pillar: alternating band grid, ROOM cells with HEADING / BENCH stages, retained PILLAR solids never scheduled, single-front schedule from the central cell. Longhole levels / stopes / network / timeline proven byte-unchanged against the 21B/C baseline captured on 7052606. MineExchange **1.2.0** (CUT / BACKFILL / ROOM / BENCH / PILLAR entities, per-method production documents, one omission group per bundle). Frontend: method selector with Implemented / Not implemented badges, method-specific parameter editor (Apply = scenario PUT + world regeneration), generic Production action, kind-coloured production layer + 4D states from the backend transitions. Not implemented: Sublevel Caving, Shrinkage, WARPED production, production-room walkthrough, geotechnical pillar design |
| 22A/B | Mine Analysis Core + Planning Economics — **DELIVERED** (rules 197–202, `docs/analysis-economics.md`) | READ-ONLY downstream projection (`analysis/`, `GET …/analysis`, sync, no derived artifact, ONE re-verified snapshot): development lengths / GROSS excavation volumes per edge type from MineNetwork, planned mined tonnes / volume / grade proxy per method (Longhole stopes, Cut & Fill cuts + separate backfill, Room & Pillar extraction units + separate retained pillars), schedule KPIs and planning ratios from the timeline, cross-artifact integrity (409 ANALYSIS_SOURCE_INCONSISTENT), partial 200 for absent sources; user-authored `economics.json` beside the scenario (`GET/PUT …/analysis/economics-config`, sha256 revision, zero invalidation), cost / gross-revenue summary, Planning Cashflow buckets and Baseline Planning NPV (mid-bucket discounting); Analysis workspace (Overview \| Economics) with the assumptions editor and the permanent synthetic-economics disclaimer. Non-scope: rule compliance, candidate what-if economics, IRR / tax / royalty, ventilation / haulage / capacity |
| 22C | Design Rulebook + Layout Development Economics — **DELIVERED** (rules 203–206, `docs/layout-comparison.md`) | Rules tab = a PRESENTATION of the Phase 20D.3 design assessment (statuses / authorities / scopes verbatim, advisories never a pass mark, no overall compliance score, no second evaluator); `GET …/analysis/layout-comparison` (sync, read-only, ONE re-verified snapshot) = Comparable Layout Development Cost per ranked candidate from the PERSISTED `diagnostics.length3d` and `access.totalAccessLength` × the `economics.json` ramp / level-access rates only (drifts, crosscuts, shafts, production, processing, backfill, opex, capital, revenue, NPV explicitly excluded), rows in the persisted ranking order with plain Δ vs winner / selected and the 20D.3 scores; NOT_CONFIGURED keeps the geometry rows with null costs; INACTIVE_LAYOUT_V2 under a LEGACY ramp; Layout comparison tab with summary, table, optional bars. Ranking / winner / selection untouched; no candidate what-if, no candidate NPV, no recommendation |
| 23B | External software adapters — **23B.0 DELIVERED (architecture / gap analysis, docs-only)**, adapters PLANNED (`docs/external-adapters.md`) | MineExchange is the ONLY external boundary; adapters are translators (never planners) consuming a MineExchange bundle, four-state source mapping (AVAILABLE / ABSENT / SOURCE_NOT_SUCCESS / UNSUPPORTED_BY_ADAPTER), no silent defaults (NOT_PROVIDED / USER_REQUIRED / ADAPTER_DEFAULT_EXPLICIT), typed failure candidates, adapter versioning separate from MineExchange. Gap analysis: Ventsim = YES_WITH_EXPLICIT_ADAPTER_CONFIG on MineExchange 1.2 (DXF centerlines → Convert Centrelines; dimensions via attribute table; resistance / fans / heat are user inputs); AnyLogic = MineExchange 1.3 (operational / timeline semantics) REQUIRED first; Unity / Unreal = static packaging ready on 1.2, semantics via an identity table. Sequence: 23B.1 Ventsim seed adapter → 23B.x MineExchange 1.3 → 23B.2 AnyLogic → 23B.3 Unity / Unreal → future result import / overlay. FIRST IMPLEMENTATION TARGET = Ventsim. RS3 / blast / support adapters remain unscheduled |

## Phase 20 completion gate

Phase 20 is **COMPLETE** (Phase 20D.3 closeout):

| Item | State |
| --- | --- |
| 20A layout search (families, delivered-centerline validation, clearance policy, ranking, Effective Ramp) | DONE |
| 20B access / development (ramp junctions, level accesses, method-aware level development, development meshes, rule 188 vertical continuity) | DONE |
| 20C warped / shaft / capability (section(z) curved development, shaft planner, capability graph, construction ServiceReference) | DONE |
| 20D unified geometry (typed junction union, child-floor clipping, cap cut, child mouth cap) | DONE |
| 20D branch walkthrough (STATIC_FINAL development collision, temporal aperture barriers) | DONE |
| 20D assessment / comparison (read-only design assessment, candidate comparison, dual-egress advisory) | DONE |

Deferred Phase 20 backlog — explicitly not blocking, each a later phase or
follow-up decided on its own: bounded local A* refinement of a layout
candidate; new layout families (FIGURE_EIGHT / HYBRID, true straight-insert
turnouts); temporal branch traversal in the TIMELINE_SNAPSHOT walkthrough
(development colliders by day); the all-development exact CSG / watertight
union and a banked junction floor; branch teleport / routing, branch
infrastructure interaction and a branch-aware minimap; shaft mesh, inclined
shafts and shaft placement optimization; a ramp ↔ level-drift separation
diagnostic (never a gate); the WARPED stope geometry (typed Phase 09
boundary); the remaining NO_FEASIBLE portal-approach seeds; the recorded
CONSERVATIVE-side false-block behaviour of the access screen; rulebook /
economic analysis (Phase 22) and external simulation adapters (Phase 23).

Follow-up S1 (Ramp / Footwall / Access Standoff Semantics Rationalization)
was executed by Phase 20B.1 commit C: the audit table lives in
`docs/algorithms.md` ("Phase 20B.1 — stand-off / clearance semantics
audit"); `RampConstraints.clearance` is documented UNWIRED/RESERVED, the
main-ramp corridor stand-off gained its own audited default
(`footwall_access_offset + 6 × tunnel_width`), the WARPED conservative
bound is narrowed only by the stage-4 local lattice refinement, and
per-method stand-off needs remain with the Phase 21 mining-method work.

Deferred deployment item (not scheduled):

| Item | Purpose | Key change |
| --- | --- | --- |
| D0 | Hugging Face public demo | single Docker Space, session isolation, TTL, prebuilt demo scenario; demo mode (viewer-only: OrbitControls autoRotate roundview paused on input, 20× looping 4D playback reusing the timeline clock, one "Demo" HUD toggle, disabled in walkthrough) |

Phases 01–20E, 21A, 21B/C, 22A/B, 22C and 23A are described in `docs/architecture.md`;
the invariants they established are `CLAUDE.md` rules 1–202.

## Phase 20E — UI/UX consolidation (frontend only)

Information-architecture pass before Phase 21A: the long Design panel
becomes workflow tabs (Layout → Develop → Network → Mining), infrastructure
becomes Systems (Communication | Sensors), technical paragraphs move into ⓘ
popovers, detailed numbers into `Details`, the legacy Hybrid-A* chain stays
one `Advanced` section, status and button hierarchy are unified, and the
left panel widens to 320 px with Layers collapsed at the bottom. The Mining
tab is shaped so Phase 21A can add its mining-method card above Stopes; no
method selector ships in 20E. API, artifacts, invalidation, geometry and
goldens are unchanged (CLAUDE.md rule 191).

## Phase 21A — Mining Method Core (backend registry + MineExchange 1.1)

The last remaining method dispatch (`if method is LONGHOLE …` in the level
builder, `strategy_for` in the design service) is unified behind ONE
registry: `plan_for(method)` returns an explicit `MiningMethodPlan` for every
enum member — `LongholeOpenStopingPlan` (IMPLEMENTED) or an
`UnsupportedMethodPlan` (UNSUPPORTED_METHOD) — and there is no path on which
an unregistered method could fall back to longhole geometry. The plan owns
WHAT (production-development intent, the station-lattice pitch / margin, the
production generator); `LevelDevelopmentBuilder` keeps WHERE and validity.
No new persisted artifact, no rewrite of the longhole algorithm, every
existing failure string preserved; the §14 regression gate (longhole
`levels.json` / `stopes.json` unchanged under the two-tier parity gate —
structure / ids / counts exact, floats within 1e-10, digests advisory —
goldens unchanged) is the acceptance instrument. MineExchange grows to 1.1 additively (stopes + method semantics,
`docs/mine-exchange.md`); the Mining tab gains its read-only method card.
Cut & Fill (21B) and Room & Pillar (21C) were NOT implemented in 21A; they
entered through the same registry as their own plans in 21B/C below.

## Phase 21B/C — Cut & Fill + Room & Pillar (first-class production methods)

Delivered as ONE combined phase (CLAUDE.md rules 193–196). The registry table
becomes Longhole / Cut & Fill / Room & Pillar IMPLEMENTED and Sublevel Caving
/ Shrinkage Stoping UNSUPPORTED; every downstream consumer still asks the plan
(`production_access_pattern`, `production_identity`, `production_schedule`)
and never the method. The active production artifact keeps the legacy path
`derived/stopes.json` but is a method-typed `ProductionPayload`; the new
`…/design/production` route is method-generic while `…/design/stopes` stays
Longhole-only. Cut & Fill and Room & Pillar are new implementations over
shared prism helpers — the longhole algorithm is untouched and its four
artifacts are proven unchanged against the 21B/C baseline captured on the
pinned pre-migration HEAD (`tests/fixtures/phase21bc/longhole_baseline.json`).
The timeline builder executes the plan's schedule spec (Longhole's chain moved
verbatim), MineExchange grows to 1.2.0 additively, and the Mining tab gains
the method selector + parameter editor and the generic Production action.
Non-scope: Sublevel Caving, Shrinkage Stoping, WARPED_VEIN production
geometry, production-room walkthrough, geotechnical pillar design.

## Phase 22A/B — Mine Analysis Core + Planning Economics (delivered together)

A downstream, read-only analysis layer over the persisted authoritative
state (rules 197–202): the MineNetwork is the development authority (length
and GROSS excavation volume per edge type), the active production artifact
the tonnage authority (planned mined tonnes from geometry × density; pillars
retained, backfill semantic), the MineTimeline the timing authority (baseline
duration, ramp completion, first production, task counts), and a
user-authored `economics.json` beside the scenario — never a derived
artifact, never an invalidation trigger — the assumption authority
(development rates per edge type, production rate per method, processing,
backfill, fixed opex, initial capital, gross revenue per mined tonne, discount
rate, bucket size). Costs and gross revenue follow the timeline tasks into
fixed cashflow buckets; the Baseline Planning NPV discounts each bucket at its
midpoint. The frontend Analysis workspace (Overview | Economics) renders the
projection and edits explicit assumptions only, under the permanent
"Synthetic planning economics" disclaimer. Non-scope: external adapters
(23B), IRR / tax / royalty / inflation, ventilation, haulage and capacity.

## Phase 22C — Design Rulebook + Layout Development Economics

Two read-only views over existing authorities (rules 203–206,
`docs/layout-comparison.md`). The **Rules** tab presents the Phase 20D.3
design assessment as a rulebook — Category · Rule · Status · Authority ·
Scope · Evidence, statuses verbatim, a design advisory never a pass mark, an
informational fact never pass / fail, no overall compliance score — through
the existing `GET …/design/assessment`; no second evaluator exists. The
**Layout comparison** tab and `GET …/analysis/layout-comparison` price every
ranked layout-v2 candidate's PERSISTED main-ramp length and level-access
length with the `economics.json` ramp / level-access rates: a *Comparable
Layout Development Cost* that includes only candidate-owned development and
explicitly excludes drifts, crosscuts, shafts, production, processing,
backfill, fixed opex, capital, revenue and NPV. Rows keep the persisted
engineering ranking; winner, selection and scores are the layout
authority's and are never changed by cost; no candidate what-if quantity and
no candidate NPV exist. Non-scope: candidate regeneration, IRR / payback /
tax / royalty / depreciation / inflation, pricing, grade revenue, recovery,
ventilation / haulage / fleet / capacity, Monte Carlo, auto-selection,
optimization, 23B adapters, calibration, resources / reserves.

## How this list is used

- A phase is implemented only when it is the requested phase. Nothing in
  this table authorises starting the work early.
- Phase-specific invariants land in `CLAUDE.md` **with the phase that
  implements them**, never in advance of the code they constrain.
- The order is a plan, not a contract: a phase may be re-scoped or split
  before it starts, but it is never skipped silently.

## Git workflow

Bundle delivery is retired. Local commits may be created once a scoped
implementation and all required quality gates pass; every remote write —
push, force-push, merge, PR create/update — needs a new explicit approval
for that specific action. See `CLAUDE.md` rule 126.
