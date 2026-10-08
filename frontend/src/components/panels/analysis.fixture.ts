/** Phase 22A/B test fixture: the hand-built mine of the backend tests
 * (`backend/tests/analysis_support.py`) as the API emits it. */
import type {
  EconomicsConfig,
  MineAnalysisPayload,
  SensitivityCase,
  SensitivityPayload,
  TimeseriesPayload,
  WhatIfOutcome,
} from '@/types/analysis'
import { WHAT_IF_LABEL } from '@/types/analysis'

export const CONFIG: EconomicsConfig = {
  version: 1,
  currencyCode: 'USD',
  developmentCosts: {
    rampPerM: 10,
    levelAccessPerM: 8,
    driftPerM: 6,
    crosscutPerM: 5,
    raisePerM: 7,
    shaftPerM: 0,
    shaftStationAccessPerM: 0,
  },
  productionCosts: {
    longholeOpenStopingPerTonne: 2,
    cutAndFillPerTonne: 3,
    roomAndPillarPerTonne: 4,
  },
  processingCostPerTonne: 1,
  backfillCostPerM3: 0.5,
  fixedOperatingCostPerDay: 10,
  grossRevenuePerMinedTonne: 5,
  initialCapitalCost: 500,
  annualDiscountRate: 0.1,
  cashflowBucketDays: 30,
}

export const DISCLAIMER =
  'Synthetic planning economics. Not a resource/reserve estimate or feasibility study.'

const bucket = (
  index: number,
  net: number,
  cumulative: number,
  over: Partial<MineAnalysisPayload['economics']['cashflow'][number]> = {},
) => ({
  index,
  startDay: index * 30,
  endDay: (index + 1) * 30,
  developmentCost: 0,
  productionMiningCost: 0,
  processingCost: 0,
  backfillCost: 0,
  fixedOperatingCost: 300,
  initialCapitalCost: 0,
  revenue: 0,
  netCashflow: net,
  cumulativeCashflow: cumulative,
  discountedNetCashflow: net,
  ...over,
})

