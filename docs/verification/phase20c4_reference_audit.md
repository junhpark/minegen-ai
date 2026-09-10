# Phase 20C.4 — Gate A Reference Audit (causal proof before fix)

Machine-readable artifact: `backend/golden/phase20c4_reference_audit.json` (HISTORICAL_DIAGNOSTIC, methodologyVersion 1). Baseline: `backend/golden/phase20c3a_failure_census.json` (ORIGINAL, main 7463c49); audit run on main 9d1a8bb. Production geometry was NOT changed; every measurement replays production code (LayoutV2Search, candidate_policy, _junction_candidates, _search_level, plan_level_accesses).

**Semantics.** Diagnostic artifact for the Phase 20C.4 decision gate. Not a golden target, not an optimization target; production geometry was NOT changed to produce it.

## Audited set

| role | seeds / candidates |
|---|---|
| Population A (LEVEL_ACCESS_PROBLEM) | seeds [307, 320, 328, 312] — 24 candidates (up to 6 per seed), 122 failed levels + 136 OK levels on the same candidates |
| Population B (MULTI_CLUSTER_CLEARANCE) | 26 candidates / 110 clusters on seeds [303, 308, 316, 324, 307, 320, 328, 312] (SPIRAL 4, SWITCHBACK 22) |
| Successful controls | WARPED 301 (SPIRAL winner), 305 (SWITCHBACK winner), 322 (SWITCHBACK winner), TABULAR BASELINE-42 (EXACT clearance) — winner + 2 feasible candidates each |

## Distance definitions (one coordinate system: backend X East / Y North / Z Up)

