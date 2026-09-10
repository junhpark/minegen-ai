# Phase 20C.3A — Failure Locality Census (historical diagnostic baseline)

Machine-readable artifact: `backend/golden/phase20c3a_failure_census.json` (censusType **ORIGINAL**, methodologyVersion 1, baseline `main` 7463c49). Script: `scripts/phase20c3a_failure_census.py (diagnostic, not production)`.

**Semantics.** Historical diagnostic baseline of the Phase 20C.3A failure locality census. NOT an optimization target, NOT a required golden outcome, NOT a threshold to preserve; the failure populations are allowed to change in Phase 20C.4. It records why bounded local repair was deferred; it is architecture-decision evidence, not a golden expectation (no regression test consumes it and no comparison is run against it).

## Provenance

| | |
|---|---|
| baseline git SHA | `7463c49086dd98536e80f6654412db148bea5328` |
| source survey | `backend/golden/phase20c2a_warped_seed_survey.json` (gitHead `422cfd3`, 19 SUCCESS / 13 NO_FEASIBLE) |
| seed range | 301–332 (32 seeds, RANDOM_WARPED_VEIN, faultCount 1) |
| seeds re-run for the census | 302, 303, 306, 307, 308, 309, 312, 316, 319, 320, 321, 324, 328 (the 13 NO_FEASIBLE seeds; the 19 SUCCESS seeds are carried from the survey) |
| census executed | 2026-09-09, 351.1 s search + localization |
| production code changes | 0 |

## Method

- **search** — production LayoutV2Search.run() on RANDOM_WARPED_VEIN scenarios realized from the fixed seed list (same call chain as the 32-seed survey); nothing tuned, no production change
- **localization** — in-memory per-sample validity of validate_delivered_centerline (valid_mask, points, per-sample rejection reasons) plus orebody_distance < required clearance, evaluated under each DETAILED candidate's own stage-4 clearance policy rebuilt by LayoutV2Search.candidate_policy; production artifacts persist counts only, so the census re-ran the search instead of reading layout_v2.json
- **clusterRule** — contiguous failing samples; runs merged when the chainage gap ≤ shoulder = 2·R_min = 36 m (R_min = 18 m, sample spacing 2 m)
- **classificationRule** — LEVEL_ACCESS_PROBLEM: main ramp valid, access plan infeasible. PORTAL_ARTIFACT: cluster at chainage ≤ 12 m, ABOVE_TERRAIN only, ≤ 0.3 m above terrain, span ≤ 10 m (excluded before counting clusters). MULTI_CLUSTER_CLEARANCE: ≥ 2 clusters. PORTAL_APPROACH: single cluster touching the fixed start with ABOVE_TERRAIN. FIRST_LEG_GLOBAL_ABOVE_TERRAIN: single interior cluster with span > 4·R_min = 72 m. LOCAL_REPAIR_GEOMETRY_RULE: single interior cluster, span ≤ 4·R_min, ≥ one shoulder from both endpoints. PHYSICALLY_LOCAL_REPAIRABLE: LOCAL candidates whose defect can be removed inside the window without relaxing any constraint (ABOVE_TERRAIN: extra depth (g_max − g)·shoulder ≥ needed; clearance: lateral micro-shift)
- **localityRuleStatus** — EXPLORATORY_LOCALITY_CLASSIFIER — not a production engineering contract; the 2R / 4R / 1R derivation has not been verified against the motion-primitive construction and is not to be promoted while local repair stays deferred

## Summary

| | |
|---|---|
| 32-seed baseline | 19 SUCCESS / 13 NO_FEASIBLE |
| DETAILED candidates inspected | 147 |
| INSUFFICIENT_DIAGNOSTICS | 0 |
| expected seed recovery from one-window local repair | 0–1 of 13 |

### Raw populations (stored separately; they are NOT summed into a confirmed cause)

| population | candidates |
|---|---|
| LEVEL_ACCESS_PROBLEM | 76 |
| MULTI_CLUSTER_CLEARANCE | 37 |
| PORTAL_APPROACH | 22 |
| FIRST_LEG_GLOBAL_ABOVE_TERRAIN | 6 |
| LOCAL_REPAIR_GEOMETRY_RULE | 5 |
| PHYSICALLY_LOCAL_REPAIRABLE | 3 |
| PORTAL_ARTIFACT_ONLY | 1 |