export const FULL: MineAnalysisPayload = {
  status: 'SUCCESS',
  sources: {
    scenarioRevision: 's',
    networkRevision: 'n',
    productionRevision: 'p',
    timelineRevision: 't',
    economicsRevision: 'e',
  },
  development: {
    availability: 'AVAILABLE',
    reason: null,
    categories: [
      { edgeType: 'RAMP', edgeCount: 2, totalLengthM: 150, grossExcavationVolumeM3: 3000 },
      { edgeType: 'LEVEL_ACCESS', edgeCount: 1, totalLengthM: 30, grossExcavationVolumeM3: 600 },
      { edgeType: 'DRIFT', edgeCount: 1, totalLengthM: 40, grossExcavationVolumeM3: 640 },
      { edgeType: 'CROSSCUT', edgeCount: 1, totalLengthM: 10, grossExcavationVolumeM3: 160 },
      { edgeType: 'RAISE', edgeCount: 0, totalLengthM: 0, grossExcavationVolumeM3: 0 },
      { edgeType: 'SHAFT', edgeCount: 0, totalLengthM: 0, grossExcavationVolumeM3: 0 },
      {
        edgeType: 'SHAFT_STATION_ACCESS',
        edgeCount: 0,
        totalLengthM: 0,
        grossExcavationVolumeM3: 0,
      },
    ],
    totals: {
      totalDevelopmentLengthM: 230,
      grossDevelopmentVolumeM3: 4400,
      rampLengthM: 150,
      levelAccessLengthM: 30,
      driftLengthM: 40,
      crosscutLengthM: 10,
      shaftLengthM: 0,
      shaftStationAccessLengthM: 0,
    },
    crossCheck: { toleranceM: 1e-6, maxLengthDifferenceM: 0, maxCountDifference: 0 },
  },
  production: {
    availability: 'AVAILABLE',
    reason: null,
    method: 'LONGHOLE_OPEN_STOPING',
    productionObjectCount: 2,
    totalProductionVolumeM3: 1600,
    totalPlannedMinedTonnes: 4000,
    weightedMeanGradeProxy: 2.5,
    detail: { kind: 'LONGHOLE_OPEN_STOPING', stopeCount: 2, levelIntervalCount: 1 },
  },
  schedule: {
    availability: 'AVAILABLE',
    reason: null,
    taskCount: 15,
    developmentTaskCount: 5,
    productionTaskCount: 10,
    startDay: 0,
    endDay: 120,
    mineDurationDays: 120,
    rampCompletionDay: 30,
    firstProductionDay: 50,
  },
  ratios: {
    availability: 'AVAILABLE',
    reason: null,
    developmentMetresPerKt: 57.5,
    grossDevelopmentM3PerKt: 1100,
  },
  economics: {
    availability: 'AVAILABLE',
    reason: null,
    economicsRevision: 'e',
    currencyCode: 'USD',
    cashflowBucketDays: 30,
    annualDiscountRate: 0.1,
    revenueModel: 'GROSS_REVENUE_PER_MINED_TONNE',
    npvConvention: 'MID_BUCKET_MIDPOINT',
    summary: {
      developmentCost: 2030,
      productionMiningCost: 8000,
      processingCost: 4000,
      backfillCost: 0,
      fixedOperatingCost: 1200,
      initialCapitalCost: 500,
      totalCost: 15730,
      totalRevenue: 20000,
      undiscountedNetCashflow: 4270,
      npv: 4038.51,
    },
    cashflow: [
      bucket(0, -2540, -2540, { developmentCost: 1740, initialCapitalCost: 500 }),
      bucket(1, -2590, -5130, { developmentCost: 290, productionMiningCost: 2000 }),
      bucket(2, -2300, -7430, { productionMiningCost: 6000, processingCost: 1000, revenue: 5000 }),
      bucket(3, 11700, 4270, { processingCost: 3000, revenue: 15000 }),
    ],
    planningIrr: {
      status: 'DEFINED',
      annualRate: 0.1234,
      reason: null,
      convention: 'MID_BUCKET_MIDPOINT',
      bracket: [-0.99, 10],
      name: 'Planning IRR',
    },
    disclaimer: DISCLAIMER,
  },
}

/** a fresh scenario: nothing generated, nothing configured */
export const EMPTY: MineAnalysisPayload = {
  status: 'SUCCESS',
  sources: {
    scenarioRevision: 's',
    networkRevision: null,
    productionRevision: null,
    timelineRevision: null,
    economicsRevision: null,
  },
  development: {
    availability: 'NOT_AVAILABLE',
    reason: 'network.json not generated',
    categories: [],
    totals: null,
    crossCheck: null,
  },
  production: {
    availability: 'NOT_AVAILABLE',
    reason: 'stopes.json not generated',
    method: null,
    productionObjectCount: null,
    totalProductionVolumeM3: null,
    totalPlannedMinedTonnes: null,
    weightedMeanGradeProxy: null,
    detail: null,
  },
  schedule: {
    availability: 'NOT_AVAILABLE',
    reason: 'timeline.json not generated',
    taskCount: null,
    developmentTaskCount: null,
    productionTaskCount: null,
    startDay: null,
    endDay: null,
    mineDurationDays: null,
    rampCompletionDay: null,
    firstProductionDay: null,
  },
  ratios: {
    availability: 'NOT_AVAILABLE',
    reason: 'requires development and production',
    developmentMetresPerKt: null,
    grossDevelopmentM3PerKt: null,
  },
  economics: {
    availability: 'NOT_CONFIGURED',
    reason: 'Planning economics is not configured.',
    economicsRevision: null,
    currencyCode: null,
    cashflowBucketDays: null,
    annualDiscountRate: null,
    revenueModel: 'GROSS_REVENUE_PER_MINED_TONNE',
    npvConvention: 'MID_BUCKET_MIDPOINT',
    summary: null,
    cashflow: [],
    planningIrr: {
      status: 'NOT_CONFIGURED',
      annualRate: null,
      reason: null,
      convention: 'MID_BUCKET_MIDPOINT',
      bracket: [-0.99, 10],
      name: 'Planning IRR',
    },
    disclaimer: DISCLAIMER,
  },
}

