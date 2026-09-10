# Phase 20C.4 — Gate C implementation and Gate D controlled comparison

Commits on `phase-20c4-access-reference-consistency` after the reviewed Gate A/B baseline (2df98f2): C0 67cea1f (F1), C1 31055db (`ServiceReference`), C2 c09978c (SPIRAL), C3 4ed0a35 (SWITCHBACK), C4/D (this closeout). Production files touched: `layout/reference.py` (new), `layout/families.py`, `layout/search.py`. Everything the directive lists as preserved is untouched: candidate enumeration, stage-2 screen semantics and authority, stage-3 ordering, stage-4 authority, the candidate-specific clearance policy, anchor trace-chainage semantics, every level-access hard gate, score coefficients, Effective Ramp ownership, shafts, MineNetwork, CapabilityGraph, and the frontend (which reads no new field). Design reference: `docs/algorithms.md` "Phase 20C.4"; rule 186 in `CLAUDE.md`.

## 1. What changed (one authoritative reference, two consumers)

`build_service_reference` (once per `LayoutV2Search.run`) collects, for every serviceable level, the interior of the WORLD-policy offset development trace at the world anchor stand-off — the cached trace stage 4 already builds for coarse anchors (token `"WORLD"`; `test_reference_reads_the_same_world_trace_stage_4_caches` proves no second clearance field exists). `families.corridor_profile` is the single consumer entry point; `build_spiral` and `build_switchback` add its `delta(z)` exactly where the track edge enters their corridor, so an inactive reference (TABULAR, explicit `footwallStandoff`) is bit-identical (`+0.0`). LONGITUDINAL is deferred unchanged.

| quantity | definition |
|---|---|
| footprint | ramp's OWN along-extent: SPIRAL rim `R` about the axis; SWITCHBACK `leg/2 + R_min` about the shared leg centre |
| support(L) | max `p·n` over reference points inside the footprint (empty ⇒ delta 0, never a fallback) |
| delta(L) | `max(0, support + 6·width − (footwall_edge(z_L)·n + standoff))`, piecewise-linear in z, constant beyond the levels |
| SWITCHBACK | *(925ce25 — superseded by §11)* pair-band maximum of delta (± 2 cycles) against the most ore-ward track edge in the band (a near leg at a pair start serves every level of its pair; the mid-pair near leg takes the smaller boundary lateral; the leg lags the edge drift, 2.9 m on 301 L04) |
| inactive | TABULAR analytic path, explicit stand-off, zero profile — `np.array_equal` against the reference-less build |

## 2. Gate C step 0 (F1) — `phase20c4_c0_f1.md`

Reading (b) does not hold: no ramp ↔ backbone crossing near a level plane and no excavation conflict (minimum 3-D distance 18.1 m ≥ 15 m). 322 L08 / L09 and 305 L12 were window artefacts (whole-trace fallback on an empty footprint; a window centred on a terminal hairpin over a 33° oblique backbone). 305 L05 / L07 are genuine encroachments of the leg-end hairpin on the level backbone (14.9 / 19.6 m plan) — the mechanism the contract corrects. SWITCHBACK entered Gate C under the two footprint refinements.

## 3. Tests at 925ce25 (all pass; the 307 cases are `slow`; the follow-up test set is in §11)

- `tests/test_service_reference.py` (8): profile semantics; TABULAR inactive + every family bit-identical; explicit stand-off keeps the legacy corridor; WARPED-301 active / deterministic / outward-only / empty-footprint-zero / payload; same cached WORLD traces; stage-4 dominance (REFINED candidate backbone never outward of the construction backbone beyond the section grid resolution, policy rebuilt through `candidate_policy`); band-max exactness against a brute-force grid; WARPED-307 SPIRAL delta > 0 on every level the rim runs alongside and the delivered helix is the corrected one.
- `tests/test_corridor_reference_integration.py` (4): 301 SPIRAL RL crossings ≥ support + 6 widths and moved by exactly the profile (one-sample tolerance), never inward; zero-profile candidates bit-identical, corrected ones keep their radius; 301 SWITCHBACK near legs clear every level plane within half an interval of their z-span and move outward cycle by cycle (legacy near legs 0.2 m from the backbone, corrected 33–48 m outward), R_min / leg spacing / nominal leg length untouched; WARPED-307 SPIRAL-n1-CW-e+0-g0.100 and SWITCHBACK-k1-p+0-CW-s50-g0.120 hold six widths at every RL crossing they run alongside — a SEPARATION regression, never a success-count assertion.
- Two `slow` fixture tests assumed WARPED-307 stays NO_FEASIBLE (`test_clearance_failure_detail_names_the_candidate_basis`, `test_shortlist_reconstruction_holds_on_a_conservative_case_with_failed_detailed`) and failed on the pushed Gate C head (CI "Backend" check and the local FULL run, 601 passed / 2 failed). No survey seed fails on OREBODY_CLEARANCE any more, and a larger exclusion buffer cannot produce one either (the corridor is placed relative to the certified clearance set). Both tests now exercise their property on the LEGACY corridor, which an explicit `layout.footwallStandoff` (the 50 m the default derives) preserves by contract (rule 186; reference inactive): 307 then reproduces its pre-20C.4 outcome exactly — NO_FEASIBLE, 12 of 12 shortlisted INFEASIBLE, 3 refined-basis clearance failures. The properties under test (failure detail names the candidate basis; shortlist reconstruction on a decisive conservative case) are unchanged.
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

