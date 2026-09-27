/**
 * Phase 22B — the planning-economics editor's draft helpers (pure, no React).
 *
 * The draft holds the user's EXPLICIT assumptions as strings (so a half-typed
 * number is never coerced) and is scoped to ONE identity
 * `scenarioId:economicsRevision`: another scenario, or a saved revision,
 * discards the pending edits (the Phase 21B/C review-blocker-3 contract). The
 * backend `EconomicsConfig` schema is the validation authority (422); the
 * client-side check here only decides whether the Save button is enabled and
 * never widens what the backend accepts.
 */
import type { EconomicsConfig } from '@/types/analysis'

export type DevelopmentRateKey = keyof EconomicsConfig['developmentCosts']
export type ProductionRateKey = keyof EconomicsConfig['productionCosts']
export type ScalarKey =
  | 'processingCostPerTonne'
  | 'backfillCostPerM3'
  | 'fixedOperatingCostPerDay'
  | 'grossRevenuePerMinedTonne'
  | 'initialCapitalCost'
  | 'annualDiscountRate'
  | 'cashflowBucketDays'

export interface EconomicsDraft {
  currencyCode: string
  developmentCosts: Record<DevelopmentRateKey, string>
  productionCosts: Record<ProductionRateKey, string>
  scalars: Record<ScalarKey, string>
}

export interface EconomicsDraftState {
  identity: string
  draft: EconomicsDraft
}

export const DEVELOPMENT_RATE_KEYS: readonly DevelopmentRateKey[] = [
  'rampPerM',
  'levelAccessPerM',
  'driftPerM',
  'crosscutPerM',
  'raisePerM',
  'shaftPerM',
  'shaftStationAccessPerM',
]
export const PRODUCTION_RATE_KEYS: readonly ProductionRateKey[] = [
  'longholeOpenStopingPerTonne',
  'cutAndFillPerTonne',
  'roomAndPillarPerTonne',
]
export const SCALAR_KEYS: readonly ScalarKey[] = [
  'processingCostPerTonne',
  'backfillCostPerM3',
  'fixedOperatingCostPerDay',
  'grossRevenuePerMinedTonne',
  'initialCapitalCost',
  'annualDiscountRate',
  'cashflowBucketDays',
]

export const DEVELOPMENT_RATE_LABEL: Record<DevelopmentRateKey, string> = {
  rampPerM: 'Ramp (per m)',
  levelAccessPerM: 'Level access (per m)',
  driftPerM: 'Drift (per m)',
  crosscutPerM: 'Crosscut (per m)',
  raisePerM: 'Raise (per m)',
  shaftPerM: 'Shaft (per m)',
  shaftStationAccessPerM: 'Shaft station access (per m)',
}
export const PRODUCTION_RATE_LABEL: Record<ProductionRateKey, string> = {
  longholeOpenStopingPerTonne: 'Longhole Open Stoping (per t)',
  cutAndFillPerTonne: 'Cut & Fill (per t)',
  roomAndPillarPerTonne: 'Room & Pillar (per t)',
}
export const SCALAR_LABEL: Record<ScalarKey, string> = {
  processingCostPerTonne: 'Processing (per mined t)',
  backfillCostPerM3: 'Backfill (per m³, Cut & Fill only)',
  fixedOperatingCostPerDay: 'Fixed operating (per day)',
  grossRevenuePerMinedTonne: 'Gross revenue (per mined t)',
  initialCapitalCost: 'Initial capital (day 0)',
  annualDiscountRate: 'Annual discount rate (fraction)',
  cashflowBucketDays: 'Cashflow bucket (days)',
}

/** the active method's production rate key (null for a reserved method) */
export const METHOD_RATE_KEY: Record<string, ProductionRateKey> = {
  LONGHOLE_OPEN_STOPING: 'longholeOpenStopingPerTonne',
  CUT_AND_FILL: 'cutAndFillPerTonne',
  ROOM_AND_PILLAR: 'roomAndPillarPerTonne',
}

const s = (v: number) => String(v)

export function draftFromConfig(config: EconomicsConfig): EconomicsDraft {
  return {
    currencyCode: config.currencyCode,
    developmentCosts: {
      rampPerM: s(config.developmentCosts.rampPerM),
      levelAccessPerM: s(config.developmentCosts.levelAccessPerM),
      driftPerM: s(config.developmentCosts.driftPerM),
      crosscutPerM: s(config.developmentCosts.crosscutPerM),
      raisePerM: s(config.developmentCosts.raisePerM),
      shaftPerM: s(config.developmentCosts.shaftPerM),
      shaftStationAccessPerM: s(config.developmentCosts.shaftStationAccessPerM),
    },
    productionCosts: {
      longholeOpenStopingPerTonne: s(config.productionCosts.longholeOpenStopingPerTonne),
      cutAndFillPerTonne: s(config.productionCosts.cutAndFillPerTonne),
      roomAndPillarPerTonne: s(config.productionCosts.roomAndPillarPerTonne),
    },
    scalars: {
      processingCostPerTonne: s(config.processingCostPerTonne),
      backfillCostPerM3: s(config.backfillCostPerM3),
      fixedOperatingCostPerDay: s(config.fixedOperatingCostPerDay),
      grossRevenuePerMinedTonne: s(config.grossRevenuePerMinedTonne),
      initialCapitalCost: s(config.initialCapitalCost),
      annualDiscountRate: s(config.annualDiscountRate),
      cashflowBucketDays: s(config.cashflowBucketDays),
    },
  }
}