- **trackEdge** — FootwallTrack.footwall_edge(z): the GLOBAL linear track's footwall edge point at elevation z (plan); its true clearance is ≈ 0–5 m where the track fits the body
- **localContact** — FootwallTrace.contact_points of the level section (contains()-authoritative, grid resolution) — in-plane distance on the level plane
- **trueClearance** — orebody.approximate_clearance (WARPED, derived lattice EDT) / signed_distance (TABULAR) — 3-D distance to the solid
- **certifiedClearance** — the candidate's stage-4 ClearancePolicy.signed_clearance (COARSE/REFINED conservative: true − errorBound − discretization; EXACT: = true)
- **corridorRef** — family rule: footwall_edge(z) + n_hat·footwallStandoff (SPIRAL rim toward ore / SWITCHBACK near-leg centerline / LONGITUDINAL corridor) — the rule-170 corridor position at the level elevation
- **rampCrossing** — the delivered main ramp's first z-crossing of the level elevation
- **nearestRampInWindow** — closest delivered ramp sample to the anchor inside the junction elevation window [RL−10, RL+45] (plan distance and dz)
- **requiredRunAtGmax** — |dz| / max_gradient for the nearest approach; available run = its plan distance (a lower bound of the CS connector's horizontal length)
- **bindingCause** — per-level replay of the production junction lattice one junction at a time through _search_level (used=[] isolates junction spacing): SEPARATION_BOUND when every grade-feasible junction (planSep ≥ |dz|/g_max) is rejected by plan separation / rock pillar / connector availability

## Current contract

- **footwallTrackAuthority** — family construction + orientation (u_h, w_h, lateral drift) AND the corridor lateral reference (layout/families.py: footwall_edge(z) + standoff)
- **localFootwallTraceAuthority** — level-development anchors (rule 178 offset trace = certified-clearance level set at the anchor stand-off on the level plane, smoothed, re-validated)
- **corridorDerivation** — rule 170: footwallStandoff = footwall_access_offset + 6 × tunnel_width = 50 m from the GLOBAL track edge (true contact)
- **anchorDerivation** — rule 158/178: anchor stand-off 20 m (raised to required + errorBound + 1 under a conservative basis; 20.0 with the REFINED bound) measured on the CERTIFIED clearance field, i.e. from a surface that lies errorBound (+ trace smoothing bias) OUTSIDE the true contact
- **rule170PhysicalIntent** — main-ramp centerline's ore-facing nearest approach = level-development plane + two half-spans + a two-width rock pillar + a three-width turnout-taper allowance (spatial margins from the footwall footprint edge; docs/algorithms.md S1 table)
- **anchorStandoffPhysicalIntent** — level entry / development plane at footwall_access_offset from the footwall footprint edge (rule 43 line on TABULAR; the section's footwall-side extent on implicit bodies)
- **samePhysicalSpacingSystem** — YES — both are offsets from the footwall contact; the corridor default is DEFINED as the anchor plane + 6 widths

## Per-level reference measurements (medians per seed / family; metres)

| role | seed | basis | family | levels ok/failed | anchor→track edge (w_h) | anchor→local contact (in-plane) | anchor true clr | anchor certified clr | track edge true clr | corridorRef→anchor | corridorRef true clr | crossing→anchor | nearest ramp→anchor (window) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CONTROL | 42 | EXACT | SPIRAL | 39/0 | 21.3 | None | 20.0 | 20.0 | -0.0 | 29.0 | 47.0 | 29.0 | 28.8 |
| CONTROL | 301 | REFINED_CONSERVATIVE | SPIRAL | 42/0 | 19.8 | 37.7 | 37.3 | 26.5 | 18.0 | 34.5 | 53.1 | 34.8 | 33.5 |
| CONTROL | 305 | REFINED_CONSERVATIVE | SWITCHBACK | 33/0 | 48.1 | 53.4 | 37.0 | 26.3 | 7.3 | 159.9 | 36.1 | 101.8 | 67.5 |
| CONTROL | 322 | REFINED_CONSERVATIVE | SWITCHBACK | 21/0 | 48.8 | 55.8 | 36.8 | 26.0 | 2.0 | 288.6 | 32.4 | 125.6 | 98.7 |
| LA | 307 | REFINED_CONSERVATIVE | SPIRAL | 2/7 | 48.2 | 50.2 | 37.2 | 26.4 | 2.2 | 39.6 | 38.5 | 39.8 | 17.4 |
| LA | 307 | REFINED_CONSERVATIVE | SWITCHBACK | 20/25 | 48.5 | 49.9 | 37.1 | 26.3 | 2.2 | 36.5 | 35.9 | 19.5 | 8.2 |
| LA | 312 | REFINED_CONSERVATIVE | SWITCHBACK | 47/25 | 50.7 | 55.1 | 37.0 | 26.2 | -0.6 | 72.2 | 31.2 | 62.8 | 24.5 |
| LA | 320 | REFINED_CONSERVATIVE | SPIRAL | 1/10 | 48.7 | 49.0 | 37.0 | 26.3 | 2.8 | 19.1 | 38.0 | 76.8 | 3.4 |
| LA | 320 | REFINED_CONSERVATIVE | SWITCHBACK | 31/24 | 47.7 | 50.7 | 37.0 | 26.3 | 2.8 | 27.1 | 36.3 | 36.8 | 6.4 |
| LA | 328 | REFINED_CONSERVATIVE | SPIRAL | 0/11 | 42.8 | 48.4 | 37.1 | 26.3 | 2.4 | 13.6 | 34.3 | 13.0 | 4.7 |
| LA | 328 | REFINED_CONSERVATIVE | SWITCHBACK | 35/20 | 46.4 | 51.2 | 37.1 | 26.3 | 2.4 | 58.4 | 35.8 | 51.0 | 9.9 |
| MC | 303 | REFINED_CONSERVATIVE | SWITCHBACK | 37/23 | 56.0 | 57.3 | 37.0 | 26.3 | 5.4 | 63.4 | 33.8 | 36.1 | 16.4 |
| MC | 308 | REFINED_CONSERVATIVE | SWITCHBACK | 32/28 | 49.7 | 51.3 | 37.1 | 26.3 | 0.9 | 64.9 | 35.9 | 39.9 | 8.0 |
| MC | 316 | REFINED_CONSERVATIVE | SWITCHBACK | 29/19 | 50.1 | 53.4 | 37.1 | 26.3 | 5.1 | 57.3 | 35.9 | 38.7 | 9.1 |
| MC | 324 | REFINED_CONSERVATIVE | SPIRAL | 1/7 | 48.1 | 49.3 | 37.1 | 26.3 | 2.7 | 22.0 | 38.8 | 24.0 | 10.9 |
| MC | 324 | REFINED_CONSERVATIVE | SWITCHBACK | 9/15 | 47.9 | 49.3 | 37.1 | 26.3 | 2.7 | 41.2 | 36.2 | 40.2 | 11.7 |

Measured mismatch: anchor plane ≈ 37 m TRUE clearance (certified ≈ 26 m; 20 m stand-off on the certified level set + 10.8 m coarse bound + ≈ 6 m trace smoothing bias) while the corridor rim / near leg sits ≈ 32–39 m TRUE clearance (50 m from a track edge of 0–5 m true clearance, body leaning over the plane) — the two land on the same clearance shell, separation p50 7 m instead of the intended 30 m; TABULAR control: anchor 20 m, corridor rim 47 m, nearest approach 28.8 m, 39/39 OK; WARPED-301 control: track edge ≈ local contact, nearest approach 33.4 m, 42/42 OK

## Population A — LEVEL_ACCESS_PROBLEM

Binding cause of the 122 failed levels (grade-feasible junctions only): SEPARATION_BOUND 97, MIXED:INSUFFICIENT_RAMP_TO_ENTRY_SEPARATION,TURNOUT_NOT_STRAIGHT 5, MIXED:CONNECTOR_UNAVAILABLE,INSUFFICIENT_RAMP_TO_ENTRY_SEPARATION,TURNOUT_NOT_STRAIGHT 3, MIXED:INSUFFICIENT_RAMP_PILLAR,INSUFFICIENT_RAMP_TO_ENTRY_SEPARATION,TURNOUT_NOT_STRAIGHT 5, NO_GRADE_FEASIBLE_JUNCTION 1, MIXED:INSUFFICIENT_RAMP_PILLAR,TURNOUT_NOT_STRAIGHT 11.

Nearest ramp approach to the anchor: failed levels p10/p50/p90 = [1.4, 7.2, 16.6] m (≤ 20 m on 98%, max 27.6 m); OK levels on the same candidates are served by far junctions (selected connector p10/p50/p90 = [46.8, 77.7, 106.2] m).

Discriminator: nearest ramp approach to the anchor inside the junction window: failed levels p90 16.3 m / max 27.6 m; every control level ≥ 23.7 m (TABULAR 28.8 m by design = 30 m − plan effects; 301 p10 24.9 m; 305/322 ≥ 37 m). The 30 m B-1 value is NOT the discriminator (TABULAR sits at 28.8 m and is served from a junction 36 m away); the collapse to ≤ 20 m is.

### §7 per-reason decomposition

| reported reason | failed levels | binding SEPARATION_BOUND | binding mixed (separation + turnout) | no grade-feasible junction | nearest approach median (m) | analytic shared-reference prediction OK | classification |
|---|---|---|---|---|---|---|---|
| GRADE_LIMIT | 75 | 73 | 1 | 1 | 7.0 | 54/75 | **REFERENCE_CAUSED** |
| CONNECTOR_UNAVAILABLE | 20 | 10 | 10 | 0 | 9.8 | 19/20 | **REFERENCE_CONTRIBUTED** |
| INSUFFICIENT_RAMP_PILLAR | 25 | 12 | 13 | 0 | 6.8 | 13/25 | **REFERENCE_CONTRIBUTED** |
| TURNOUT_NOT_STRAIGHT | 2 | 2 | 0 | 0 | 2.4 | 2/2 | **REFERENCE_CAUSED** |

the reported label is the plurality of ALL lattice junction rejections (layout/access.py:1527); at the grade-feasible junctions the binding gates are plan separation / rock pillar / connector availability.

### Successful controls

| control | basis | levels | failed | nearest approach p10/p50/p90 (m) | min (m) | selected connector p10/p50/p90 (m) | anchor true / certified clearance (m) |
|---|---|---|---|---|---|---|---|
| TABULAR-42 | EXACT | 39 | 0 | [28.8, 28.8, 28.9] | 28.8 | [36.3, 37.5, 38.2] | 20.0 / 20.0 |
| WARPED-301 | REFINED_CONSERVATIVE | 42 | 0 | [24.9, 33.5, 41.8] | 23.7 | [34.7, 41.3, 49.8] | 37.3 / 26.5 |
| WARPED-305 | REFINED_CONSERVATIVE | 33 | 0 | [37.7, 67.5, 94.2] | 24.6 | [52.6, 107.8, 164.1] | 37.0 / 26.3 |
| WARPED-322 | REFINED_CONSERVATIVE | 21 | 0 | [63.9, 98.7, 120.4] | 53.8 | [96.3, 118.7, 160.4] | 36.8 / 26.0 |

Hard stop 4: NOT triggered — nearest approach ≤ 20 m on 98 % of failed levels and on 0 % of control levels (all served); the switchback controls 305/322 are served from the FAR leg with 108–119 m connectors (their near leg never comes within 37 m)

### Mandatory counterfactual (authoritative access planner, access hard gates retained; the shifted ramp is NOT re-validated)

| counterfactual | failed levels fixed | still failed | OK levels broken | access plans feasible (of 24 candidates) |
|---|---|---|---|---|
| CF-ANCHOR: anchor moved away from the nearest ramp approach to the rule-171 plan separation (30 m) | 57 | 65 | 19 | 3 |
| CF-RAMP: whole ramp rigidly shifted by the same deficit (corridor at the shared separation) | 48 | 74 | 4 | 6 |

restoring the plan separation at the nearest approach (anchor moved outward or ramp rigidly shifted) flips 48–57 of the 122 failed levels to OK with the access hard gates retained (plan_level_accesses re-run; the shifted ramp is not re-validated) and makes the access plan of 3–6 of 24 candidates feasible (access-plan feasibility, not candidate feasibility); the remainder do not flip because a rigid translation / anchor move is not the actual re-derivation (SPIRAL corridors need a re-derived radius/centre; anchors moved toward the ore hit the certified clearance floor 3.6–9.7 m < 10.59 m, so the ANCHOR cannot be the moving side)

| seed | candidate | baseline ok/failed | CF-ANCHOR ok/failed (moved, min certified clr) | CF-RAMP ok/failed (shift m, ramp clearance ok) |
|---|---|---|---|---|
| 307 | SPIRAL-n1-CW-e+0-g0.100 | 2/7 | 9/0 (9, 17.63) | 9/0 (12.64, True) |
| 307 | SWITCHBACK-k1-p+0-CW-s50-g0.120 | 4/5 | 4/5 (9, 6.74) | 4/5 (8.05, True) |
| 307 | SWITCHBACK-k1-p+20-CW-g0.120 | 4/5 | 5/4 (9, 19.16) | 3/6 (11.77, False) |
| 307 | SWITCHBACK-k1-p+20-CW-s50-g0.120 | 4/5 | 3/6 (9, 7.56) | 9/0 (22.91, True) |
| 307 | SWITCHBACK-k1-p+20-CW-s50-g0.100 | 4/5 | 8/1 (9, 9.74) | 9/0 (13.67, True) |
| 307 | SWITCHBACK-k1-p+20-CCW-g0.100 | 4/5 | 4/5 (5, 15.28) | 4/5 (13.91, True) |
| 320 | SPIRAL-n1-CCW-e+0-g0.100 | 1/10 | 1/10 (11, 5.92) | 1/10 (25.67, True) |
| 320 | SWITCHBACK-k1-p-20-CW-s50-g0.120 | 6/5 | 9/2 (11, 7.98) | 11/0 (18.93, True) |
| 320 | SWITCHBACK-k1-p-20-CW-s50-g0.100 | 6/5 | 7/4 (11, 9.45) | 9/2 (20.53, True) |
| 320 | SWITCHBACK-k1-p-20-CCW-g0.120 | 5/6 | 9/2 (10, 6.85) | 5/6 (8.55, False) |
| 320 | SWITCHBACK-k1-p-20-CCW-s50-g0.100 | 8/3 | 10/1 (10, 3.63) | 10/1 (7.84, True) |
| 320 | SWITCHBACK-k1-p+0-CW-g0.120 | 6/5 | 6/5 (11, 8.68) | 10/1 (22.01, True) |
| 328 | SPIRAL-n1-CW-e+45-g0.120 | 0/11 | 1/10 (11, 7.97) | 0/11 (22.51, False) |
| 328 | SWITCHBACK-k1-p-20-CW-s50-g0.100 | 10/1 | 10/1 (7, 7.77) | 11/0 (15.79, True) |
| 328 | SWITCHBACK-k1-p-20-CCW-g0.120 | 6/5 | 9/2 (6, 12.49) | 9/2 (25.17, True) |
| 328 | SWITCHBACK-k1-p+0-CW-g0.100 | 6/5 | 6/5 (11, 3.89) | 8/3 (14.85, True) |
| 328 | SWITCHBACK-k1-p+0-CW-s50-g0.120 | 6/5 | 9/2 (11, 6.72) | 6/5 (7.86, True) |
| 328 | SWITCHBACK-k1-p+0-CW-s50-g0.100 | 7/4 | 10/1 (11, 8.52) | 6/5 (4.43, True) |
| 312 | SWITCHBACK-k1-p-20-CW-s50-g0.100 | 10/2 | 8/4 (7, 6.91) | 11/1 (19.18, True) |
| 312 | SWITCHBACK-k1-p-20-CCW-g0.120 | 9/3 | 9/3 (5, 9.7) | 9/3 (22.97, True) |
| 312 | SWITCHBACK-k1-p-20-CCW-g0.100 | 7/5 | 7/5 (5, 16.54) | 7/5 (23.56, True) |
| 312 | SWITCHBACK-k1-p-20-CCW-s50-g0.120 | 8/4 | 12/0 (4, 20.99) | 11/1 (9.17, True) |
| 312 | SWITCHBACK-k1-p-20-CCW-s50-g0.100 | 7/5 | 12/0 (5, 16.29) | 12/0 (19.52, True) |
| 312 | SWITCHBACK-k1-p+0-CW-s50-g0.120 | 6/6 | 6/6 (12, 9.9) | 6/6 (20.93, False) |

**Population A verdict: CONFIRMED.**

## Population B — MULTI_CLUSTER_CLEARANCE

26 candidates / 110 clusters; fit rule: ≥ 90 % of cluster samples above the corridor-band p80 of the local-contact offset (distance-to-track-edge − true clearance) AND ≤ 25 % of non-cluster corridor samples above it. Fits: SPIRAL 4/4, SWITCHBACK 18/22. Worst-sample true clearance below required: 12 clusters; certified-only deficits: 98.

Mechanism: clusters sit where the LOCAL contact lies 40–107 m outside the GLOBAL track edge (in-cluster offset mean +38 … +107 m vs −4 … −22 m elsewhere on the corridor band); the sample's true clearance there is 14–21 m ≥ required 10.6 m in 98 of 110 clusters, so the deficit is a CERTIFIED (bound) deficit created by placing the corridor from the track edge instead of the local contact

| seed | candidate | family | error bound | clusters | true < required | local-contact offset in-cluster mean | outside-cluster corridor mean | cluster samples above p80 | non-cluster above p80 | fits | predicted removed if corridor from local contact |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 307 | SWITCHBACK-k1-p-20-CW-g0.120 | SWITCHBACK | 5.39 | 3 | 0 | 68.63 | -13.39 | 1.0 | 0.196 | YES | 3/3 |
| 307 | SWITCHBACK-k1-p-20-CCW-g0.120 | SWITCHBACK | 5.39 | 4 | 0 | 74.6 | -16.16 | 1.0 | 0.201 | YES | 4/4 |
| 307 | SWITCHBACK-k1-p+20-CW-g0.100 | SWITCHBACK | 5.39 | 4 | 0 | 62.19 | -15.91 | 1.0 | 0.199 | YES | 4/4 |
| 320 | SWITCHBACK-k1-p-20-CW-g0.100 | SWITCHBACK | 5.39 | 2 | 0 | 55.77 | -3.54 | 1.0 | 0.2 | YES | 2/2 |
| 320 | SWITCHBACK-k1-p+20-CCW-g0.100 | SWITCHBACK | 5.39 | 2 | 0 | 107.39 | -10.43 | 1.0 | 0.201 | YES | 2/2 |
| 328 | SWITCHBACK-k1-p+20-CW-g0.120 | SWITCHBACK | 5.39 | 3 | 1 | 73.14 | 0.04 | 1.0 | 0.2 | YES | 3/3 |
| 312 | SPIRAL-n1-CCW-e+45-g0.120 | SPIRAL | 5.39 | 5 | 0 | 39.8 | -6.3 | 1.0 | 0.12 | YES | 5/5 |
| 312 | SWITCHBACK-k1-p+20-CW-g0.100 | SWITCHBACK | 5.39 | 5 | 5 | 83.45 | -5.15 | 1.0 | 0.122 | YES | 5/5 |
| 312 | SWITCHBACK-k1-p+20-CW-s50-g0.120 | SWITCHBACK | 5.39 | 4 | 0 | 38.46 | -5.6 | 0.982 | 0.114 | YES | 4/4 |
| 312 | SWITCHBACK-k1-p+20-CW-s50-g0.100 | SWITCHBACK | 5.39 | 5 | 0 | 62.81 | -6.9 | 0.994 | 0.111 | YES | 5/5 |
| 303 | SPIRAL-n1-CCW-e+45-g0.120 | SPIRAL | 5.39 | 8 | 0 | 48.01 | -18.46 | 1.0 | 0.059 | YES | 8/8 |
| 303 | SWITCHBACK-k1-p+20-CW-g0.120 | SWITCHBACK | 5.39 | 4 | 0 | 51.58 | -18.27 | 0.961 | 0.05 | YES | 4/4 |
| 303 | SWITCHBACK-k1-p+20-CW-g0.100 | SWITCHBACK | 5.39 | 4 | 4 | 67.71 | -20.79 | 0.995 | 0.052 | YES | 4/4 |
| 308 | SPIRAL-n1.5-CCW-e-45-g0.100 | SPIRAL | 5.39 | 11 | 0 | 39.66 | -21.93 | 1.0 | 0.118 | YES | 11/11 |
| 308 | SWITCHBACK-k1-p-20-CW-g0.120 | SWITCHBACK | 5.39 | 4 | 0 | 70.78 | -16.21 | 1.0 | 0.177 | YES | 4/4 |
| 308 | SWITCHBACK-k1-p-20-CCW-g0.120 | SWITCHBACK | 5.39 | 5 | 0 | 82.33 | -20.36 | 1.0 | 0.202 | YES | 5/5 |
| 316 | SPIRAL-n1-CW-e+45-g0.120 | SPIRAL | 5.39 | 3 | 0 | 46.51 | -15.04 | 1.0 | 0.164 | YES | 3/3 |
| 316 | SWITCHBACK-k1-p+20-CW-g0.120 | SWITCHBACK | 5.39 | 3 | 1 | 80.13 | -14.3 | 1.0 | 0.175 | YES | 3/3 |
| 316 | SWITCHBACK-k1-p+20-CW-s50-g0.120 | SWITCHBACK | 5.39 | 2 | 0 | 59.02 | -17.18 | 1.0 | 0.168 | YES | 2/2 |
| 316 | SWITCHBACK-k1-p+20-CW-s50-g0.100 | SWITCHBACK | 5.39 | 3 | 1 | 77.72 | -16.0 | 1.0 | 0.179 | YES | 3/3 |
| 316 | SWITCHBACK-k1-p+20-CCW-g0.100 | SWITCHBACK | 5.39 | 2 | 0 | 96.62 | -20.7 | 1.0 | 0.2 | YES | 2/2 |
| 324 | SWITCHBACK-k1-p-20-CW-g0.100 | SWITCHBACK | 5.39 | 5 | 0 | -26.65 | -26.75 | 0.5 | 0.202 | NO | 5/5 |
| 324 | SWITCHBACK-k1-p-20-CCW-g0.100 | SWITCHBACK | 5.39 | 5 | 0 | 4.54 | -31.56 | 0.707 | 0.201 | NO | 5/5 |
| 324 | SWITCHBACK-k1-p+20-CW-g0.120 | SWITCHBACK | 5.39 | 4 | 0 | 60.48 | -31.07 | 1.0 | 0.183 | YES | 4/4 |
| 324 | SWITCHBACK-k1-p+20-CW-g0.100 | SWITCHBACK | 5.39 | 5 | 0 | 2.02 | -31.03 | 0.673 | 0.19 | NO | 5/5 |
| 324 | SWITCHBACK-k1-p+20-CCW-g0.100 | SWITCHBACK | 5.39 | 5 | 0 | 0.16 | -37.14 | 0.637 | 0.201 | NO | 5/5 |

Non-fitting: SWITCHBACK-k1-p-20-CW-g0.100, SWITCHBACK-k1-p-20-CCW-g0.100, SWITCHBACK-k1-p+20-CW-g0.100, SWITCHBACK-k1-p+20-CCW-g0.100 — seed 324 SWITCHBACK ×4: clusters include samples with strongly NEGATIVE local offset (−150 m, far-leg / hairpin regions far from the footwall) — a different mechanism (far-leg proximity to the hanging-wall side / body thickness), left unresolved

**Population B verdict: PARTIALLY_CONFIRMED.**

## Engineering intent check (Gate B entry)

Rule 170 and the anchor stand-off describe the same physical spacing system: **YES** — rule 170 default = footwall_access_offset + RAMP_CORRIDOR_MARGIN_WIDTHS × width, i.e. the anchor plane plus explicit spatial margins; both cite the footwall footprint edge (docs/algorithms.md S1 table rows footwall_access_offset / footwall_standoff / anchor_standoff).

## TABULAR shadow sanity

Old / new proposed reference equivalent: **YES (analytic; numerical shadow to be recorded in Gate B)** — on TABULAR (EXACT) certified = true, the track edge IS the analytic footwall line and the anchor sits 20.0 m from it (measured true = certified = 20.0); a corridor derived from the same certified field at anchor stand-off + 6 widths reproduces footwall_edge(z) + 50 m — measured corridorRef→anchor 29.0 m, nearest approach 28.8 m.

## Single-source contract proposal

- **authoritativeSource** — candidate-policy certified clearance field (ClearancePolicy.signed_clearance) on the level plane — the SAME field the rule-178 offset trace already uses
- **sharedAbstraction** — ServiceReference: per level, the certified level set at the anchor stand-off (existing OffsetTrace) → anchor; the same level set at (anchor stand-off + RAMP_CORRIDOR_MARGIN_WIDTHS × width) along the local outward normal → corridor reference point; interpolated across elevations for family construction
- **footwallTrackFutureRole** — family construction / orientation (u_h, w_h, lateral drift, hairpin stacking) only; no longer the corridor's lateral authority on implicit bodies; on TABULAR the two coincide
- **corridorDerivation** — families place the ore-facing corridor at ServiceReference.corridor(z) instead of track.footwall_edge(z) + standoff
- **anchorDerivation** — unchanged (rule 178 offset trace)
- **errorBoundTreatment** — unchanged and applied ONCE — both consumers read the same certified field; no '+ errorBound + traceBias' correction is added to the corridor
- **stageConstraint** — stage-1 construction only has the WORLD (coarse) policy while stage-4 anchors may use the candidate's REFINED policy; the corridor derived on the coarse field is further out than an anchor derived on the refined field, so the separation can only be ≥ the intended value — conservative direction, to be documented
- **expectedModulesAffected** — layout/families.py (corridor placement), layout/search.py (shared reference construction, LayoutContext), layout/levels.py or layout/sections.py (ServiceReference helper reusing offset_trace), tests/ (reference determinism, TABULAR equivalence, WARPED local reference, GRADE_LIMIT / PILLAR causal regressions)
- **portalApproach** — DEFERRED (28-candidate analytical population preserved)

## Unresolved mechanisms

- Population B: 4 of 26 candidates (seed 324 SWITCHBACK) with negative local offsets
- Population A: levels whose binding cause mixes TURNOUT_NOT_STRAIGHT with separation (16 of 122) — turnout curvature is family geometry, not a reference issue
- counterfactuals are proxies (rigid ramp shift / anchor move), not the re-derived corridor

## Recommendation

**PROCEED (Gate B single-source contract; Population A CONFIRMED, Population B PARTIALLY_CONFIRMED — implement the shared reference for the corridor and measure B in Gate D without assuming it)**

DO NOT IMPLEMENT PRODUCTION GEOMETRY UNTIL THIS GATE IS REVIEWED.