## 8. Gate D — 32-seed controlled survey (`backend/golden/phase20c4_warped_seed_survey.json`, before/after `phase20c4_warped_seed_before_after.json`)

`python -m minegen.regression warped-seeds --label phase20c4_warped_seed_survey --out golden` (1461.4 s wall-clock, concurrent with the golden suite and the census re-run on the same 4-core machine; observation only) against the 20C.2A survey (`phase20c2a_warped_seed_survey.json`, the tree the 20C.3A census was taken on), compared with `scripts/phase20c4_survey_before_after.py`.

| quantity | before (20C.2A / 20C.3A tree) | after (Gate C tree) |
|---|---|---|
| layout SUCCESS | 19 / 32 | **28 / 32** |
| status flips | — | NO_FEASIBLE_CANDIDATE → SUCCESS 9 (303, 307, 308, 312, 316, 319, 320, 324, 328); SUCCESS → NO_FEASIBLE 0 |
| feasible DETAILED candidates (sum) | 104 | 283 |
| winner family | SPIRAL 1, SWITCHBACK 18 | SPIRAL 21, SWITCHBACK 7 |
| dominant failure histogram | ABOVE_TERRAIN 8, LEVEL_ACCESS_INFEASIBLE 21, OREBODY_CLEARANCE 3 | ABOVE_TERRAIN 15, TURN_RADIUS (cheap) 13, LEVEL_ACCESS_INFEASIBLE 3, LEG_TOO_SHORT 1 |
| level-access failure reasons (all DETAILED candidates) | GRADE_LIMIT 350, INSUFFICIENT_RAMP_PILLAR 96, TURNOUT_NOT_STRAIGHT 77, CONNECTOR_UNAVAILABLE 66 | GRADE_LIMIT 3, TURNOUT_NOT_STRAIGHT 6 |
| remaining NO_FEASIBLE | 13 | 302, 306, 309, 321 — dominant DETAILED:ABOVE_TERRAIN on every one (portal / first-leg approach population, out of scope, directive §22); 302 has only 2 DETAILED candidates (cheap WORLD_BOUNDS 36, TURN_RADIUS 21) |

Every one of the 32 seeds changed (0 identical): the reference is active on every WARPED scenario. Winner changes, reported as required (§21): the winner family flips SWITCHBACK → SPIRAL on 11 seeds (311, 314, 315, 318, 322, 323, 326, 327, 329, 331, 332); six seeds keep a SWITCHBACK winner with a different orientation / station (304, 305, 310, 313, 325, 330); the nine newly successful seeds all choose a SPIRAL; 301 keeps its SPIRAL. Two mechanisms, both geometric and both recomputed by unchanged scoring: (1) spirals that previously failed level access because their rim sat ≈ 7 m from the level backbones are now feasible and, being shorter than a corrected switchback stack, rank first; (2) a switchback consumes the pair-band MAXIMUM of delta, so its whole stack moves outward by the largest correction in a ± two-cycle band, which lengthens every access on the stack (the development term), while a spiral's axis moves only where a level needs it. No coefficient, weight, bonus or threshold changed. One seed loses feasible candidates (330: 10 → 7, still SUCCESS with a different switchback); every other seed keeps or gains.

