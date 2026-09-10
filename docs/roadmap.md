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
| 20D | Rulebook compliance + unified development mesh + branch walkthrough | explicit rulebook compliance reporting ("two independent escape routes" once the capability graph defines shared edges), multi-candidate comparison; typed-junction minimum union (not a general Boolean engine), branch walkthrough; legacy A* kept as baseline |
| 21A | Longhole migration | prove the new MiningMethodPlan abstraction with already-validated geometry |
| 21B | Cut & Fill | lift / cut / backfill 4D mining method |
| 21C | Room & Pillar | limestone; pillar, room, bench, double bench |
| 22 | Analysis / Economics / Compliance | production, development, cost, revenue, cashflow + rule compliance + layout comparison |
| 23 | External Simulation Bridge | Ventsim, AnyLogic, blast, support, Unreal adapters |

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

Phases 01–20B are described in `docs/architecture.md`; the invariants they
established are `CLAUDE.md` rules 1–169.

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
