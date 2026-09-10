# Phase 20C.4 — Gate B: Engineering Intent + Single-Source ServiceReference Contract

Diagnostic artifact: `backend/golden/phase20c4_gate_b_shadow.json` (methodologyVersion 2, candidate-exact shadow on main efecf00; production change 0). Scripts: `scripts/phase20c4_shadow_20c4b.py` (candidate-exact), `scripts/phase20c4_shadow_check_20c4b.py` (first-pass direct check), `scripts/phase20c4_time_traces_20c4b.py`. This document is the Gate B architecture decision; implementation waits for Gate C approval.

## 1. Engineering intent check

- **What physical surface does rule 170 offset the ramp service corridor from?** The footwall footprint edge (the ore contact on the footwall side), by `footwall_access_offset + RAMP_CORRIDOR_MARGIN_WIDTHS × tunnel_width` — the level-development plane plus two half-spans, a two-width rock pillar and a three-width turnout-taper allowance (`docs/algorithms.md` S1 table, `layout/families.py::effective_footwall_standoff`).
- **What physical surface does the 20C.2A anchor stand-off offset from?** The same footwall contact: `footwall_access_offset` from the footwall footprint edge (rule 43 line on TABULAR); on implicit bodies measured on the certified-clearance field (rule 178 offset trace), raised under a conservative basis (rule 158).
- **Same physical spacing system? YES.** The corridor default is defined as the anchor plane plus explicit spatial margins. Only the implementation reference differs: the corridor reads the GLOBAL linear `FootwallTrack` edge (per-level fit of `centroid + w_h·extent` — true contact; residual 0.02–0.39 m on TABULAR-42 but 1–68 m per level on WARPED seeds), the anchor reads the CERTIFIED clearance level set (error-bound + trace-smoothing bias outside the true contact). → PROCEED to a shared reference contract (§11).

## 2. Candidate-exact shadow (every constructed SPIRAL / SWITCHBACK candidate, its own g / n / k / station / orientation, delivered polyline)

δ_int = outward corridor move (m) restoring 6 widths between the delivered ore-facing corridor and every WORLD-policy anchor-backbone point inside the candidate's own footprint, over the backbone INTERIOR (end margins excluded as for the anchor admissible range) — the contract quantity. Per seed, per family and stage-4 status: median of candidate medians / max of candidate maxima (candidates with median δ_int > 1 m / total). The full-trace δ (end margins included) is kept in the JSON; where a strike-end wrap inflates it the difference is discussed below.

| seed | status | SPIRAL/FEASIBLE | SPIRAL/INFEASIBLE | SPIRAL/NOT_VALIDATED | SWITCHBACK/FEASIBLE | SWITCHBACK/INFEASIBLE | SWITCHBACK/NOT_VALIDATED | winner δ_int median / max |
|---|---|---|---|---|---|---|---|---|
| 42 | SUCCESS | — | — | — | — | — | — | 0.0 / 0.0 (TABULAR, analytic path) |
| 301 | SUCCESS | 7.49 / 11.65 (3/3) | 74.18 / 113.04 (15/15) | 80.89 / 121.94 (12/12) | 18.75 / 125.98 (7/7) | 16.45 / 40.13 (2/2) | 20.13 / 98.53 (25/27) | 7.49 / 11.35 (SPIRAL; full-trace 7.49 / 11.35) |
| 305 | SUCCESS | — | 117.0 / 162.94 (26/26) | 124.39 / 156.9 (4/4) | 0.0 / 32.75 (1/5) | 21.81 / 110.49 (6/6) | 46.73 / 114.35 (23/25) | 0.0 / 29.47 (SWITCHBACK; full-trace 0.0 / 29.47) |
| 307 | NO_FEASIBLE | — | 102.93 / 129.38 (11/11) | 102.64 / 123.39 (19/19) | — | 61.41 / 97.26 (11/11) | 41.4 / 97.91 (25/25) | — |
| 320 | NO_FEASIBLE | — | 98.1 / 117.19 (8/8) | 101.42 / 126.14 (22/22) | — | 38.47 / 91.55 (11/11) | 44.34 / 99.69 (25/25) | — |
| 328 | NO_FEASIBLE | — | 88.84 / 134.62 (14/14) | 91.91 / 139.71 (16/16) | — | 39.89 / 93.54 (11/11) | 44.45 / 106.34 (25/25) | — |
| 312 | NO_FEASIBLE | — | 99.84 / 116.0 (20/20) | 103.24 / 120.61 (10/10) | — | 39.68 / 90.53 (11/11) | 40.18 / 93.6 (25/25) | — |
| 303 | NO_FEASIBLE | — | 112.02 / 147.58 (22/22) | 79.18 / 137.73 (8/8) | — | 47.51 / 113.97 (11/11) | 35.61 / 103.24 (25/25) | — |
| 322 | SUCCESS | — | 104.16 / 141.09 (27/27) | 118.55 / 137.18 (3/3) | 0.0 / 122.17 (0/11) | 91.25 / 166.23 (2/2) | 40.75 / 157.0 (22/23) | 0.0 / 112.24 (SWITCHBACK; full-trace 0.0 / 112.24) |

