/**
 * Phase 22A/B — the mine analysis read model and the planning-economics
 * assumption document, as the backend emits them (`analysis/models.py`,
 * `analysis/economics.py`). Read-only DTOs: the frontend renders these
 * values and computes no engineering or economic quantity itself.
 */
import type { EdgeType, MiningMethodType } from './enums'

export type Availability = 'AVAILABLE' | 'NOT_AVAILABLE' | 'NOT_CONFIGURED'

export interface AnalysisSources {
  scenarioRevision: string
  networkRevision: string | null
  productionRevision: string | null
  timelineRevision: string | null
  economicsRevision: string | null
}

export interface DevelopmentCategory {
  edgeType: EdgeType
  edgeCount: number
  totalLengthM: number
  grossExcavationVolumeM3: number
}

export interface DevelopmentTotals {
  totalDevelopmentLengthM: number
  grossDevelopmentVolumeM3: number
  rampLengthM: number
  levelAccessLengthM: number
  driftLengthM: number
  crosscutLengthM: number
  shaftLengthM: number
  shaftStationAccessLengthM: number
}

export interface DevelopmentSection {
  availability: Availability
  reason: string | null
  categories: DevelopmentCategory[]
  totals: DevelopmentTotals | null
  crossCheck: {
    toleranceM: number
    maxLengthDifferenceM: number
    maxCountDifference: number
  } | null
}

export interface LongholeProductionDetail {
  kind: 'LONGHOLE_OPEN_STOPING'
  stopeCount: number
  levelIntervalCount: number
}

export interface CutFillProductionDetail {
  kind: 'CUT_AND_FILL'
  cutCount: number
  liftCount: number
  backfillCount: number
  totalBackfillVolumeM3: number
}

export interface RoomPillarProductionDetail {
  kind: 'ROOM_AND_PILLAR'
  roomCount: number
  extractionUnitCount: number
  pillarCount: number
  headingCount: number
  benchCount: number
  retainedPillarVolumeM3: number
  retainedPillarTonnesEquivalent: number
  geometricExtractionFraction: number
}

export type ProductionDetail =
  LongholeProductionDetail | CutFillProductionDetail | RoomPillarProductionDetail

export interface ProductionSection {
  availability: Availability
  reason: string | null
  method: MiningMethodType | null
  productionObjectCount: number | null
  totalProductionVolumeM3: number | null
  totalPlannedMinedTonnes: number | null
  weightedMeanGradeProxy: number | null
  detail: ProductionDetail | null
}

export interface ScheduleSection {
  availability: Availability
  reason: string | null
  taskCount: number | null
  developmentTaskCount: number | null
  productionTaskCount: number | null
  startDay: number | null
  endDay: number | null
  mineDurationDays: number | null
  rampCompletionDay: number | null
  firstProductionDay: number | null
}

export interface PlanningRatios {
  availability: Availability
  reason: string | null
  developmentMetresPerKt: number | null
  grossDevelopmentM3PerKt: number | null
}

export interface EconomicsSummary {
  developmentCost: number
  productionMiningCost: number
  processingCost: number
  backfillCost: number
  fixedOperatingCost: number
  initialCapitalCost: number
  totalCost: number
  totalRevenue: number
  undiscountedNetCashflow: number
  npv: number
}

export interface CashflowBucket {
  index: number
  startDay: number
  endDay: number
  developmentCost: number
  productionMiningCost: number
  processingCost: number
  backfillCost: number
  fixedOperatingCost: number
  initialCapitalCost: number
  revenue: number
  netCashflow: number
  cumulativeCashflow: number
  discountedNetCashflow: number
}

/** hardening PR-2 H3 §8.2 — Planning IRR under the mid-bucket convention,
 * typed: DEFINED | NOT_DEFINED (NO_SIGN_CHANGE | MULTIPLE_SIGN_CHANGES) |
 * NOT_CONFIGURED; never NaN / Infinity */