LEVEL_ACCESS_PROBLEM + MULTI_CLUSTER_CLEARANCE + PORTAL_APPROACH + FIRST_LEG_GLOBAL_ABOVE_TERRAIN + LOCAL_REPAIR_GEOMETRY_RULE + PORTAL_ARTIFACT_ONLY = 147; PHYSICALLY_LOCAL_REPAIRABLE ⊂ LOCAL_REPAIR_GEOMETRY_RULE.

### Investigation populations

| population | count | composition | status |
|---|---|---|---|
| referenceConsistencyInvestigationPopulation | 113 | LEVEL_ACCESS_PROBLEM 76 + MULTI_CLUSTER_CLEARANCE 37 | HYPOTHESIS_NOT_YET_CAUSALLY_CONFIRMED |
| portalFamilyApproachInvestigationPopulation | 28 | PORTAL_APPROACH 22 + FIRST_LEG_GLOBAL_ABOVE_TERRAIN 6 | ANALYTICAL_GROUPING |

NOT a confirmed common-cause population. Hypothesis: main-ramp corridor placed from the global footwall TRACK edge vs level anchors placed from the section / conservative-clearance offset trace (seed 307: anchors 46–50 m from the track edge, corridor 50 m). To be tested by the Phase 20C.4 Gate A counterfactual audit.

analysis grouping of the two portal-side ABOVE_TERRAIN classes; not a confirmed single mechanism

### Locality-rule sensitivity

LOCAL count under max span ≤ 2R / 4R / 8R: 3 / 5 / 9. single-interior-cluster candidates counted LOCAL under each span rule; the 8R additions are seed-306 first-leg ABOVE_TERRAIN runs 84–120 m long, 2.5–7.1 m above ground, all grade-limited.

### Level-access failures

76 candidates with a fully valid main ramp, 363 failed required levels: GRADE_LIMIT 208, CONNECTOR_UNAVAILABLE 57, INSUFFICIENT_RAMP_PILLAR 56, TURNOUT_NOT_STRAIGHT 42.

## Per seed

| seed | result | detailed | feasible | LEVEL_ACCESS | MULTI_CLUSTER | PORTAL_APPROACH | FIRST_LEG | LOCAL | artifact-only |
|---|---|---|---|---|---|---|---|---|---|
| 301 | SUCCESS | 12 | 10 | — | — | — | — | — | — |
| 302 | NO_FEASIBLE | 3 | 0 |  | 1 | 2 |  |  |  |
| 303 | NO_FEASIBLE | 12 | 0 | 9 | 3 |  |  |  |  |
| 304 | SUCCESS | 12 | 6 | — | — | — | — | — | — |
| 305 | SUCCESS | 12 | 5 | — | — | — | — | — | — |
| 306 | NO_FEASIBLE | 12 | 0 | 1 | 3 | 1 | 6 | 1 |  |
| 307 | NO_FEASIBLE | 12 | 0 | 9 | 3 |  |  |  |  |
| 308 | NO_FEASIBLE | 12 | 0 | 7 | 3 |  |  | 2 |  |
| 309 | NO_FEASIBLE | 12 | 0 | 3 | 5 | 4 |  |  |  |
| 310 | SUCCESS | 12 | 5 | — | — | — | — | — | — |
| 311 | SUCCESS | 12 | 9 | — | — | — | — | — | — |
| 312 | NO_FEASIBLE | 12 | 0 | 8 | 4 |  |  |  |  |
| 313 | SUCCESS | 12 | 1 | — | — | — | — | — | — |
| 314 | SUCCESS | 12 | 5 | — | — | — | — | — | — |
| 315 | SUCCESS | 12 | 7 | — | — | — | — | — | — |
| 316 | NO_FEASIBLE | 12 | 0 | 7 | 5 |  |  |  |  |
| 317 | SUCCESS | 12 | 2 | — | — | — | — | — | — |
| 318 | SUCCESS | 12 | 3 | — | — | — | — | — | — |
| 319 | NO_FEASIBLE | 12 | 0 | 7 |  | 4 |  |  | 1 |
| 320 | NO_FEASIBLE | 12 | 0 | 10 | 2 |  |  |  |  |
| 321 | NO_FEASIBLE | 12 | 0 |  | 2 | 10 |  |  |  |
| 322 | SUCCESS | 12 | 11 | — | — | — | — | — | — |
| 323 | SUCCESS | 12 | 2 | — | — | — | — | — | — |
| 324 | NO_FEASIBLE | 12 | 0 | 4 | 5 | 1 |  | 2 |  |
| 325 | SUCCESS | 12 | 5 | — | — | — | — | — | — |
| 326 | SUCCESS | 12 | 1 | — | — | — | — | — | — |
| 327 | SUCCESS | 12 | 10 | — | — | — | — | — | — |
| 328 | NO_FEASIBLE | 12 | 0 | 11 | 1 |  |  |  |  |
| 329 | SUCCESS | 12 | 4 | — | — | — | — | — | — |
| 330 | SUCCESS | 12 | 10 | — | — | — | — | — | — |
| 331 | SUCCESS | 12 | 6 | — | — | — | — | — | — |
| 332 | SUCCESS | 12 | 2 | — | — | — | — | — | — |

