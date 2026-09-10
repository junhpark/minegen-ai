# Phase 20C.4 — Gate B: Engineering Intent + Single-Source Service Reference Contract

Diagnostic artifact: `backend/golden/phase20c4_gate_b_shadow.json` (shadow computation on main efecf00 + Gate A commit; production change 0). Scripts: `scripts/phase20c4_shadow_20c4b.py`, `scripts/phase20c4_shadow_check_20c4b.py`, `scripts/phase20c4_time_traces_20c4b.py`. This document is the Gate B architecture decision; implementation waits for Gate C approval.

## 1. Engineering intent check

- **What physical surface does rule 170 offset the ramp service corridor from?** The footwall footprint edge (the ore contact on the footwall side), by `footwall_access_offset + RAMP_CORRIDOR_MARGIN_WIDTHS × tunnel_width` — i.e. the level-development plane plus two half-spans, a two-width rock pillar and a three-width turnout-taper allowance (`docs/algorithms.md` S1 table, `layout/families.py::effective_footwall_standoff`).
- **What physical surface does the 20C.2A anchor stand-off offset from?** The same footwall contact: `footwall_access_offset` from the footwall footprint edge (rule 43 line on TABULAR); on implicit bodies the stand-off is measured on the certified-clearance field (rule 178 offset trace), raised under a conservative basis (rule 158).
- **Same physical spacing system? YES.** The corridor default is defined as the anchor plane plus explicit spatial margins. Only the implementation reference differs: the corridor reads the GLOBAL linear `FootwallTrack` edge (a per-level fit of `centroid + w_h·extent` — true contact, residual 0.02–0.39 m on TABULAR-42 but 1–68 m per level on WARPED seeds), the anchor reads the CERTIFIED clearance level set (which lies error-bound + trace-smoothing bias outside the true contact). → PROCEED to a shared reference contract (§11 of the directive).

## 2. Where the current corridor actually is (direct check on delivered geometry)

Per level, the delivered ramp's ore-facing extreme within ±3 m of the RL compared with the rule-170 formula, the stage-4 anchor and the WORLD-policy anchor-trace support inside the family footprint centred on the delivered corridor (metres):

| seed | candidate | status | levels (near-leg / rim levels) | formula error at near levels (median) | anchor separation from near leg (median) | trace-support separation (median) | required outward corridor move median / max | failed levels |
|---|---|---|---|---|---|---|---|---|
| 305 | SWITCHBACK-k1-p+20-CCW-g0.100 | FEASIBLE | 11 (5) | 5.2 | 78.5 | 37.8 | 0.0 / 6.7 | 0 |
| 307 | SWITCHBACK-k1-p+0-CW-s50-g0.120 | INFEASIBLE | 9 (5) | -4.2 | -2.6 | -5.3 | 35.3 / 36.7 | 5 |
| 307 | SPIRAL-n1-CW-e+0-g0.100 | INFEASIBLE | 9 (8) | 12.4 | 13.9 | 11.3 | 18.7 / 20.0 | 7 |
| 301 | SPIRAL-n1-CW-e+0-g0.120 | FEASIBLE | 14 (14) | 0.0 | 30.0 | 22.6 | 7.4 / 11.3 | 0 |

- The formula `footwall_edge(z)·n + footwallStandoff` reproduces the delivered spiral rim exactly (301: 0.0 m) and the switchback near leg within 4–5 m; levels served by the FAR leg show the +2R (+ station) offset (86.6 m on 307, 61 m on 305) as expected.
- On the failing 307 switchback the anchors sit ON the near-leg line (separation −2.8 … +1.5 m) and the anchor backbone protrudes 5–7 m BEYOND the near leg; on the failing 307 spiral the rim passes the anchors at 13–14 m. On the successful 301 spiral the separation is 24–37 m (backbone 19–29 m); on the successful 305 switchback 48–139 m.
- Required outward corridor move to restore 6 widths against the anchor backbone: 307 switchback 35–37 m, 307 spiral 19–20 m, 301 winner 7 m median / 11 m max (its geometry WILL change), 305 winner 0 m median / 6.7 m max.

## 3. Whole-trace vs footprint-windowed support (why the window is part of the contract)

