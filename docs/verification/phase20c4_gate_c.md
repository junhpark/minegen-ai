# Phase 20C.4 — Gate C implementation and Gate D controlled comparison

Commits on `phase-20c4-access-reference-consistency` after the reviewed Gate A/B baseline (2df98f2): C0 67cea1f (F1), C1 31055db (`ServiceReference`), C2 c09978c (SPIRAL), C3 4ed0a35 (SWITCHBACK), C4/D (this closeout). Production files touched: `layout/reference.py` (new), `layout/families.py`, `layout/search.py`. Everything the directive lists as preserved is untouched: candidate enumeration, stage-2 screen semantics and authority, stage-3 ordering, stage-4 authority, the candidate-specific clearance policy, anchor trace-chainage semantics, every level-access hard gate, score coefficients, Effective Ramp ownership, shafts, MineNetwork, CapabilityGraph, and the frontend (which reads no new field). Design reference: `docs/algorithms.md` "Phase 20C.4"; rule 186 in `CLAUDE.md`.

## 1. What changed (one authoritative reference, two consumers)

`build_service_reference` (once per `LayoutV2Search.run`) collects, for every serviceable level, the interior of the WORLD-policy offset development trace at the world anchor stand-off — the cached trace stage 4 already builds for coarse anchors (token `"WORLD"`; `test_reference_reads_the_same_world_trace_stage_4_caches` proves no second clearance field exists). `families.corridor_profile` is the single consumer entry point; `build_spiral` and `build_switchback` add its `delta(z)` exactly where the track edge enters their corridor, so an inactive reference (TABULAR, explicit `footwallStandoff`) is bit-identical (`+0.0`). LONGITUDINAL is deferred unchanged.

| quantity | definition |
|---|---|
| footprint | ramp's OWN along-extent: SPIRAL rim `R` about the axis; SWITCHBACK `leg/2 + R_min` about the shared leg centre |
| support(L) | max `p·n` over reference points inside the footprint (empty ⇒ delta 0, never a fallback) |
| delta(L) | `max(0, support + 6·width − (footwall_edge(z_L)·n + standoff))`, piecewise-linear in z, constant beyond the levels |
| SWITCHBACK | pair-band maximum of delta (± 2 cycles) against the most ore-ward track edge in the band (a near leg at a pair start serves every level of its pair; the mid-pair near leg takes the smaller boundary lateral; the leg lags the edge drift, 2.9 m on 301 L04) |
| inactive | TABULAR analytic path, explicit stand-off, zero profile — `np.array_equal` against the reference-less build |

## 2. Gate C step 0 (F1) — `phase20c4_c0_f1.md`

Reading (b) does not hold: no ramp ↔ backbone crossing near a level plane and no excavation conflict (minimum 3-D distance 18.1 m ≥ 15 m). 322 L08 / L09 and 305 L12 were window artefacts (whole-trace fallback on an empty footprint; a window centred on a terminal hairpin over a 33° oblique backbone). 305 L05 / L07 are genuine encroachments of the leg-end hairpin on the level backbone (14.9 / 19.6 m plan) — the mechanism the contract corrects. SWITCHBACK entered Gate C under the two footprint refinements.

## 3. Tests (all pass; the 307 cases are `slow`)

- `tests/test_service_reference.py` (8): profile semantics; TABULAR inactive + every family bit-identical; explicit stand-off keeps the legacy corridor; WARPED-301 active / deterministic / outward-only / empty-footprint-zero / payload; same cached WORLD traces; stage-4 dominance (REFINED candidate backbone never outward of the construction backbone beyond the section grid resolution, policy rebuilt through `candidate_policy`); band-max exactness against a brute-force grid; WARPED-307 SPIRAL delta > 0 on every level the rim runs alongside and the delivered helix is the corrected one.
- `tests/test_corridor_reference_integration.py` (4): 301 SPIRAL RL crossings ≥ support + 6 widths and moved by exactly the profile (one-sample tolerance), never inward; zero-profile candidates bit-identical, corrected ones keep their radius; 301 SWITCHBACK near legs clear every level plane within half an interval of their z-span and move outward cycle by cycle (legacy near legs 0.2 m from the backbone, corrected 33–48 m outward), R_min / leg spacing / nominal leg length untouched; WARPED-307 SPIRAL-n1-CW-e+0-g0.100 and SWITCHBACK-k1-p+0-CW-s50-g0.120 hold six widths at every RL crossing they run alongside — a SEPARATION regression, never a success-count assertion.
- `tests/test_layout_v2_golden_smoke.py`: baseline moved to `phase20c4_layout_v2.json`; the hard-coded "WARPED-307 stays NO_FEASIBLE_CANDIDATE" expectation is replaced by SUCCESS with the Gate A causal explanation (its failures were REFERENCE_CAUSED); ACCESS-INFEASIBLE remains the explicit-failure detector.