TABULAR-42: δ ≡ 0 on every candidate by contract (analytic path). Per-candidate and per-level rows, the delivered near-leg lateral, the stage-4 anchor separation where the candidate reached stage 4, footprint parameters and trace-point counts are in the JSON.

### Winners of the successful seeds, per level (delivered near-leg / rim lateral vs the interior backbone support; metres)

| seed | winner | level | delivered near lateral | formula error | stage-4 anchor separation | backbone separation (interior) | δ_int | δ (full trace) |
|---|---|---|---|---|---|---|---|---|
| 301 | SPIRAL-n1-CW-e+0-g0.120 | L03 | -29.44 | -0.01 | 26.3 | 20.28 | 9.72 | 9.72 |
| 301 | SPIRAL-n1-CW-e+0-g0.120 | L04 | -34.94 | -0.01 | 23.58 | 18.65 | 11.35 | 11.35 |
| 301 | SPIRAL-n1-CW-e+0-g0.120 | L05 | -40.44 | -0.0 | 23.64 | 19.22 | 10.78 | 10.78 |
| 301 | SPIRAL-n1-CW-e+0-g0.120 | L06 | -45.95 | -0.01 | 24.85 | 20.6 | 9.4 | 9.4 |
| 301 | SPIRAL-n1-CW-e+0-g0.120 | L07 | -51.46 | -0.02 | 25.84 | 21.84 | 8.16 | 8.16 |
| 301 | SPIRAL-n1-CW-e+0-g0.120 | L08 | -56.96 | -0.02 | 27.49 | 22.05 | 7.95 | 7.95 |
| 301 | SPIRAL-n1-CW-e+0-g0.120 | L09 | -62.46 | -0.02 | 29.16 | 22.36 | 7.64 | 7.64 |
| 301 | SPIRAL-n1-CW-e+0-g0.120 | L10 | -67.96 | -0.02 | 30.88 | 22.65 | 7.35 | 7.35 |
| 301 | SPIRAL-n1-CW-e+0-g0.120 | L11 | -73.46 | -0.01 | 32.22 | 23.44 | 6.56 | 6.56 |
| 301 | SPIRAL-n1-CW-e+0-g0.120 | L12 | -78.97 | -0.02 | 33.45 | 24.05 | 5.95 | 5.95 |
| 301 | SPIRAL-n1-CW-e+0-g0.120 | L13 | -84.48 | -0.03 | 34.52 | 24.76 | 5.24 | 5.24 |
| 301 | SPIRAL-n1-CW-e+0-g0.120 | L14 | -89.99 | -0.03 | 34.94 | 25.37 | 4.63 | 4.63 |
| 301 | SPIRAL-n1-CW-e+0-g0.120 | L15 | -95.49 | -0.03 | 35.39 | 26.61 | 3.39 | 3.39 |
| 301 | SPIRAL-n1-CW-e+0-g0.120 | L16 | -100.8 | 0.16 | 36.5 | 29.6 | 0.4 | 0.4 |
| 305 | SWITCHBACK-k1-p+20-CCW-g0.100 | L02 | 175.88 | 25.15 | 101.03 | 114.25 | 0.0 | 0.0 |
| 305 | SWITCHBACK-k1-p+20-CCW-g0.100 | L03 | 136.03 | 5.17 | 79.67 | 30.92 | 0.0 | 0.0 |
| 305 | SWITCHBACK-k1-p+20-CCW-g0.100 | L04 | 136.15 | 25.15 | 70.23 | 71.91 | 0.0 | 0.0 |
| 305 | SWITCHBACK-k1-p+20-CCW-g0.100 | L05 | 96.3 | 5.17 | 47.63 | 0.53 | 29.47 | 29.47 |
| 305 | SWITCHBACK-k1-p+20-CCW-g0.100 | L06 | 96.41 | 25.15 | 61.69 | 60.47 | 0.0 | 0.0 |
| 305 | SWITCHBACK-k1-p+20-CCW-g0.100 | L07 | 56.57 | 5.17 | 49.62 | 6.29 | 23.71 | 23.71 |
| 305 | SWITCHBACK-k1-p+20-CCW-g0.100 | L08 | 56.68 | 25.15 | 75.3 | 71.31 | 0.0 | 0.0 |
| 305 | SWITCHBACK-k1-p+20-CCW-g0.100 | L09 | 16.84 | 5.17 | 85.61 | 37.13 | 0.0 | 0.0 |
| 305 | SWITCHBACK-k1-p+20-CCW-g0.100 | L10 | 16.95 | 25.15 | 103.19 | 111.64 | 0.0 | 0.0 |
| 305 | SWITCHBACK-k1-p+20-CCW-g0.100 | L11 | -22.89 | 5.17 | 78.54 | 23.33 | 6.67 | 6.67 |
| 305 | SWITCHBACK-k1-p+20-CCW-g0.100 | L12 | -15.0 | 32.93 | 75.71 | 8.68 | 21.32 | 21.32 |
| 322 | SWITCHBACK-k1-p+20-CCW-g0.120 | L03 | 107.09 | 0.77 | 72.7 | 47.05 | 0.0 | 0.0 |
| 322 | SWITCHBACK-k1-p+20-CCW-g0.120 | L04 | 112.16 | 7.72 | 84.15 | 93.25 | 0.0 | 0.0 |
| 322 | SWITCHBACK-k1-p+20-CCW-g0.120 | L05 | 103.32 | 0.77 | 84.0 | 58.11 | 0.0 | 0.0 |
| 322 | SWITCHBACK-k1-p+20-CCW-g0.120 | L06 | 108.39 | 7.72 | 103.78 | 113.92 | 0.0 | 0.0 |
| 322 | SWITCHBACK-k1-p+20-CCW-g0.120 | L07 | 99.55 | 0.77 | 102.8 | 82.61 | 0.0 | 0.0 |
| 322 | SWITCHBACK-k1-p+20-CCW-g0.120 | L08 | 105.98 | 9.08 | 117.48 | -82.24 | 112.24 | 112.24 |
| 322 | SWITCHBACK-k1-p+20-CCW-g0.120 | L09 | 96.86 | 1.86 | 115.76 | -79.79 | 109.79 | 109.79 |