The first shadow pass took the support of the anchor trace over its WHOLE length: along oblique lateral directions (spiral e ± 45°, switchback p ± 20°) that reads 60–137 m even on successful seeds, because a leg 150 m long does not run alongside a 300–600 m body. Windowing the support to the family footprint (SPIRAL |u − u_axis| ≤ R + margin, SWITCHBACK |proj_leg − leg centre| ≤ leg/2 + margin) and centring it on the DELIVERED corridor gives the table above. The contract therefore defines the reference per footprint, never as a global support.

| seed | status | SPIRAL e+0 delta median/max (windowed, track-centroid window) | SWITCHBACK p+0 | LONGITUDINAL |
|---|---|---|---|---|
| 42 | SUCCESS | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 |
| 301 | SUCCESS | 7.24 / 11.34 | 13.22 / 17.09 | 32.87 / 38.2 |
| 305 | SUCCESS | 43.55 / 55.77 | 43.57 / 56.2 | 50.83 / 59.83 |
| 307 | NO_FEASIBLE | 31.01 / 32.55 | 31.22 / 32.83 | 31.29 / 32.83 |
| 320 | NO_FEASIBLE | 32.56 / 34.47 | 32.56 / 35.54 | 32.56 / 35.56 |
| 328 | NO_FEASIBLE | 40.35 / 42.49 | 40.76 / 42.99 | 40.76 / 42.99 |
| 312 | NO_FEASIBLE | 38.3 / 39.09 | 38.3 / 39.09 | 38.3 / 39.09 |
| 303 | NO_FEASIBLE | 38.74 / 39.0 | 39.28 / 40.04 | 39.36 / 40.38 |
| 322 | SUCCESS | 35.12 / 36.59 | 35.18 / 36.59 | 35.18 / 36.59 |

(TABULAR-42: 0 / 0 in every direction by contract; WARPED failing seeds 31–41 m; WARPED-301 7 / 11 m.)

## 4. Single-source contract (`ServiceReference`)

```
orebody / section geometry (LevelSections, contains()-authoritative)
        ↓
authoritative local service reference = the CERTIFIED clearance level set on each level plane
        (rule 178 offset trace at the anchor stand-off, WORLD policy, token "WORLD" — already computed today for stage-4 coarse anchors)
        ↓
        ├── development anchor      : entry on that trace (unchanged, rule 178/179)
        └── ramp service corridor  : lateral(z, n, footprint) = footwall_edge(z)·n + footwallStandoff + δ(z, n, footprint)
                                      δ = max(0, support_footprint(trace_z, n) + RAMP_CORRIDOR_MARGIN_WIDTHS·width − (footwall_edge(z)·n + footwallStandoff))
                                      δ interpolated piecewise-linearly between required levels, clamped ≥ 0, constant beyond the level range
```

- **Authoritative source**: the candidate-policy family's certified clearance field. Stage 1 (family construction) only has the WORLD policy, so the reference is built once per search on the world policy (`LevelSections.offset_trace(level, w_h, anchor_standoff(world), …, token="WORLD")`); stage-4 anchors under a REFINED policy sit at or inside that trace, so the separation after alignment is ≥ the intended value — conservative direction, documented.
- **Shared abstraction**: `ServiceReference` (new helper in `layout/levels.py` or `layout/families.py`, built in `LayoutV2Search.run()` setup next to `build_footwall_track`, carried on `LayoutContext`): per level the offset trace points; method `corridor_lateral(z, n, along_dir, along_centre, along_half_extent)`; TABULAR → the analytic path returns δ = 0 and the existing formula unchanged.
- **FootwallTrack future role**: family construction / orientation (u_h, w_h, lateral drift, hairpin stacking) and the z-trend of the corridor; no longer the corridor's lateral authority on implicit bodies (δ corrects it per level); on TABULAR the two coincide.
- **Corridor derivation**: `build_spiral` axis: `footwall_edge(z) + d_hat·(corridor_lateral(...) − footwall_edge(z)·d_hat + R)`; `build_switchback` near-leg placement and the pair-drift term use the reference lateral at z_join / z_a / z_pair instead of the bare edge; `build_longitudinal` corridor0 likewise (whole-trace footprint). Three call sites (`families.py:663`, `:929/:965`, `:790`).
- **Anchor derivation**: unchanged (`build_anchor` / `build_curved_anchor`, rule 178 trace, entry policy, trace-chainage semantics).
- **Error-bound treatment**: unchanged and applied ONCE — the corridor reads the same certified field the anchor reads; no `+ errorBound + traceBias` arithmetic (§15), δ is measured from the actual backbone geometry and is never negative (the corridor is never pulled inward, so every currently-valid placement stays at least where it is).
- **Windowing**: the support is taken over the trace points inside the family footprint along the corridor direction; this is geometric (a leg only has to clear what it runs alongside), not a tolerance.
- **Stage-1 cost**: fresh sections + track + 9 world-policy offset traces on 307 = 1.33 s against a 22.6 s search; the traces are the same cached objects stage 4 builds for coarse anchors today.

