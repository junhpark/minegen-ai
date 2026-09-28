# Mine analysis and planning economics (Phase 22A/B)

`GET /api/v1/scenarios/{id}/analysis` is a **read-only projection** of the
persisted mine state into planning quantities. It is computed per request
from one validated snapshot, persists nothing, runs no job and never touches
a mine artifact. The status of every figure is fixed by `CLAUDE.md` rules
197–202: **synthetic planning quantities — never a resource or reserve
estimate, a feasibility study or an investment recommendation.**

## Sources and authorities

| Section | Authority | Absent / FAILED | Present but inconsistent |
| --- | --- | --- | --- |
| development | `derived/network.json` (MineNetwork edges) | `NOT_AVAILABLE` + reason (200) | 409 `ANALYSIS_SOURCE_INCONSISTENT` |
| production | `derived/stopes.json` (the ACTIVE production artifact, typed by method) | `NOT_AVAILABLE` (200) | 409 |
| schedule | `derived/timeline.json` (MineTimeline baseline) | `NOT_AVAILABLE` (200) | 409 (a SUCCESS timeline without its network / production owner is inconsistent, never partial) |
| ratios | development + production | `NOT_AVAILABLE`; tonnes = 0 → `AVAILABLE` with null ratios | — |
| economics | `economics.json` + the three sections above | `NOT_CONFIGURED` (no config) / `NOT_AVAILABLE: SOURCE_NOT_AVAILABLE …` | 409 `ARTIFACT_MALFORMED` for an unusable `economics.json` |

A world that is not generated makes every derived section `NOT_AVAILABLE`
(derived files are never trusted without a valid world). Every consumed
source — `scenario.json`, `arrays.npz`, the three artifacts and
`economics.json` — is re-observed after the projection; any movement is
409 `READ_SNAPSHOT_CHANGED`. The scenario document itself is the bound read
(`ScenarioStore.get_bound`, stat → get → re-stat) and the artifact snapshot
is taken with `expect_scenario_revision` = that revision, so a same-id
scenario PUT between the document read and the snapshot is also
`READ_SNAPSHOT_CHANGED`.

## What the numbers mean

- **Development.** Per `EdgeType` (RAMP, LEVEL_ACCESS, DRIFT, CROSSCUT,
  RAISE, SHAFT, SHAFT_STATION_ACCESS): edge count, total 3-D length and the
  **gross** excavation volume `Σ length3d × analyticArea`. Junction overlaps
  are not unioned. The network's declared metrics are cross-checked against
  the edges (counts exact, lengths within 1e-6 m) and never overwritten.
- **Production.** `totalPlannedMinedTonnes` is the sum of the production
  objects' persisted tonnes (stopes, cuts or extraction units — solids ×
  density). Retained pillars (Room & Pillar) and backfills (Cut & Fill) are
  reported separately and are **not** production. `weightedMeanGradeProxy`
  is the tonnage-weighted Phase 09 planning proxy: informational, never a
  revenue input, never an "economic grade".
- **Schedule.** Task counts, start / end day, `mineDurationDays`,
  `rampCompletionDay`, `firstProductionDay` (earliest STOPING start) — the
  deterministic precedence-only baseline, never a production forecast.
- **Ratios.** `developmentMetresPerKt` and `grossDevelopmentM3PerKt` per
  thousand planned mined tonnes.

## Economics assumptions (`economics.json`)

A **user-authored** document at `data/scenarios/{id}/economics.json`, beside
`scenario.json`. It is not a derived artifact: it has no registry entry, no
fingerprint role and no invalidation cascade. Writing it changes no geometry,
production or timeline; a scenario PUT does not delete it.

    GET /api/v1/scenarios/{id}/analysis/economics-config
        → {"configured": false, "revision": null, "config": null}   when absent
    PUT /api/v1/scenarios/{id}/analysis/economics-config   body = EconomicsConfig
        → {"configured": true, "revision": "<sha256 of the canonical JSON>", "config": {...}}

`EconomicsConfig` (every float finite and ≥ 0; no defaults exist):