The 20C.3A hypothesis population is closed: LEVEL_ACCESS_INFEASIBLE falls from the dominant failure on 21 seeds to 3 seeds' histograms, and the GRADE_LIMIT / INSUFFICIENT_RAMP_PILLAR / CONNECTOR_UNAVAILABLE / TURNOUT_NOT_STRAIGHT reasons fall from 589 to 9 level-access rejections in total. What remains is the portal / first-leg approach population (ABOVE_TERRAIN at the fixed start), which Phase 20C.4 never touched and which is the next diagnostic target — it grew as a share, and in absolute count on the census seeds (PORTAL_APPROACH 22 → 42), because a corridor that starts further from the ore changes the approach geometry.

## 9. VA-01 tiers

- FAST: PASS, 519 passed / 0 failed (head 4ed0a35 + C4 working tree).
- FEATURE: PASS, 524 passed / 0 failed (head 7ef6cea).
- FULL: recorded in §10 on the exact Gate D HEAD it ran on.

## 10. FULL (authoritative) — HEAD 44dcfa1

`python scripts/verify.py full` on 44dcfa1 (the two 307 fixture tests moved to the explicit-stand-off legacy corridor): **PASS in 1615.7 s** — ruff-check, ruff-format, mypy PASS; pytest-full 603 passed / 0 failed / 0 skipped (1572.0 s); fe-typecheck, fe-lint, fe-prettier, fe-vitest (263 passed in 40 files), fe-build PASS; collection coverage all = 603, full = 603, fast = 519; `fullAuthority = True`. The previous FULL on 1dfbba0 was 601 passed / 2 failed (the two fixture tests, §3), matching the CI "Backend" and "FULL backend" failures on the pushed Gate C head 7ef6cea. This section is the only change after 44dcfa1 (docs-only follow-up).

## 11. Follow-up (PR #28 closeout) — the SWITCHBACK consumption window, derived

Directive: derive the SWITCHBACK corridor's vertical consumption window from the
real pair geometry; the double ± 2·drop band of 925ce25 was undeclared.

### 11.1 What 925ce25 actually did, and what the stack actually does

At 925ce25 `build_switchback` consumed `corridor_profile(..., base_band_half =
2·drop)` — the track edge read at its most ore-ward point inside ± 2·drop of
each level — and then `DeltaProfile.band_max(2·drop)` on top — the running
maximum of delta over another ± 2·drop — i.e. up to ± 4·drop, and it folded
`delta(z_pair) − delta(z_a)` into the edge pair drift. Neither width was
derived. Before changing anything the stacking mechanics were verified on the
delivered 301 stacks (`scratchpad` debug, then the integration tests):

- Parity. `first_moves_away = (first_sense > 0) == right_is_away` decides whether
  cycle 0 is the NEAR leg (anchor = first near leg) or the FAR leg (anchor =
  far leg, `leg_lateral0 = standoff + 2·R + station`). 301
  SWITCHBACK-k1-p-20-CW-g0.120 is far-first.
- Drift composition. At every cycle start `z_a` the stack reads the pair drift
  `edge(z_a − 2·drop) − edge(z_a)` and enlarges ONLY the hairpin that bulges in
  the drift direction (never below R_min): outward drift through the hairpin
  after a NEAR leg, inward drift through the hairpin after a FAR leg. Composed
  over the stack: near-first → every near leg sits at the edge of its START
  elevation; far-first → the first near leg (starting at `z_join − drop`) is
  placed by the WHOLE first pair's drift and every near leg carries one cycle
  drop of edge lag (measured on 301 k1-p-20-CW: near leg [139.4, 157.6] at
  −44.86 m against the L03/L04 requirement −39.84 m — 4.98 m short — with the
  symmetric window alone; edge slope 0.196 × 25 m = 4.9 m).
- Folding delta into that composition loses any delta step that only one of the
  two interleaved pair phases sees: 301 SWITCHBACK-k2-p-20-CW-g0.120 delivered a
  near leg 1.47 m INWARD of the reference-less build (−126.35 vs −124.88 m) once
  the smoothing band was gone. The band-max had been doing smoothing duty for
  the composition, not only window duty.
- Last pair: `z_pair = max(z_a − 2·drop, z_last)` places the deepest near leg
  with the value at `z_last`, whose window holds the deepest level.
- Station (`arc–straight–arc`): changes the leg spacing and the horizontal cycle
  length, not the cycle drop — the window is station-independent.
- Chord descent: `Path.arc` descends per chord, so one pair descends up to
  `switchback_pair_descent_closure` (≈ 6 mm at 2 m sampling, supremum over
  R ≥ R_min evaluated exactly) less than its nominal 2·drop; the near leg starts
  at most that far ABOVE the nominal `z_pair` its delta is read at.