## LOCAL_REPAIR_GEOMETRY_RULE candidates (5) and the physical verdict

| seed | candidate | defect | chainage | span (m) | physically repairable in one window | verdict |
|---|---|---|---|---|---|---|
| 306 | SWITCHBACK-k1-p-20-CCW-s50-g0.120 | ABOVE_TERRAIN (above terrain 1.32 m, clearance deficit 0.0 m) | 140–187 | 46.5 | NO | grade-limited: g = g_max, zero vertical slack |
| 308 | SWITCHBACK-k2-p-20-CCW-g0.100 | CLEARANCE_BELOW_REQUIRED (above terrain — m, clearance deficit 0.04 m) | 4650–4652 | 2.0 | YES | lateral micro-shift of 0.04 m over 2.0 m |
| 308 | SWITCHBACK-k2-p+20-CW-g0.100 | ABOVE_TERRAIN (above terrain 0.35 m, clearance deficit 0.0 m) | 260–284 | 24.0 | YES | vertical fix feasible inside the window: needs shoulder 18 m = 1.0 R ≤ 2 R |
| 324 | SWITCHBACK-k1-p-20-CW-s50-g0.100 | ABOVE_TERRAIN (above terrain 3.16 m, clearance deficit 0.0 m) | 102–163 | 61.8 | NO | grade-limited: needs shoulder 158 m = 8.8 R > 2 R |
| 324 | SWITCHBACK-k1-p-20-CCW-g0.120 | CLEARANCE_BELOW_REQUIRED (above terrain — m, clearance deficit 0.03 m) | 2323–2323 | 0.0 | YES | lateral micro-shift of 0.03 m over 0.0 m |

## Decision record

| item | decision |
|---|---|
| Phase 20C.3A | PASS / COMPLETE |
| Bounded local repair (20C.3B) | **DEFERRED** |
| production code changes | 0 |

Rationale:

- 3 / 147 candidates were judged physically local-repairable.
- Expected seed recovery was approximately 0–1.
- Current Hybrid A* does not constrain terminal heading.
- Current smoothing cannot preserve the geometry outside a bounded repair interval without architectural redesign.
- The dominant measured populations instead concern level access, repeated clearance, and portal/family approach geometry.

Architecture feasibility (repo reality review, `design/astar_3d.py`, `design/smoothing.py`, `layout/search.py`):

- fixedStartPosition: YES
- fixedEndPosition: YES
- initialHeadingConstraint: YES
- terminalHeadingConstraint: NO
- boundedSearchDomain: NO
- localSmoothingPreservesOutsideGeometry: NO
- candidateSpecificClearancePreserved: YES (refined window built around the original points; outside it the coarse bound applies)

Next phase: 20C.4 Level-Access Reference Consistency & Corridor/Anchor Alignment — Gate A reference-frame audit / causal proof → Gate B single-source geometry contract → Gate C implementation → 32-seed controlled comparison; no corridor move or stand-off change before Gate A.

## Reproduction

```
backend/.venv/bin/python scripts/phase20c3a_failure_census.py 302,303,306,307,308,309,312,316,319,320,321,324,328 /tmp/census.json
```

The raw per-candidate output is deterministic for a given `main` SHA; a re-run on a later `main` is a NEW census (Phase 20C.4 is expected to change the populations) and must not be compared against this file as a regression.
