# Design Rulebook and Layout Development Economics (Phase 22C)

Phase 22C adds two read-only views to the Analysis workspace and one
read-only endpoint. Both are downstream projections of persisted
authoritative state (`CLAUDE.md` rules 203–206): nothing is generated,
persisted, re-ranked or re-evaluated.

## Design Rulebook (Rules tab)

The **Rules** tab is a presentation of the Phase 20D.3 design assessment
(`GET /api/v1/scenarios/{id}/design/assessment`, rule 189). There is **no
second rule evaluator**: the frontend consumes the existing
`DesignAssessmentPayload` and renders every `AssessmentCheck` with its
recorded status, authority, scope and evidence.

| authority | rendering |
| --- | --- |
| `HARD_DESIGN_RULE`, `DERIVED_VALIDATION` | `✓ SATISFIED` · `✗ NOT SATISFIED` · `? NOT EVALUATED` · `— NOT APPLICABLE` (verbatim) |
| `ADVISORY` | `Advisory satisfied` / `Advisory not satisfied` + "Design advisory — not a statutory compliance determination"; never the ✓ pass mark |
| `INFORMATIONAL` | `Info`; no pass / fail whatever the recorded status |

`NOT_EVALUATED` is never coerced into a failure. There is no overall
compliance score, percentage, "compliant: YES" or certification. Under a
LEGACY active ramp with a dormant layout-v2 catalogue the tab states that the
layout-v2 rows describe the **inactive** layout-v2 selection.

## Comparable Layout Development Cost (Layout comparison tab)

    GET /api/v1/scenarios/{id}/analysis/layout-comparison

Synchronous, read-only, no job, no persistence. For every candidate in the
persisted layout-v2 `ranking` (FEASIBLE ranked candidates, in the persisted
order):

    mainRampLengthM              = candidates[c].diagnostics.length3d
    levelAccessLengthM           = candidates[c].access.totalAccessLength
    rampCost                     = mainRampLengthM × economics.developmentCosts.rampPerM
    levelAccessCost              = levelAccessLengthM × economics.developmentCosts.levelAccessPerM
    comparableDevelopmentCost    = rampCost + levelAccessCost
    comparableDevelopmentLengthM = mainRampLengthM + levelAccessLengthM
    costDeltaFromWinner          = comparableDevelopmentCost − winner's
    costDeltaFromSelected        = comparableDevelopmentCost − selected's

Both lengths are the candidate's **persisted** catalogue facts written by
the layout search. Nothing is re-swept, re-summed from a centerline or
re-planned, and no per-candidate levels, production, network or timeline
artifact exists or is imagined. The comparison includes **only** the two
development kinds a candidate owns in the catalogue:

    comparisonBasis.included = [RAMP, LEVEL_ACCESS]
    comparisonBasis.excluded = [DRIFT, CROSSCUT, RAISE, SHAFT, SHAFT_STATION_ACCESS,
                                PRODUCTION, PROCESSING, BACKFILL, FIXED_OPEX,
                                CAPITAL, REVENUE, NPV]

The name keeps the word **Comparable**: it is not total mine development
cost, not total mine cost, not NPV, not a feasibility statement and not an
optimization recommendation.

### Payload

`LayoutComparisonPayload {status, availability, reason, scope, activeSource,
winnerId, selectedCandidateId, currencyCode, rampRatePerM,
levelAccessRatePerM, economicsRevision, layoutRevision, selectionRevision,
comparisonBasis, rows[], disclaimer}`; every row is a
`LayoutDevelopmentComparisonRow {candidateId, family, catalogueRank,
selected, winner, status, mainRampLengthM, levelAccessLengthM,
comparableDevelopmentLengthM, rampCost, levelAccessCost,
comparableDevelopmentCost, costDeltaFromWinner, costDeltaFromSelected,
scores, scoreDeltaFromWinner}`. `scores` / `scoreDeltaFromWinner` are the
Phase 20D.3 `ComparisonScores` / `ScoreDeltas` (copied verbatim, plain
`candidate − winner` subtraction through the shared assessment helpers).

| state | availability | rows |
| --- | --- | --- |
| world not generated | `NOT_AVAILABLE`, reason `world not generated` | `[]` |
| no `layout_v2.json` | `NOT_AVAILABLE`, reason `layout-v2 catalogue not generated` (200) | `[]` |
| catalogue, no `economics.json` | `NOT_CONFIGURED`, reason `planning economics not configured` | geometry rows, every cost `null` — no hidden demo default |
| catalogue + `economics.json` | `AVAILABLE` | costed rows |

`scope` follows the assessment: `ACTIVE_DESIGN` under a LAYOUT_V2 ramp
source, `INACTIVE_LAYOUT_V2` for a catalogue beside a LEGACY active ramp
(the UI says "These are inactive Layout-v2 alternatives; the active design
uses the Legacy ramp."), `NONE` without a catalogue.

### Refusals

A malformed catalogue is 409 `ARTIFACT_MALFORMED` through the shared
Phase 20D.3 grammar (`validate_catalogue_shape`: duplicate id, ranking
naming an unknown / non-FEASIBLE candidate, …) extended — for this consumer
only — by `validate_layout_economics_shape`: every ranked candidate must
carry a finite, non-negative `diagnostics.length3d` and
`access.totalAccessLength`. These fields stay optional for the design
assessment. A stale selection is 409 `LAYOUT_V2_SELECTION_STALE`; a source
moving during the projection (`scenario.json`, `arrays.npz`, the world
record, `layout_v2.json`, `layout_v2_selected.json`, `level_accesses.json`,
`ramp_source.json`, `economics.json`) is 409 `READ_SNAPSHOT_CHANGED` — the
same bound-read + snapshot + re-observe protocol as `GET …/analysis`.

### What the comparison never does

- change `ranking`, `winnerId`, `scores` or the selection, or write
  `layout_v2.json`;
- sort by cost, carry a cost rank, a "cheapest" flag or a recommendation;
- estimate per-candidate drift / crosscut / shaft length, tonnage,
  production, processing, backfill, fixed opex, revenue, duration or NPV;
- combine an engineering score with a cost into one number.

## Frontend

Analysis tabs: **Overview | Economics | Rules | Layout comparison**. The
Layout comparison tab shows a summary (ranking winner = engineering rank #1,
selected candidate, number of comparable feasible candidates, "Included cost
basis: Main ramp + level access only", the two rates), the table in the
persisted ranking order (rank, candidate · family, ramp length + cost,
access length + cost, comparable cost + length, Δ vs winner, ● winner,
"(selected)"), an optional horizontal bar chart (cost per candidate, winner ●
and selection ◆ marked) and the scores in Details. It never names an
"economic winner", "best option" or "recommended" candidate. Saving the
economics assumptions on the Economics tab is one PUT that reloads the
analysis and the layout comparison — no invalidation, no epoch bump, no
scene clear. Only `rampPerM` and `levelAccessPerM` are consumed here.

Queries are keyed on the scenario epoch, the scene identity and the
economics revision; the Rules tab shares the Layout panel's
`design-assessment` cache entry.

## Vocabulary

Forbidden in payload and UI: feasible project, bankable, economically
viable, investment grade, economic reserve, profitable mine, optimal layout,
recommended layout, certified, regulatory compliant, safe / unsafe mine.
Allowed: synthetic planning, comparable development cost, design rule,
design validation, design advisory, engineering ranking, planning
comparator, selected candidate, ranking winner.