### 11.2 The fix (three derived pieces, no threshold, no coefficient)

1. **Exact delta consumption** (`build_switchback`): the anchor carries the
   first near leg's delta; at every near-leg cycle the step to the next near
   leg (`delta(z_pair) − delta_applied`) widens THIS away hairpin when outward
   and is carried into the NEXT toward hairpin when inward; the pair leg length
   pays `π·|step|/4` exactly as it pays the edge drift. A near leg starting at
   `z` therefore sits at `legacy_near(z) + delta(z)` whatever the pair phase;
   `delta ≡ 0` adds `0.0` to every radius and leg — bit-identical.
2. **One derived window** (`WindowRequirementProfile`, `layout/reference.py`):
   `W(z) = max{Q_L = support_L + margin : z_L ∈ [z − drop − dz/2, z + dz/2 + ε]}`
   — the level planes a near leg starting at `z` (span `[z − drop, z]`)
   occupies under nearest-plane attribution, `ε` the descent closure;
   `delta(z) = max(0, W(z) − base(z))`, empty window → 0, no requirement at any
   level → the exact zero profile.
3. **Parity edge term**: `base(z) = standoff + edge(z)·n` (near-first) or
   `standoff + min edge(z')·n over z' ∈ {z − drop, z, z + drop}` (far-first —
   the one-cycle lag of §11.1; the edge is linear in z so the ends suffice,
   and the minimum over both neighbours covers an inward- and an
   outward-drifting edge).

Removed: `corridor_profile(..., base_band_half)`, `DeltaProfile.band_max`,
`BandMaxProfile` and its test. SPIRAL path untouched (`corridor_profile` is
now the continuous-service profile only). Docs: rule 186, `docs/algorithms.md`
"Pair-window rule", the `reference.py` module docstring, and the derivation in
`switchback_corridor_profile`'s docstring.

### 11.3 Evidence — the "why that width" test was red on 925ce25

`tests/test_service_reference.py::test_switchback_window_is_the_pair_span_derived_from_the_leg_geometry`
(synthetic per-level requirements on the real 301 context, a linear synthetic
track edge, both parities; a requirement change outside the window never moves
the corridor at `z`, one inside does). Run FIRST against the 925ce25 logic
through a temporary wrapper reproducing it (`corridor_profile(...,
base_band_half = 2·drop)` then `band_max(2·drop)`) — the recorded run
(`scratchpad/f1_red_evidence_full.log`):

```
cd backend && .venv/bin/pytest "tests/test_service_reference.py::test_switchback_window_is_the_pair_span_derived_from_the_leg_geometry" -q -p no:cacheprovider -rA --disable-warnings
E           AssertionError: np.float64(132.43210872615703)
E           assert 0.3548572281846081 == 0.0 ± 1.0e-09
E             
E             comparison failed
E             Obtained: 0.3548572281846081
E             Expected: 0.0 ± 1.0e-09
FAILED tests/test_service_reference.py::test_switchback_window_is_the_pair_span_derived_from_the_leg_geometry
```

(the first sampled elevation, 132.43 m — above every level's window — already
carried 0.35 m of band-min edge correction). Green on the derived window;
green with both parities and the descent closure. New / changed tests:
`test_window_requirement_profile_semantics` (replaces the band-max test),
the pair-window test above, and in
`tests/test_corridor_reference_integration.py` the switchback stack test now
measures straight-leg runs with an exact heading test (a wide hairpin's last
chord was lifting the run's top by 0.2 m), the median lateral, and the
outward-only comparison allows exactly the edge shift between the two builds'
leg start elevations (the corrected join elevation moves with the corridor).
Every near leg of every constructed 301 SWITCHBACK still clears every level
plane within half an interval of its span by ≥ support + 6 widths − 1 m, every
hairpin ≥ R_min, leg spacing / nominal leg length unchanged.

### 11.4 Invariance

- TABULAR / explicit stand-off: `ZERO_PROFILE`, `np.array_equal` against the
  reference-less build (`test_tabular_reference_is_inactive_and_every_family_is_bit_identical`,
  `test_explicit_footwall_standoff_keeps_the_legacy_corridor`); the four EXACT
  golden cases (TABULAR-REFERENCE, GEOMETRY-STRESS, ACCESS-INFEASIBLE,
  CUT_AND_FILL) have byte-identical contract, metrics and candidates against
  both 925ce25 and 20C.2A.
- SPIRAL: unchanged by construction; measured on all 32 seeds — every SPIRAL
  candidate's `maxDelta` identical to 925ce25 (`spiralMaxAbsChange = 0.0` on
  every seed, `golden/phase20c4_followup_corridor_shift.json`); the 301 / 307 /
  IRREGULAR golden winners (all SPIRAL) keep identical length, access length,
  clearance and score.