/** every field empty: the user fills each assumption explicitly */
export function emptyDraft(): EconomicsDraft {
  return {
    currencyCode: '',
    developmentCosts: {
      rampPerM: '',
      levelAccessPerM: '',
      driftPerM: '',
      crosscutPerM: '',
      raisePerM: '',
      shaftPerM: '',
      shaftStationAccessPerM: '',
    },
    productionCosts: {
      longholeOpenStopingPerTonne: '',
      cutAndFillPerTonne: '',
      roomAndPillarPerTonne: '',
    },
    scalars: {
      processingCostPerTonne: '',
      backfillCostPerM3: '',
      fixedOperatingCostPerDay: '',
      grossRevenuePerMinedTonne: '',
      initialCapitalCost: '',
      annualDiscountRate: '',
      cashflowBucketDays: '',
    },
  }
}

/**
 * DEMO / SYNTHETIC ASSUMPTIONS — round illustrative planning numbers a user
 * may load with one EXPLICIT click. They are never applied automatically,
 * never a default of the backend, and carry no calibration or market
 * meaning.
 */
export const DEMO_ASSUMPTIONS: EconomicsConfig = {
  version: 1,
  currencyCode: 'USD',
  developmentCosts: {
    rampPerM: 6000,
    levelAccessPerM: 5000,
    driftPerM: 4500,
    crosscutPerM: 4500,
    raisePerM: 5500,
    shaftPerM: 25000,
    shaftStationAccessPerM: 5000,
  },
  productionCosts: {
    longholeOpenStopingPerTonne: 35,
    cutAndFillPerTonne: 60,
    roomAndPillarPerTonne: 30,
  },
  processingCostPerTonne: 25,
  backfillCostPerM3: 40,
  fixedOperatingCostPerDay: 20000,
  grossRevenuePerMinedTonne: 120,
  initialCapitalCost: 20000000,
  annualDiscountRate: 0.08,
  cashflowBucketDays: 30,
}

/** the persisted config as the editor's starting draft (empty when absent) */
export function persistedDraft(config: EconomicsConfig | null): EconomicsDraft {
  return config ? draftFromConfig(config) : emptyDraft()
}

export function reconcileEconomicsDraft(
  state: EconomicsDraftState,
  identity: string,
  persisted: EconomicsDraft,
): EconomicsDraftState {
  return state.identity === identity ? state : { identity, draft: persisted }
}

export function economicsDraftIsDirty(draft: EconomicsDraft, persisted: EconomicsDraft): boolean {
  return JSON.stringify(draft) !== JSON.stringify(persisted)
}

const CURRENCY = /^[A-Z]{3}$/

function nonNegative(text: string): number | null {
  if (text.trim() === '') return null
  const v = Number(text)
  return Number.isFinite(v) && v >= 0 ? v : null
}

/**
 * The draft as a submittable `EconomicsConfig`, or the list of field labels
 * that are empty or invalid. The rules mirror the backend schema (finite,
 * non-negative, bucket > 0, ISO-style upper-case 3-letter currency) and
 * decide only whether Save is enabled; the backend stays the authority.
 */
export function draftToConfig(
  draft: EconomicsDraft,
): { config: EconomicsConfig; problems: [] } | { config: null; problems: string[] } {
  const problems: string[] = []
  if (!CURRENCY.test(draft.currencyCode)) problems.push('Currency code (3 upper-case letters)')
  const dev = {} as Record<DevelopmentRateKey, number>
  for (const k of DEVELOPMENT_RATE_KEYS) {
    const v = nonNegative(draft.developmentCosts[k])
    if (v === null) problems.push(DEVELOPMENT_RATE_LABEL[k])
    else dev[k] = v
  }
  const prod = {} as Record<ProductionRateKey, number>
  for (const k of PRODUCTION_RATE_KEYS) {
    const v = nonNegative(draft.productionCosts[k])
    if (v === null) problems.push(PRODUCTION_RATE_LABEL[k])
    else prod[k] = v
  }
  const scalars = {} as Record<ScalarKey, number>
  for (const k of SCALAR_KEYS) {
    const v = nonNegative(draft.scalars[k])
    if (v === null || (k === 'cashflowBucketDays' && v <= 0)) problems.push(SCALAR_LABEL[k])
    else scalars[k] = v
  }
  if (problems.length > 0) return { config: null, problems }
  return {
    config: {
      version: 1,
      currencyCode: draft.currencyCode,
      developmentCosts: dev,
      productionCosts: prod,
      ...scalars,
    },
    problems: [],
  }
}

/** identity of the editor's draft: the scenario and the SAVED revision */
export function economicsIdentity(scenarioId: string | null, revision: string | null): string {
  return `${scenarioId ?? ''}:${revision ?? 'unconfigured'}`
}