// --------------------------------------------------------------------------- //
// Hardening PR-2 H3 §8 — sensitivity / what-if and time-series fixtures
// --------------------------------------------------------------------------- //

const SOURCES = {
  scenarioRevision: 's',
  networkRevision: 'n',
  productionRevision: 'p',
  timelineRevision: 't',
  economicsRevision: 'e',
}

const UNIT_FACTORS = {
  grossRevenuePerMinedTonne: 1,
  developmentCost: 1,
  miningCost: 1,
  processingCost: 1,
  backfillCost: 1,
  initialCapital: 1,
  discountRate: 1,
  developmentRate: 1,
  miningRate: 1,
}

export const BASE_OUTCOME: WhatIfOutcome = {
  label: WHAT_IF_LABEL,
  status: 'AVAILABLE',
  reason: null,
  factors: UNIT_FACTORS,
  scheduleRebuilt: false,
  planningNpv: 4038.51,
  planningIrr: FULL.economics.planningIrr,
  mineDurationDays: 120,
  firstProductionDay: 50,
  endDay: 120,
  undiscountedNetCashflow: 4270,
  npvDelta: 0,
  mineDurationDeltaDays: 0,
  firstProductionDeltaDays: 0,
}

const PARAMETERS: SensitivityPayload['parameters'] = [
  { key: 'grossRevenuePerMinedTonne', label: 'Gross revenue per mined tonne', kind: 'ECONOMIC' },
  { key: 'developmentCost', label: 'Development cost rates', kind: 'ECONOMIC' },
  { key: 'miningCost', label: 'Production mining cost rate', kind: 'ECONOMIC' },
  { key: 'processingCost', label: 'Processing cost rate', kind: 'ECONOMIC' },
  { key: 'backfillCost', label: 'Backfill cost rate', kind: 'ECONOMIC' },
  { key: 'initialCapital', label: 'Initial capital cost', kind: 'ECONOMIC' },
  { key: 'discountRate', label: 'Annual discount rate', kind: 'ECONOMIC' },
  { key: 'developmentRate', label: 'Development advance rates', kind: 'SCHEDULE' },
  { key: 'miningRate', label: 'Production mining rate', kind: 'SCHEDULE' },
]

const sensitivityCase = (
  parameter: SensitivityCase['parameter'],
  pct: number,
  npvDelta: number,
  over: Partial<WhatIfOutcome> = {},
): SensitivityCase => {
  const p = PARAMETERS.find((q) => q.key === parameter)
  if (!p) throw new Error(parameter)
  return {
    parameter,
    label: p.label,
    kind: p.kind,
    perturbationPct: pct,
    factor: 1 + pct / 100,
    outcome: {
      ...BASE_OUTCOME,
      factors: { ...UNIT_FACTORS, [parameter]: 1 + pct / 100 },
      scheduleRebuilt: p.kind === 'SCHEDULE',
      planningNpv: 4038.51 + npvDelta,
      npvDelta,
      ...over,
    },
  }
}