### 11.5 Gate D re-run (same commands as §4/§5/§8, same 32 / 13 seeds)

Three time points (`golden/phase20c4_followup_three_point.json`,
`scripts/phase20c4_three_point_table.py`):

| metric | 20C.2A | 20C.4 (925ce25) | 20C.4 after |
|---|---|---|---|
| SUCCESS / 32 | 19 | 28 | 29 |
| level-access rejections (survey, all DETAILED candidates) | 589 | 9 | 11 (GRADE_LIMIT 3, TURNOUT_NOT_STRAIGHT 6, INSUFFICIENT_RAMP_PILLAR 2) |
| LEVEL_ACCESS_PROBLEM (census, 13 seeds) | 76 | 0 | 1 |
| multi-cluster clearance (census) | 37 | 6 | 7 |
| PORTAL_APPROACH (census) | 22 | 42 | 28 |
| FEASIBLE (census) | 0 | 85 | 94 |
| winner SWITCHBACK | 18 | 7 | 8 |
| winner SPIRAL | 1 | 21 | 21 |
| feasible DETAILED candidates (survey) | 104 | 283 | 296 |
| regressed seeds (vs previous column) | – | none | none |
| recovered seeds (vs previous column) | – | 303, 307, 308, 312, 316, 319, 320, 324, 328 | 309 |

Remaining NO_FEASIBLE: 302, 306, 321 (DETAILED:ABOVE_TERRAIN, the portal /
first-leg approach population). Census seeds now 10 / 13 SUCCESS (309: 0 → 2
feasible); the census re-run records one LEVEL_ACCESS_PROBLEM candidate
(307 SWITCHBACK-k1-p+0-CW-g0.100, newly DETAILED, LEVEL_ACCESS_INFEASIBLE — the
same candidate that flips FEASIBLE → INFEASIBLE in the 307 golden: a stack the
narrower window places closer to a level backbone fails typed in stage 4,
exactly the authority the contract keeps) and
PORTAL_APPROACH 42 → 28 (a stack that moves less far outward reaches its first
leg more often). Survey winner changes vs 925ce25 (all reported): 304, 310,
313, 330 keep a SWITCHBACK winner with the opposite turn sense (CW → CCW), 309
gains SWITCHBACK-k1-p-20-CCW-g0.120; every SPIRAL winner is unchanged.
Layout goldens (`golden/phase20c4_vs_20c2a_layout.json` regenerated,
`golden/phase20c4_followup_vs_925ce25_layout.json` new): 301 winner unchanged,
10 feasible (two SWITCHBACK ids swap between FEASIBLE and NOT_VALIDATED); 307
SUCCESS, 12 → 11 feasible (SWITCHBACK-k1-p+0-CW-g0.100 FEASIBLE → INFEASIBLE,
k1-p-20-CCW-g0.120 → FEASIBLE, five k2 stacks now shortlisted and INFEASIBLE);
IRREGULAR-REACH-EXCEEDED 10 feasible with three g0.100 stacks replacing three
g0.120 ones. Screen audit (`golden/phase20c4_screen_audit.json`): false blocks
40 (20C.2A) → 74 (301 29, 307 16, IRREGULAR 29), none inside the production
shortlist (20C.2A: 3); the conservative-side screen stays the documented rule
176 heuristic and the corrected stacks it under-predicts are served by stage 4.