## 4. Golden comparison — `backend/golden/phase20c4_vs_20c2a_layout.json`

`python -m minegen.regression layout-v2 --suite full --label phase20c4_layout_v2 --out golden` (237.9 s), compared with `layout-v2-compare golden/phase20c2a_layout_v2.json golden/phase20c4_layout_v2.json`. Retention: `phase20c2a_layout_v2.json` removed (CSV and comparison kept), `docs/architecture.md` reference updated.

| case | policy | contract diffs | metric drift | reading |
|---|---|---|---|---|
| TABULAR-REFERENCE | EXACT | 0 | 0 | byte-identical (reference inactive) |
| GEOMETRY-STRESS | EXACT | 0 | 0 | byte-identical |
| ACCESS-INFEASIBLE | EXACT | 0 | 0 | byte-identical (still NO_FEASIBLE_CANDIDATE) |
| CUT_AND_FILL | EXACT | 0 | 0 | byte-identical |
| WARPED_VEIN-301 | CONSERVATIVE | 7 | 29 | winner unchanged (SPIRAL-n1-CW-e+0-g0.120), feasible 10/92 unchanged; the rim moves outward: access-plan separations 32.6–38.2 → 36.7–37.5 m, excavation separations 12.8–16.7 → 15.8–16.6 m, access lengths 33–44 → 40–44 m (total 543.8 → 580.3 m), access gradients 0.013–0.061 → 0.031–0.032, cheap-feasible 51 → 48, shortlist / ranking order of the switchbacks changes, winner length 4454.96 → 4448.81 m, score 7.90 → 7.99 (development 2.28 → 2.36 from the longer accesses; no bonus, no coefficient) |
| IRREGULAR-REACH-EXCEEDED | CONSERVATIVE | 6 | 29 | same body as 301 with the reach screen exercised: same winner, same diffs |
| WARPED_VEIN-307 | CONSERVATIVE | 18 | 36 | **NO_FEASIBLE_CANDIDATE → SUCCESS**: 0 → 12 feasible of 92, winner SPIRAL-n1-CCW-e+0-g0.120 (L 3711.4 m, 9/9 serviceable levels, every access an RS connector 39–40 m, access-plan separations 36.5–38.0 m, excavation separations 15.3–17.1 m, conservative clearance 55.4 m) |

Every EXACT case is byte-identical, exactly as the TABULAR sanity (Gate B §5) and the inactive-reference contract require. The three CONSERVATIVE cases change only through geometry: the corridor moved outward by the measured delta and every downstream number (access lengths, separations, scores, ordering) was recomputed by the unchanged code — no access bonus, family bonus, recovery bonus or new weight (directive §21). Winner changes: none on 301 / IRREGULAR; 307 gains a winner because a corridor that keeps six widths from the level backbones gives the unchanged access planner junctions it can serve.

## 5. Census controlled comparison — `backend/golden/phase20c4_census_before_after.json`

The committed 20C.3A census (`phase20c3a_failure_census.json`, ORIGINAL baseline 7463c49) against the SAME script (`scripts/phase20c3a_failure_census.py`) on the SAME 13 NO_FEASIBLE seeds under the Gate C tree (`scripts/phase20c4_census_before_after.py`).

| seed | before | after | feasible after |
|---|---|---|---|
| 302 | NO_FEASIBLE | NO_FEASIBLE | 0 |
| 303 | NO_FEASIBLE | **SUCCESS** | 12 |
| 306 | NO_FEASIBLE | NO_FEASIBLE | 0 |
| 307 | NO_FEASIBLE | **SUCCESS** | 12 |
| 308 | NO_FEASIBLE | **SUCCESS** | 9 |
| 309 | NO_FEASIBLE | NO_FEASIBLE | 0 |
| 312 | NO_FEASIBLE | **SUCCESS** | 11 |
| 316 | NO_FEASIBLE | **SUCCESS** | 12 |
| 319 | NO_FEASIBLE | **SUCCESS** | 5 |
| 320 | NO_FEASIBLE | **SUCCESS** | 11 |
| 321 | NO_FEASIBLE | NO_FEASIBLE | 0 |
| 324 | NO_FEASIBLE | **SUCCESS** | 1 |
| 328 | NO_FEASIBLE | **SUCCESS** | 12 |