### Open finding F1 — backbone across the near leg on successful SWITCHBACK winners

Excluding the trace end margins changes nothing on the winners (δ_int = δ on every level above). On 305 (L05, L07, L12) and 322 (L08, L09) the construction backbone INSIDE the candidate's footprint lies at or BEYOND the delivered near leg (backbone separation +0.5 … −82 m) while the stage-4 anchor of the same level sits 48–117 m away and the access succeeded. Two readings, not yet separated: (a) the footprint window (± leg/2 + margin along the leg through the near-leg centre, z-window ± half a level interval) catches a hairpin / far-side portion of the trace that the leg does not actually run alongside; (b) the main ramp genuinely crosses the level's development backbone — a ramp ↔ DRIFT conflict that no current gate validates (the access planner checks the BRANCH pillar only; rule 160 forbids shared nodes, not geometric crossing). Either way a naive support cannot be applied to SWITCHBACK until F1 is resolved: the contract below is stated unconditionally for SPIRAL (rim footprint, clean: 301 winner δ_int 0.4–11.4 m, 307 spiral 19–20 m) and CONDITIONALLY for SWITCHBACK (Gate C step 0 = F1 investigation on 322 L08 / 305 L05 with the traces plotted against the delivered legs; if (b) holds, the crossing is a new typed finding for the level builder, not a corridor rule).

