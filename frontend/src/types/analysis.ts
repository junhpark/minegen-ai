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