Per-seed corridor shift (`golden/phase20c4_followup_corridor_shift.json`,
`scripts/phase20c4_corridor_shift.py` run under the 925ce25 worktree and the
follow-up tree, `scripts/phase20c4_corridor_shift_compare.py`; `movedLessBy` =
maxDelta(925ce25) − maxDelta(after) per constructed SWITCHBACK candidate, 975
candidates over 32 seeds): mean 15.3 m, median 12.3 m, max 50.7 m (310
SWITCHBACK-k1-p-20-CCW-g0.100); exactly one candidate moves MORE, by 0.08 m
(315 SWITCHBACK-k2-p+20-CW-g0.120, 2.90 → 2.98 m — the far-first edge term of
§11.2 on a stack the old band barely touched). SWITCHBACK winners after the
fix, `maxDelta` before → after: 304 86.9 → 45.1, 305 101.8 → 79.0,
309 96.5 → 60.5, 310 143.7 → 92.9, 313 88.4 → 44.7, 317 54.3 → 37.0,
325 86.5 → 64.9, 330 61.9 → 37.8 m. Per seed (mean / min / max over the
seed's SWITCHBACK candidates, m):

| seed | mean | min | max | seed | mean | min | max |
|---|---|---|---|---|---|---|---|
| 301 | 6.5 | 2.5 | 11.0 | 317 | 11.7 | 4.3 | 21.9 |
| 302 | 17.9 | 0.0 | 48.4 | 318 | 13.7 | 4.6 | 24.2 |
| 303 | 18.4 | 5.6 | 31.1 | 319 | 12.0 | 5.3 | 18.4 |
| 304 | 26.9 | 8.9 | 43.2 | 320 | 4.3 | 1.1 | 8.3 |
| 305 | 29.2 | 9.9 | 46.0 | 321 | 19.0 | 5.0 | 31.9 |
| 306 | 7.3 | 2.9 | 12.7 | 322 | 14.0 | 0.0 | 46.9 |
| 307 | 6.2 | 2.1 | 9.9 | 323 | 18.3 | 5.1 | 32.0 |
| 308 | 10.6 | 3.3 | 17.8 | 324 | 7.6 | 2.6 | 12.1 |
| 309 | 23.6 | 8.3 | 36.8 | 325 | 27.2 | 8.8 | 45.9 |
| 310 | 31.2 | 9.6 | 50.7 | 326 | 6.2 | 1.5 | 13.2 |
| 311 | 21.7 | 6.6 | 39.3 | 327 | 14.9 | 0.0 | 40.2 |
| 312 | 14.2 | 3.8 | 25.6 | 328 | 15.6 | 4.3 | 28.3 |
| 313 | 27.9 | 9.1 | 46.4 | 329 | 8.0 | 2.5 | 15.0 |
| 314 | 8.2 | 1.3 | 20.1 | 330 | 14.9 | 4.0 | 29.3 |
| 315 | 6.6 | -0.1 | 19.2 | 331 | 19.3 | 5.4 | 32.9 |
| 316 | 9.8 | 2.4 | 18.9 | 332 | 17.5 | 5.9 | 28.3 |

### 11.6 Gates (follow-up tree)

- FAST: PASS, 519 passed / 0 failed (head 925ce25 + follow-up working tree).
- FEATURE: PASS, 524 passed / 0 failed (head 925ce25 + follow-up working tree, clean canaries).
- Legacy 22-case golden (`python -m minegen.regression run --suite full` vs
  `golden/phase20b_closeout_full.json`): see §12.
- FULL: recorded in §12 on the exact HEAD it ran on (28e7033).

## 12. FULL (authoritative) — HEAD 28e7033 (follow-up)

`cd backend && python ../scripts/verify.py full` on 28e7033 (the follow-up
commit, clean tree): **PASS in 2027.9 s** — ruff-check, ruff-format, mypy
PASS; pytest-full **604 passed / 0 failed / 0 skipped** (1959.2 s, unfiltered;
603 on 44dcfa1 + the window-profile unit test, the band-max test replaced by the
pair-window test); fe-typecheck, fe-lint, fe-prettier, fe-vitest (263 passed),
fe-build PASS; collection coverage all = 604, full = 604, fast = 519;
`fullAuthority = True`, `gitDirty = False`
(`backend/.verification/verification-summary.json`). The same commit's FAST
(519 / 0) and FEATURE (524 / 0) ran on the identical tree before the commit.

Legacy 22-case golden (`cd backend && python -m minegen.regression run --suite
full --label phase20c4_followup_legacy --out <scratch>` on the follow-up tree,
then `python -m minegen.regression compare golden/phase20b_closeout_full.json
<scratch>/phase20c4_followup_legacy.json`): 22 cases compared, **HARD CONTRACT
regressions 0, metric changes 0 (expected 0, unexpected 0)**, no missing / new
cases; runtime 10509.2 → 10692.1 s (advisory; the run shared the CPU with FULL
and the Gate D re-run). The legacy Phase 03–10 chain does not read
`layout/families.py` or `layout/reference.py`.