**Resolved in Gate C step 0** (`docs/verification/phase20c4_c0_f1.md`, `backend/golden/phase20c4_c0_f1.json`): reading (b) does not hold — no crossing near a level plane and no excavation conflict on either winner (minimum 3-D ramp ↔ backbone distance 18.1 m). 322 L08 / L09 and 305 L12 are window artefacts (empty footprint answered by a whole-trace fallback; a window centred on a terminal hairpin plus the along margin over a 33° oblique backbone). 305 L05 / L07 are genuine encroachments of the leg-end hairpin on the level backbone (14.9 / 19.6 m plan) — the mechanism the contract corrects. Two refinements apply to §4: the footprint is the ramp's OWN along-extent about the construction centre (SWITCHBACK `leg/2 + R_min`, SPIRAL `R`; the 6-width margin is lateral only) and an empty footprint yields δ = 0. SWITCHBACK proceeds to C3 under those refinements.

### Stage-4 dominance check on DETAILED candidates (delivered corridor separation, metres)

| status | levels | separation from the stage-4 anchor p10/p50/p90 | separation from the WORLD-policy backbone support p10/p50/p90 | levels where anchor separation < backbone separation |
|---|---|---|---|---|
| INFEASIBLE | 599 | [-16.1, 12.0, 48.3] | [-38.0, -8.2, 25.5] | 6 |
| FEASIBLE | 272 | [25.8, 48.4, 107.8] | [-44.5, 23.4, 87.4] | 19 |

