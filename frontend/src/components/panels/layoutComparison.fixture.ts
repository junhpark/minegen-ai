/** Phase 22C test fixture: a layout comparison whose COST order disagrees
 * with the persisted engineering ranking (rank 2 is the most expensive, rank
 * 3 the least) — the view must show the ranking order and never re-sort. */
import type { LayoutComparisonPayload, LayoutDevelopmentComparisonRow } from '@/types/analysis'

export const WINNER = 'SWITCHBACK-k1-p+20-CW-g0.120'
export const RANK2 = 'SWITCHBACK-k1-p+0-CW-g0.120'
export const RANK3 = 'SPIRAL-n1-CW-e+0-g0.120'

function row(
  over: Partial<LayoutDevelopmentComparisonRow> & { candidateId: string },
): LayoutDevelopmentComparisonRow {
  const family = over.candidateId.split('-')[0] ?? 'SWITCHBACK'
  return {
    family,
    catalogueRank: 1,
    selected: false,
    winner: false,
    status: 'FEASIBLE',
    mainRampLengthM: 1000,
    levelAccessLengthM: 200,
    comparableDevelopmentLengthM: 1200,
    rampCost: 10000,
    levelAccessCost: 1000,
    comparableDevelopmentCost: 11000,
    costDeltaFromWinner: 0,
    costDeltaFromSelected: 0,
    scores: { development: 1.729, geology: 0, geometry: 2.792, total: 4.520685616859209 },
    scoreDeltaFromWinner: {
      totalScoreDeltaFromWinner: 0,
      developmentScoreDelta: 0,
      geologyScoreDelta: 0,
      geometryScoreDelta: 0,
    },
    ...over,
  }
}

export const ROWS: LayoutDevelopmentComparisonRow[] = [
  row({ candidateId: WINNER, catalogueRank: 1, winner: true, selected: false }),
  row({
    candidateId: RANK2,
    catalogueRank: 2,
    selected: true,
    mainRampLengthM: 1500,
    levelAccessLengthM: 300,
    comparableDevelopmentLengthM: 1800,
    rampCost: 15000,
    levelAccessCost: 1500,
    comparableDevelopmentCost: 16500,
    costDeltaFromWinner: 5500,
    costDeltaFromSelected: 0,
    scores: { development: 1.8, geology: 0, geometry: 2.83, total: 4.6277 },
    scoreDeltaFromWinner: {
      totalScoreDeltaFromWinner: 0.107,
      developmentScoreDelta: 0.071,
      geologyScoreDelta: 0,
      geometryScoreDelta: 0.038,
    },
  }),
  row({
    candidateId: RANK3,
    catalogueRank: 3,
    mainRampLengthM: 800,
    levelAccessLengthM: 100,
    comparableDevelopmentLengthM: 900,
    rampCost: 8000,
    levelAccessCost: 500,
    comparableDevelopmentCost: 8500,
    costDeltaFromWinner: -2500,
    costDeltaFromSelected: -8000,
    scores: { development: 1.75, geology: 0, geometry: 2.8, total: 4.55 },
    scoreDeltaFromWinner: {
      totalScoreDeltaFromWinner: 0.0293,
      developmentScoreDelta: 0.021,
      geologyScoreDelta: 0,
      geometryScoreDelta: 0.008,
    },
  }),
]

export const DISCLAIMER =
  "Comparable layout development cost includes only candidate-owned main-ramp and level-access development priced at the configured planning rates. It is not the mine's total development cost, not total mine cost, not NPV, not a feasibility statement and not an optimization recommendation. Engineering ranking, winner and selection are owned by the layout authority and are never changed by cost."

export const BASIS = {
  included: ['RAMP', 'LEVEL_ACCESS'],
  excluded: [
    'DRIFT',
    'CROSSCUT',
    'RAISE',
    'SHAFT',
    'SHAFT_STATION_ACCESS',
    'PRODUCTION',
    'PROCESSING',
    'BACKFILL',
    'FIXED_OPEX',
    'CAPITAL',
    'REVENUE',
    'NPV',
  ],
}

export const CONFIGURED: LayoutComparisonPayload = {
  status: 'SUCCESS',
  availability: 'AVAILABLE',
  reason: null,
  scope: 'ACTIVE_DESIGN',
  activeSource: 'LAYOUT_V2',
  winnerId: WINNER,
  selectedCandidateId: RANK2,
  currencyCode: 'USD',
  rampRatePerM: 10,
  levelAccessRatePerM: 5,
  economicsRevision: 'eco-a',
  layoutRevision: 'lay-a',
  selectionRevision: 'sel-a',
  comparisonBasis: BASIS,
  rows: ROWS,
  disclaimer: DISCLAIMER,
}

export const NOT_CONFIGURED: LayoutComparisonPayload = {
  ...CONFIGURED,
  availability: 'NOT_CONFIGURED',
  reason: 'planning economics not configured',
  currencyCode: null,
  rampRatePerM: null,
  levelAccessRatePerM: null,
  economicsRevision: null,
  rows: ROWS.map((r) => ({
    ...r,
    rampCost: null,
    levelAccessCost: null,
    comparableDevelopmentCost: null,
    costDeltaFromWinner: null,
    costDeltaFromSelected: null,
  })),
}

export const INACTIVE: LayoutComparisonPayload = {
  ...CONFIGURED,
  scope: 'INACTIVE_LAYOUT_V2',
  activeSource: 'LEGACY',
}

export const NO_CATALOGUE: LayoutComparisonPayload = {
  ...CONFIGURED,
  availability: 'NOT_AVAILABLE',
  reason: 'layout-v2 catalogue not generated',
  scope: 'NONE',
  activeSource: 'LEGACY',
  winnerId: null,
  selectedCandidateId: null,
  layoutRevision: null,
  selectionRevision: null,
  rows: [],
}
