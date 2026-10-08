# H2-CF — Cut & Fill schedule characterization, before / after

Status: **recorded** (hardening PR-2, commit C2). The two records are
`backend/tests/fixtures/h2cf/cut_fill_characterization_{before,after}.json`,
both written by `scripts/h2cf_capture_cut_fill_characterization.py` on the
small scenario (`tests.conftest.small_scenario(seed 42)`, TABULAR 200 × 120 ×
12 m, 4 required levels) with the Cut & Fill canonical defaults of each
code state. `before` was captured on the PR-2 baseline (main `1bd68c8`,
script copied into a worktree of that commit), `after` on the PR-2 branch.
`tests/test_cut_fill_characterization.py` (marker `slow`, FULL only) keeps
the `after` record as the refactor net; `before` is evidence only.

## What changed and why

| quantity | before (1bd68c8) | after (H2-CF) | why |
| --- | --- | --- | --- |
| production accesses per level | 1 (`CROSSCUT:<L>:S+00`) | 4 (`S+00 … S+03`, one per 50 m panel) | `panelLengthM` 60 → `ceil(200 / 60)` = 4 equal panels; the access is the panel's |
| blocks / panels | — / — | 3 / 12 | block = level interval, panel = strike partition |
| cuts / backfills | 294 | 336 | cuts partition the panel's mined span (50 m / 15 m → 4 × 12.5 m) instead of the whole strike (200 m / 15 m → 14 × 14.29 m); total volume and tonnes unchanged (191 552.0 m³, 536 345.6 t) |
| lifts | 21 | 21 | unchanged (dip-aware equal partition of each interval) |
| cemented backfills | 0 | 32 (bottom lift of the two blocks mined above an unmined block) | SHALLOW_TO_DEEP default: cemented sill mats |
| cure durations (days) | {7} | {7, 28} | `sillMatCureDays` 28 for cemented fills, `schedule.backfillCureDays` 7 otherwise |
| PREP dependencies | 294 × access + 293 × previous CURE (one global chain) | 336 × access + 366 × CURE (in-panel chain + concurrency gate + vertical sill-mat gates) | no global previous-cure chain |
| max cuts open at once | 1 | 2 | `maxConcurrentPanels` 2 — a precedence rule, not a capacity |
| max panels in production at once | — | 2 | measured on the half-open [first PREP, last CURE) windows |
| first STOPING day | 404.45 (after ramp completion 371.46) | 298.18 (before ramp completion 371.46) | the top block starts once its own level access and panel crosscut exist |
| end day | 5 204.5 | 3 293.7 | two panels in production instead of one serial front |

Development (ramp, level accesses, drifts) is unchanged except for the
additional production crosscuts: `rampCompletionDay` 371.46 in both records.

## What did NOT change

- Longhole and Room & Pillar: no code path touched (rule 193 baseline
  `tests/fixtures/phase21bc/longhole_baseline.json` byte-identical, Room &
  Pillar keeps the single central access and its single-front schedule).
- Hard constraints, thresholds, goldens: none. The layout-v2 golden
  `CUT_AND_FILL` case records the layout only.
- The timeline contract: `targetKind = CUT`, five tasks per cut, the four
  state transitions bound to task boundaries (rule 84).

## Honesty notes

- The sequencing is a deterministic precedence BASELINE (rule 82), never a
  resource or fleet model; `maxConcurrentPanels` is a planning assumption
  (HRMH: "more stoping units than theoretically needed"), not a measured
  capacity.
- `maxConcurrentStoping` stayed 1 in the after record: with two panels open
  the STOPING windows happened not to overlap on this fixture (the panels'
  cycles interleave); it is a measurement, not a rule.