9 of 13 seeds flip to SUCCESS; 302, 306, 309, 321 stay NO_FEASIBLE with typed reasons.

| population | before (147 DETAILED) | after (146 DETAILED) |
|---|---|---|
| LEVEL_ACCESS_PROBLEM (the Gate A hypothesis population) | 76 | **0** |
| MULTI_CLUSTER_CLEARANCE | 37 | 6 |
| PORTAL_APPROACH | 22 | 42 |
| FIRST_LEG_GLOBAL_ABOVE_TERRAIN | 6 | 6 |
| LOCAL_REPAIR_GEOMETRY_RULE | 5 | 7 |
| PORTAL_ARTIFACT_ONLY | 1 | 0 |
| FEASIBLE | 0 | 85 |

Per-candidate transitions of the 147 baseline candidates: LEVEL_ACCESS_PROBLEM → FEASIBLE 17, → NOT_DETAILED 56 (displaced from the bounded shortlist by candidates that are now cheap-feasible and rank ahead — the shortlist bound is unchanged), → PORTAL_APPROACH 2, → LOCAL_REPAIR 1; MULTI_CLUSTER_CLEARANCE → FEASIBLE 6, → NOT_DETAILED 25, → PORTAL_APPROACH 5, → LOCAL_REPAIR 1; PORTAL_APPROACH → PORTAL_APPROACH 5, → NOT_DETAILED 17. 106 candidates are DETAILED only now (FEASIBLE 62, PORTAL_APPROACH 30, FIRST_LEG 6, MULTI_CLUSTER 4, LOCAL_REPAIR 4).

Reading. The Gate A population is gone as a population: no DETAILED candidate on any of the 13 seeds fails on level access any more, which is the causal prediction of Gate A (48–57 of 122 failed levels flipping under the counterfactuals) realized by the production planner under every unchanged gate. Population B (MULTI_CLUSTER, PARTIALLY_CONFIRMED) shrinks 37 → 6 — the near-leg clusters moved with the corridor, the far-leg / hairpin clusters the contract never addressed remain. The PORTAL_APPROACH count rises 22 → 42: a corridor that starts further from the ore changes the approach geometry, and more candidates now fail at construction with the typed APPROACH_INFEASIBLE reason (deprioritized secondary population, directive §22; these are typed construction failures, never silent, and the remaining NO_FEASIBLE seeds 302 / 306 / 309 / 321 are dominated by them). PHYSICALLY_LOCAL_REPAIRABLE is not re-derived (out of scope).

## 6. Gates

- ruff check / ruff format: clean on every changed backend file and script; mypy: `Success: no issues found in 99 source files`.
- New / changed tests: 12 passed across the two reference modules (slow cases included); unmarked layout modules (`test_layout_v2`, `test_level_access`, `test_layout_clearance_consistency`, `test_section_geometry`, not slow): 84 passed; golden smoke: TABULAR-REFERENCE, WARPED_VEIN-301, IRREGULAR-REACH-EXCEEDED, GEOMETRY-STRESS passed on the new baseline, `test_layout_v2_baseline_is_committed` passed.
- VA-01 tiers: see §8 (appended with the survey).

## 7. Hard stops re-checked after implementation

1–5 unchanged from Gate B. 6 (relaxing grade / clearance / radius / pillar): no — delta ≥ 0 only, every gate untouched. 7 (TABULAR shadow changes materially): no — four EXACT golden cases byte-identical. 8 (candidate-specific clearance provenance lost): no — `candidate_policy` reconstruction asserted in the dominance test. 9 (screen authority must change): no — untouched. 10 (broad family redesign): no — one lateral substitution per family (two lines in the switchback), the pair-band rule is a consumption rule, not a redesign.

MANUAL BROWSER ACCEPTANCE: NOT RUN (no UI change; the frontend reads no new field).