This table is NOT a proof of the dominance invariant and is not read as one: it compares the stage-4 anchor POINT (entry, at the candidate policy's 20 m stand-off, possibly outside the footprint window) with the construction support (a max over the WORLD-policy trace at the 22.36 m world stand-off inside the window), so the last column mixes stand-offs, window membership and trace smoothing. The invariant proper — construction-trace support ≥ candidate-trace support along n over the SAME footprint interior — is a required Gate C test (`RefinedConservativeClearance.signed_clearance = max(coarse, refined)` makes it hold by construction for the certified fields; the trace-level statement must be verified numerically because the offset traces are smoothed and re-validated separately).

## 3. First-pass direct check (provenance)

The first shadow used a whole-trace support (over-reading oblique legs by 60–137 m), then a track-centroid window with hard-coded g = 0.12, k = 1 and a ±80 m switchback window. Those passes are kept in the JSON under `superseded` / `firstPassDirectCheck` for provenance only; the candidate-exact shadow above is authoritative.

| seed | candidate | status | near-leg levels | formula error (median) | stage-4 anchor separation (median) | backbone separation (median) | required move median / max |
|---|---|---|---|---|---|---|---|
| 305 | SWITCHBACK-k1-p+20-CCW-g0.100 | FEASIBLE | 5 | 5.2 | 78.5 | 37.8 | 0.0 / 6.7 |
| 307 | SWITCHBACK-k1-p+0-CW-s50-g0.120 | INFEASIBLE | 5 | -4.2 | -2.6 | -5.3 | 35.3 / 36.7 |
| 307 | SPIRAL-n1-CW-e+0-g0.100 | INFEASIBLE | 8 | 12.4 | 13.9 | 11.3 | 18.7 / 20.0 |
| 301 | SPIRAL-n1-CW-e+0-g0.120 | FEASIBLE | 14 | 0.0 | 30.0 | 22.6 | 7.4 / 11.3 |

## 4. Single-source contract (`ServiceReference`)

```
orebody / section geometry (LevelSections, contains()-authoritative)
        ↓
CONSERVATIVE CONSTRUCTION ServiceReference = the certified clearance level set of each level plane
        under the WORLD (coarse) policy, at the WORLD anchor stand-off (rule 178 offset trace, token "WORLD"
        — the trace stage 4 already builds for coarse anchors)
        ↓
        ├── ramp service corridor (stage 1)  : lateral(z, n, footprint) = footwall_edge(z)·n + footwallStandoff + δ(z, n, footprint)
        │                                      δ = max(0, support_footprint(trace_z, n) + RAMP_CORRIDOR_MARGIN_WIDTHS·width − (footwall_edge(z)·n + footwallStandoff))
        │                                      piecewise-linear in z between required levels, clamped ≥ 0, constant beyond the level range
        └── development anchor (stage 4)     : entry on the CANDIDATE-policy offset trace (unchanged, rule 178/179)
```

- **Construction reference vs candidate field**: the corridor is built at stage 1, before any candidate policy exists, so it reads the WORLD policy — a conservative construction reference, NOT "the same candidate-specific field" the stage-4 anchor reads.
- **Stage-4 dominance invariant**: `RefinedConservativeClearance.signed_clearance = max(coarse, refined)` (`design/cost_field.py:191–196`), so every candidate policy certifies ≥ the construction policy at every point; the candidate-policy offset trace at the same stand-off lies on or ore-ward of the construction trace, hence the delivered corridor–anchor separation ≥ the construction separation ≥ 6 widths. Gate C tests this invariant numerically (construction support ≥ candidate-trace support along n on WARPED-301 / 307 levels) and the shadow table in §2 already shows it on the audited DETAILED candidates. EXACT policies collapse both references onto the analytic surface.
- **Explicit `footwallStandoff`**: when `layout.footwallStandoff` is EXPLICIT the legacy placement is preserved unchanged (δ is not applied; the user's number is the corridor). The reference applies to the derived default (`DEFAULT_OFFSET_PLUS_CORRIDOR_MARGIN`) only; `effective_footwall_standoff` already reports the provenance.
- **Families in scope**: SPIRAL unconditionally (footprint = helix radius R + margin, from the candidate's own g and turns/level); SWITCHBACK conditionally on open finding F1 (footprint = near-leg half-length + margin from the candidate's own k, g and station). **LONGITUDINAL is deferred unchanged in this phase** (its corridor spans the whole strike; the whole-trace reading is informational only and no LONGITUDINAL candidate appears in the audited failure populations).
- **Shared abstraction**: `ServiceReference` (helper next to `build_footwall_track`, built once in `LayoutV2Search.run()` setup, carried on `LayoutContext`): per level the WORLD-policy offset trace points; `corridor_lateral(z, n, along_dir, along_centre, along_half_extent)`; TABULAR → analytic path, δ = 0 (bit-identical).
- **FootwallTrack future role**: family construction / orientation (u_h, w_h, lateral drift, hairpin stacking) and the z-trend of the corridor; no longer the corridor's lateral authority on implicit bodies (δ corrects it per level); on TABULAR the two coincide.
- **Corridor derivation** (three call sites): `build_spiral` axis `footwall_edge(z) + d_hat·(lateral(z, d_hat, …) − footwall_edge(z)·d_hat + R)` (`families.py:663`); `build_switchback` near-leg placement at z_join and the pair-drift term at z_a / z_pair use the reference lateral (`:929`, `:965`); `build_longitudinal` untouched (`:790`).
- **Anchor derivation**: unchanged (`build_anchor` / `build_curved_anchor`, rule 178 trace, entry policy, trace-chainage semantics).
- **Error-bound treatment**: unchanged and applied ONCE — the construction reference and the anchor both read certified fields; no `+ errorBound + traceBias` arithmetic (§15); δ is measured from actual backbone geometry and is never negative (the corridor is never pulled inward, so every currently-valid placement stays at least where it is).
- **Windowing**: the support is taken over the trace points inside the candidate's own footprint along the corridor direction (a leg only has to clear what it runs alongside); geometric, not a tolerance.
- **Backbone interior**: the support excludes the trace end margins exactly as the anchor admissible range does (`min(BACKBONE_END_MARGIN, 0.25 × length)` per end, `layout/access.py`) — the developed backbone, not the raw level set. Where a level set wraps around a strike end, the full-trace support can cut across a valid near leg (e.g. one level of the 322 winner reads a full-trace δ of 112 m); the interior support is the contract quantity and the full-trace value is reported as a diagnostic.
- **Stage-1 cost**: fresh sections + track + 9 WORLD-policy offset traces on 307 = 1.33 s against a 22.6 s search; the traces are the cached objects stage 4 builds for coarse anchors today.

## 5. TABULAR pre-implementation sanity (§16)

TABULAR keeps the analytic corridor path (delta ≡ 0): both the rule-43 anchor line and the track edge derive from the analytic footwall plane. track-fit residual on TABULAR-42 is 0.02–0.39 m per level; the measured anchor→track-edge offset is 21.3 m against the 20 m stand-off (grid-fit residual of the analytic edge), so a numerically re-derived delta would be ≤ 1.3 m — not applied; geometry unchanged bit-for-bit Old / new reference equivalent on TABULAR: **YES (bit-identical by contract)**; the Gate C test asserts the TABULAR-REFERENCE and small-TABULAR candidate polylines are unchanged to 1e-9.

## 6. Hard-stop review (§28)

- 1 census on main: no — present
- 2 Population A not supported: no — CONFIRMED (Gate A)
- 3 B not supported and implementation assumes it: no — the contract corrects the corridor/anchor separation only; B is measured in Gate D, not assumed
- 4 controls show the same mismatch without failures: no — nearest approach ≤ 20 m on 97.5 % of failed levels, 0 % of control levels
- 5 different physical intents: no — YES same spacing system
- 6 requires relaxing grade / clearance / radius / pillar: no — δ ≥ 0 moves the corridor outward only; every gate unchanged
- 7 TABULAR shadow changes materially: no — δ ≡ 0 on TABULAR
- 8 candidate-specific clearance provenance lost: no — candidate_policy / refinement untouched; the construction reference uses the existing WORLD token and stage-4 policies dominate it
- 9 screen authority must change: no — screen semantics untouched
- 10 broad family redesign: no for SPIRAL — lateral placement substitution at one call site; SWITCHBACK held behind F1 (if F1 is a genuine ramp–backbone crossing it is a level-builder finding, not a family redesign); LONGITUDINAL deferred

## 7. Expected effects to be measured in Gate D (not targets)

- Failing seeds: corridor moves outward by the candidate-exact δ of §2 along the family lateral direction; the near-leg / rim junction becomes available with |dz| ≈ 0; GRADE_LIMIT-labelled levels are predicted to drop first (REFERENCE_CAUSED), pillar / connector next. Portal-approach and first-leg ABOVE_TERRAIN populations are untouched by construction.
- Successful seeds: winner δ — 301 {'candidateId': 'SPIRAL-n1-CW-e+0-g0.120', 'family': 'SPIRAL', 'deltaMedian': 7.49, 'deltaMax': 11.35, 'deltaInteriorMedian': 7.49, 'deltaInteriorMax': 11.35}, 305 {'candidateId': 'SWITCHBACK-k1-p+20-CCW-g0.100', 'family': 'SWITCHBACK', 'deltaMedian': 0.0, 'deltaMax': 29.47, 'deltaInteriorMedian': 0.0, 'deltaInteriorMax': 29.47}, 322 {'candidateId': 'SWITCHBACK-k1-p+20-CCW-g0.120', 'family': 'SWITCHBACK', 'deltaMedian': 0.0, 'deltaMax': 112.24, 'deltaInteriorMedian': 0.0, 'deltaInteriorMax': 112.24}; winner changes are possible and must be reported. Ranking metrics recomputed from the delivered geometry; no bonus.
- Population B: near-leg clusters should move with the corridor; far-leg / hairpin clusters (56–133 m from the track edge) are NOT addressed by this contract and stay in the count.

## 8. Gate C plan

Gate C step 0: resolve F1 (plot the 322 L08 / 305 L05 construction trace against the delivered near leg; decide window-artefact vs ramp–backbone crossing). **DONE — window artefacts on 322 L08 / L09 and 305 L12, genuine encroachment (no crossing, no conflict) on 305 L05 / L07; footprint refined to the ramp's own along-extent, empty footprint ⇒ δ = 0; SWITCHBACK cleared for C3.** Commit 20C4-B: `ServiceReference` + tests (determinism; TABULAR old/new equivalence; WARPED construction reference δ > 0 on 307 and small where the track already fits; EXACT and CONSERVATIVE policy cases; refined-clearance provenance untouched; stage-4 dominance invariant). Commit 20C4-C: corridor integration at the SPIRAL / SWITCHBACK call sites + explicit-standoff legacy path + tests (corridor and anchor share authority; GRADE_LIMIT and INSUFFICIENT_RAMP_PILLAR causal regressions on 307 SWITCHBACK-k1-p+0-CW-s50-g0.120 and SPIRAL-n1-CW-e+0-g0.100 — separation ≥ 30 m at the RL crossing, never a success-count assertion; screen authority unchanged; candidate ordering unchanged when geometry unaffected; no-shaft / shaft downstream smoke). Commit 20C4-D: 32-seed controlled survey vs the 20C.3A census, golden comparison, docs, roadmap.

DO NOT IMPLEMENT PRODUCTION GEOMETRY UNTIL THIS GATE IS REVIEWED.