export const SENSITIVITY: SensitivityPayload = {
  status: 'SUCCESS',
  label: WHAT_IF_LABEL,
  notice: 'Every figure on this page is a what-if projection, never a scenario value.',
  sources: SOURCES,
  availability: 'AVAILABLE',
  reason: null,
  revenueModel: 'GROSS_REVENUE_PER_MINED_TONNE',
  perturbationsPct: [-30, 30],
  parameters: PARAMETERS,
  base: BASE_OUTCOME,
  cases: [
    sensitivityCase('grossRevenuePerMinedTonne', -30, -5700),
    sensitivityCase('grossRevenuePerMinedTonne', 30, 5700),
    sensitivityCase('miningRate', -30, -310.25, {
      mineDurationDays: 150,
      mineDurationDeltaDays: 30,
    }),
    sensitivityCase('miningRate', 30, 180.5, {
      mineDurationDays: 100,
      mineDurationDeltaDays: -20,
    }),
  ],
  disclaimer: DISCLAIMER,
}

export const SENSITIVITY_NOT_CONFIGURED: SensitivityPayload = {
  ...SENSITIVITY,
  availability: 'NOT_CONFIGURED',
  reason: 'Planning economics is not configured.',
  base: {
    ...BASE_OUTCOME,
    status: 'NOT_AVAILABLE',
    reason: 'Planning economics is not configured.',
    planningNpv: null,
    planningIrr: EMPTY.economics.planningIrr,
    undiscountedNetCashflow: null,
    npvDelta: null,
  },
  cases: [],
}

const quantities = (dev: number, prod: number, cost: number | null, revenue: number | null) => ({
  developmentLengthM: dev,
  developmentExcavationM3: dev * 20,
  developmentTonnes: null,
  productionTonnes: prod,
  backfillM3: 0,
  cementedBackfillM3: 0,
  cost,
  revenue,
  netCashflow: cost === null || revenue === null ? null : revenue - cost,
})

export const TIMESERIES: TimeseriesPayload = {
  status: 'SUCCESS',
  sources: SOURCES,
  availability: 'AVAILABLE',
  reason: null,
  bucketDays: 30,
  bucketCount: 4,
  startDay: 0,
  endDay: 120,
  developmentTonnes: {
    status: 'NOT_CONFIGURED',
    hostRockDensity: null,
    reason: 'scenario.geology.hostRockDensity is not declared',
  },
  retained: {
    availability: 'NOT_AVAILABLE',
    reason: 'no retained pillars for this method',
    pillarCount: null,
    pillarVolumeM3: null,
    pillarTonnesEquivalent: null,
  },
  economics: {
    availability: 'AVAILABLE',
    reason: null,
    currencyCode: 'USD',
    economicsRevision: 'e',
  },
  totals: quantities(230, 4000, 15730, 20000),
  buckets: [
    {
      index: 0,
      startDay: 0,
      endDay: 30,
      bucket: quantities(174, 0, 2540, 0),
      cumulative: quantities(174, 0, 2540, 0),
      cumulativeCashflow: -2540,
    },
    {
      index: 1,
      startDay: 30,
      endDay: 60,
      bucket: quantities(56, 1000, 2590, 0),
      cumulative: quantities(230, 1000, 5130, 0),
      cumulativeCashflow: -5130,
    },
    {
      index: 2,
      startDay: 60,
      endDay: 90,
      bucket: quantities(0, 2000, 7300, 5000),
      cumulative: quantities(230, 3000, 12430, 5000),
      cumulativeCashflow: -7430,
    },
    {
      index: 3,
      startDay: 90,
      endDay: 120,
      bucket: quantities(0, 1000, 3300, 15000),
      cumulative: quantities(230, 4000, 15730, 20000),
      cumulativeCashflow: 4270,
    },
  ],
  developmentRockVocabulary: 'Excavated development rock',
  allocation: 'LINEAR_OVER_TASK_WINDOW',
  disclaimer: DISCLAIMER,
}

/** the hardening PR-2 H3 §8 body props shared by the Analysis-panel tests */
export const H3_BODY_PROPS = {
  sensitivity: null,
  sensitivityError: null,
  sensitivityLoading: false,
  timeseries: null,
  timeseriesError: null,
  timeseriesLoading: false,
  timeline: null,
  whatIf: null,
  whatIfPending: false,
  whatIfError: null,
  onWhatIf: () => undefined,
} as const