| field | meaning |
| --- | --- |
| `version` | 1 |
| `currencyCode` | `^[A-Z]{3}$`; a label only — no conversion |
| `developmentCosts.{rampPerM, levelAccessPerM, driftPerM, crosscutPerM, raisePerM, shaftPerM, shaftStationAccessPerM}` | cost per metre by edge type (one per `EdgeType`; no generator emits a RAISE in v0.1, the rate exists so a typed edge is priced, never refused) |
| `productionCosts.{longholeOpenStopingPerTonne, cutAndFillPerTonne, roomAndPillarPerTonne}` | mining cost per planned mined tonne; only the active method's rate is used |
| `processingCostPerTonne` | per planned mined tonne |
| `backfillCostPerM3` | Cut & Fill only (0 for other methods) |
| `fixedOperatingCostPerDay` | linear over the mine duration |
| `grossRevenuePerMinedTonne` | the ONE revenue model: `plannedMinedTonnes × rate` |
| `initialCapitalCost` | day 0 (bucket 0) |
| `annualDiscountRate` | fraction ≥ 0 |
| `cashflowBucketDays` | > 0; 30 is the recommended explicit value |

No metal price, recovery, payability, smelter charge, grade unit, commodity,
IRR, tax, depreciation, royalty or inflation exists in v0.1.

## Cost timing and the Planning Cashflow

Geometry is the quantity authority; the timeline is the timing authority.

| amount | quantity × rate | spread over |
| --- | --- | --- |
| development cost | `length3d × rate(edge type)` | the edge's `DEVELOP_*` task (`basis.quantity ≈ length3d`, unit `m`, verified) |
| production mining cost | `tonnes × active method rate` | `STOPING` |
| processing cost | `tonnes × processingCostPerTonne` | `MUCKING` |
| gross revenue | `tonnes × grossRevenuePerMinedTonne` | `MUCKING` |
| backfill cost (Cut & Fill) | `backfillVolume × backfillCostPerM3` | `BACKFILL` (`basis.quantity ≈ backfill volume`, unit `m3`, verified) |
| fixed operating cost | `mineDurationDays × rate` | `[startDay, endDay]` |
| initial capital | `initialCapitalCost` | bucket 0 |

Buckets are fixed `cashflowBucketDays` intervals from day 0 (the last one
closed at the mine end); an amount on `[s, e]` is allocated by overlap
fraction, a zero-length interval as a point event. Per bucket:
`netCashflow = revenue − Σ costs`, `cumulativeCashflow` running,
`discountedNetCashflow = net / (1 + annualDiscountRate)^(midDay / 365.25)`.

**Baseline Planning NPV** = Σ `discountedNetCashflow` (mid-bucket
convention, `npvConvention = MID_BUCKET_MIDPOINT`). With a zero rate the NPV
equals the undiscounted net cashflow exactly. Every bucket column reconciles
with the summary and `totalCost` is the sum of its six components.

Economics is `AVAILABLE` only when the config and the development,
production and schedule sections are all available; an NPV is never produced
without a timeline.

## Frontend

The **Analysis** mode shows four tabs: **Overview** (Development, Production,
Schedule, Ratios cards), **Economics** (the permanent disclaimer, the
Planning economics card with summary and cashflow table, and the
"Configure assumptions" editor), **Rules** (the Design Rulebook — a
presentation of the Phase 20D.3 design assessment) and **Layout comparison**
(the Comparable Layout Development Cost over the persisted layout-v2
catalogue); the last two are described in `docs/layout-comparison.md`
(Phase 22C, rules 203–206). The editor edits explicit values only, is
scoped to `scenarioId:economicsRevision` (a scenario change or a save resets
the draft), offers "Use demo assumptions — DEMO / SYNTHETIC ASSUMPTIONS" on
an explicit click only, and saving performs exactly one PUT followed by an
analysis reload and a layout-comparison reload — no generation, no scene
reset, no invalidation. The layout comparison consumes only `rampPerM` and
`levelAccessPerM` of this document.

Forbidden vocabulary in payload and UI: reserves, resources, recoverable ore,
proven tonnes, economic grade, optimized schedule, feasibility, bankable,
certified, statutory.