## 5. TABULAR pre-implementation sanity (§16)

TABULAR keeps the analytic corridor path (delta ≡ 0): both the rule-43 anchor line and the track edge derive from the analytic footwall plane. the track-fit residual on TABULAR-42 is 0.02–0.39 m per level; the measured anchor→track-edge offset is 21.3 m against the 20 m stand-off (grid-fit residual of the analytic edge), so a numerically re-derived delta would be ≤ 1.3 m — the contract does not apply it; geometry is unchanged bit-for-bit Old / new reference equivalent on TABULAR: **YES (bit-identical by contract)**; the Gate C test asserts the TABULAR-REFERENCE and small-TABULAR candidate polylines are unchanged to 1e-9.

## 6. Hard-stop review (§28)

- 1 census on main: no — present
- 2 Population A not supported: no — CONFIRMED (Gate A)
- 3 B not supported and implementation assumes it: no — the contract corrects the corridor/anchor separation only; B is measured in Gate D, not assumed
- 4 controls show the same mismatch without failures: no — nearest approach ≤ 20 m on 97.5 % of failed levels, 0 % of control levels
- 5 different physical intents: no — YES same spacing system
- 6 requires relaxing grade / clearance / radius / pillar: no — δ ≥ 0 moves the corridor outward only; every gate unchanged
- 7 TABULAR shadow changes materially: no — δ ≡ 0 on TABULAR
- 8 candidate-specific clearance provenance lost: no — candidate_policy / refinement untouched; the reference uses the existing WORLD token
- 9 screen authority must change: no — screen semantics untouched
- 10 broad family redesign: no — lateral placement substitution at three call sites; family topology, enumeration, ids unchanged

## 7. Expected effects to be measured in Gate D (not targets)

- Failing seeds: corridor moves 19–41 m outward along the family lateral direction; the near-leg / rim junction becomes available with |dz| ≈ 0; GRADE_LIMIT-labelled levels are predicted to drop first (REFERENCE_CAUSED), pillar / connector next. Portal-approach and first-leg ABOVE_TERRAIN populations are untouched by construction.
- Successful seeds: WARPED-301 winner corridor moves ≤ 11 m (winner change possible — must be reported); 305 / 322 ≤ 7 m at two levels. Ranking metrics recomputed from the delivered geometry; no bonus.
- Population B: near-leg clusters should move with the corridor; far-leg / hairpin clusters (56–133 m from the track edge) are NOT addressed by this contract and stay in the count.

## 8. Gate C plan

Commit 20C4-B: `ServiceReference` + tests (determinism; TABULAR old/new equivalence; WARPED local reference δ > 0 on 307 and ≈ 0 where the track already fits; EXACT and CONSERVATIVE policy cases; refined-clearance provenance untouched). Commit 20C4-C: corridor integration at the three call sites + tests (corridor and anchor share authority; GRADE_LIMIT and INSUFFICIENT_RAMP_PILLAR causal regressions on 307 SWITCHBACK-k1-p+0-CW-s50-g0.120 and SPIRAL-n1-CW-e+0-g0.100 — separation ≥ 30 m at the RL crossing, never a success-count assertion; screen authority unchanged; candidate ordering unchanged when geometry unaffected; no-shaft / shaft downstream smoke). Commit 20C4-D: 32-seed controlled survey vs the 20C.3A census, golden comparison, docs, roadmap.

DO NOT IMPLEMENT PRODUCTION GEOMETRY UNTIL THIS GATE IS REVIEWED.