export interface PlanningIrr {
  status: 'DEFINED' | 'NOT_DEFINED' | 'NOT_CONFIGURED'
  annualRate: number | null
  reason: 'NO_SIGN_CHANGE' | 'MULTIPLE_SIGN_CHANGES' | null
  convention: 'MID_BUCKET_MIDPOINT'
  bracket: [number, number]
  name: 'Planning IRR'
}

export interface EconomicsSection {
  availability: Availability
  reason: string | null
  economicsRevision: string | null
  currencyCode: string | null
  cashflowBucketDays: number | null
  annualDiscountRate: number | null
  revenueModel: 'GROSS_REVENUE_PER_MINED_TONNE'
  npvConvention: 'MID_BUCKET_MIDPOINT'
  summary: EconomicsSummary | null
  cashflow: CashflowBucket[]
  planningIrr: PlanningIrr
  disclaimer: string
}

export interface MineAnalysisPayload {
  status: 'SUCCESS'
  sources: AnalysisSources
  development: DevelopmentSection
  production: ProductionSection
  schedule: ScheduleSection
  ratios: PlanningRatios
  economics: EconomicsSection
}

// --------------------------------------------------------------------------- //
// economics.json (user-authored, beside scenario.json — never derived)
// --------------------------------------------------------------------------- //

export interface DevelopmentCostRates {
  rampPerM: number
  levelAccessPerM: number
  driftPerM: number
  crosscutPerM: number
  raisePerM: number
  shaftPerM: number
  shaftStationAccessPerM: number
}

export interface ProductionCostRates {
  longholeOpenStopingPerTonne: number
  cutAndFillPerTonne: number
  roomAndPillarPerTonne: number
}

export interface EconomicsConfig {
  version: 1
  currencyCode: string
  developmentCosts: DevelopmentCostRates
  productionCosts: ProductionCostRates
  processingCostPerTonne: number
  backfillCostPerM3: number
  fixedOperatingCostPerDay: number
  grossRevenuePerMinedTonne: number
  initialCapitalCost: number
  annualDiscountRate: number
  cashflowBucketDays: number
}

export interface EconomicsConfigResponse {
  configured: boolean
  revision: string | null
  config: EconomicsConfig | null
}

// --------------------------------------------------------------------------- //
// Phase 22C — Layout Development Economics (rules 204–206): read-only mirror
// of GET …/analysis/layout-comparison. Every length is the persisted
// candidate fact, every cost is backend `length × rate`; the frontend never
// sums a centerline, never re-ranks and never derives a cost.
// --------------------------------------------------------------------------- //

import type { ComparisonScores, LayoutScope, ScoreDeltas } from './scene'

export type LayoutComparisonAvailability = 'AVAILABLE' | 'NOT_AVAILABLE' | 'NOT_CONFIGURED'

export interface LayoutComparisonBasis {
  included: string[]
  excluded: string[]
}

export interface LayoutDevelopmentComparisonRow {
  candidateId: string
  family: string
  /** the persisted layout rank (1 = ranking winner) — the ONLY rank */
  catalogueRank: number | null
  selected: boolean
  winner: boolean
  status: 'FEASIBLE' | 'INFEASIBLE' | 'NOT_VALIDATED'
  mainRampLengthM: number
  levelAccessLengthM: number
  comparableDevelopmentLengthM: number
  rampCost: number | null
  levelAccessCost: number | null
  comparableDevelopmentCost: number | null
  costDeltaFromWinner: number | null
  costDeltaFromSelected: number | null
  scores: ComparisonScores | null
  scoreDeltaFromWinner: ScoreDeltas | null
}

export interface LayoutComparisonPayload {
  status: 'SUCCESS'
  availability: LayoutComparisonAvailability
  reason: string | null
  scope: LayoutScope
  activeSource: string
  winnerId: string | null
  selectedCandidateId: string | null
  currencyCode: string | null
  rampRatePerM: number | null
  levelAccessRatePerM: number | null
  economicsRevision: string | null
  layoutRevision: string | null
  selectionRevision: string | null
  comparisonBasis: LayoutComparisonBasis
  /** persisted ranking order — never sorted by cost */
  rows: LayoutDevelopmentComparisonRow[]
  disclaimer: string
}

// --------------------------------------------------------------------------- //
// Hardening PR-2 H3 §6 — GET …/analysis/timeseries?bucketDays=<n>
// --------------------------------------------------------------------------- //

/** one bucket's quantities, or the running cumulative; `null` money cells
 * mean "not configured", `null` development tonnes mean "no host-rock density
 * declared" — never zero */
export interface TimeseriesQuantities {
  developmentLengthM: number
  developmentExcavationM3: number
  developmentTonnes: number | null
  productionTonnes: number
  backfillM3: number
  cementedBackfillM3: number
  cost: number | null
  revenue: number | null
  netCashflow: number | null
}

export interface TimeseriesBucket {
  index: number
  startDay: number
  endDay: number
  bucket: TimeseriesQuantities
  cumulative: TimeseriesQuantities
  cumulativeCashflow: number | null
}

export interface TimeseriesPayload {
  status: 'SUCCESS'
  sources: AnalysisSources
  availability: Availability
  reason: string | null
  bucketDays: number
  bucketCount: number
  startDay: number | null
  endDay: number | null
  developmentTonnes: {
    status: 'AVAILABLE' | 'NOT_CONFIGURED'
    hostRockDensity: number | null
    reason: string | null
  }
  retained: {
    availability: Availability
    reason: string | null
    pillarCount: number | null
    pillarVolumeM3: number | null
    pillarTonnesEquivalent: number | null
  }
  economics: {
    availability: Availability
    reason: string | null
    currencyCode: string | null
    economicsRevision: string | null
  }
  totals: TimeseriesQuantities | null
  buckets: TimeseriesBucket[]
  developmentRockVocabulary: 'Excavated development rock'
  allocation: 'LINEAR_OVER_TASK_WINDOW'
  disclaimer: string
}

// --------------------------------------------------------------------------- //
// Hardening PR-2 H3 §8.3 — sensitivity / what-if (READ-ONLY, never persisted)
// --------------------------------------------------------------------------- //

export const WHAT_IF_LABEL = 'WHAT-IF OVERRIDE — NOT SCENARIO VALUE'

/** multiplicative overrides, 1.0 = the scenario / economics value */
export interface WhatIfFactors {
  grossRevenuePerMinedTonne?: number
  developmentCost?: number
  miningCost?: number
  processingCost?: number
  backfillCost?: number
  initialCapital?: number
  discountRate?: number
  developmentRate?: number
  miningRate?: number
}

export type SensitivityParameterKey = keyof Required<WhatIfFactors>
export type SensitivityParameterKind = 'ECONOMIC' | 'SCHEDULE'

export interface WhatIfOutcome {
  label: typeof WHAT_IF_LABEL
  status: 'AVAILABLE' | 'NOT_AVAILABLE' | 'FAILED'
  reason: string | null
  factors: Required<WhatIfFactors>
  scheduleRebuilt: boolean
  planningNpv: number | null
  planningIrr: PlanningIrr
  mineDurationDays: number | null
  firstProductionDay: number | null
  endDay: number | null
  undiscountedNetCashflow: number | null
  npvDelta: number | null
  mineDurationDeltaDays: number | null
  firstProductionDeltaDays: number | null
}

export interface SensitivityCase {
  parameter: SensitivityParameterKey
  label: string
  kind: SensitivityParameterKind
  perturbationPct: number
  factor: number
  outcome: WhatIfOutcome
}

export interface SensitivityPayload {
  status: 'SUCCESS'
  label: typeof WHAT_IF_LABEL
  notice: string
  sources: AnalysisSources
  availability: Availability
  reason: string | null
  revenueModel: 'GROSS_REVENUE_PER_MINED_TONNE'
  perturbationsPct: number[]
  parameters: { key: SensitivityParameterKey; label: string; kind: SensitivityParameterKind }[]
  base: WhatIfOutcome
  cases: SensitivityCase[]
  disclaimer: string
}
