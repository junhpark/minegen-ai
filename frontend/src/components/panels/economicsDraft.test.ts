/**
 * Phase 22B — the assumptions editor's draft: identity-scoped
 * (`scenarioId:economicsRevision`), explicit values only, client-side
 * validation mirrors the backend schema without widening it.
 */
import { describe, expect, it } from 'vitest'
import { CONFIG } from './analysis.fixture'
import {
  DEMO_ASSUMPTIONS,
  draftFromConfig,
  draftToConfig,
  economicsDraftIsDirty,
  economicsIdentity,
  emptyDraft,
  persistedDraft,
  reconcileEconomicsDraft,
} from './economicsDraft'

describe('draft ⇄ config', () => {
  it('round-trips the persisted config exactly', () => {
    const d = draftFromConfig(CONFIG)
    expect(draftToConfig(d)).toEqual({ config: CONFIG, problems: [] })
    expect(economicsDraftIsDirty(d, persistedDraft(CONFIG))).toBe(false)
  })

  it('an unconfigured scenario starts empty and is not submittable', () => {
    const d = persistedDraft(null)
    expect(d).toEqual(emptyDraft())
    const parsed = draftToConfig(d)
    expect(parsed.config).toBeNull()
    expect(parsed.problems.length).toBeGreaterThan(10)
  })

  it('rejects what the backend rejects: currency shape, negatives, non-finite, zero bucket', () => {
    const base = draftFromConfig(CONFIG)
    expect(draftToConfig({ ...base, currencyCode: 'usd' }).problems).toEqual([
      'Currency code (3 upper-case letters)',
    ])
    expect(
      draftToConfig({ ...base, scalars: { ...base.scalars, processingCostPerTonne: '-1' } })
        .problems,
    ).toEqual(['Processing (per mined t)'])
    expect(
      draftToConfig({ ...base, scalars: { ...base.scalars, initialCapitalCost: 'abc' } }).problems,
    ).toEqual(['Initial capital (day 0)'])
    expect(
      draftToConfig({ ...base, scalars: { ...base.scalars, cashflowBucketDays: '0' } }).problems,
    ).toEqual(['Cashflow bucket (days)'])
    expect(
      draftToConfig({
        ...base,
        developmentCosts: { ...base.developmentCosts, shaftPerM: '' },
      }).problems,
    ).toEqual(['Shaft (per m)'])
  })

  it('the demo assumptions are a valid explicit config, never applied implicitly', () => {
    expect(draftToConfig(draftFromConfig(DEMO_ASSUMPTIONS)).config).toEqual(DEMO_ASSUMPTIONS)
    expect(persistedDraft(null)).not.toEqual(draftFromConfig(DEMO_ASSUMPTIONS))
  })
})

describe('draft identity', () => {
  it('is scenario + saved revision', () => {
    expect(economicsIdentity('a', 'r1')).toBe('a:r1')
    expect(economicsIdentity('a', null)).toBe('a:unconfigured')
    expect(economicsIdentity(null, null)).toBe(':unconfigured')
  })

  it('keeps pending edits under the same identity and discards them across scenarios or saves', () => {
    const persisted = persistedDraft(CONFIG)
    const edited = { ...persisted, currencyCode: 'EUR' }
    const state = { identity: 'a:r1', draft: edited }
    expect(reconcileEconomicsDraft(state, 'a:r1', persisted).draft).toBe(edited)
    // another scenario → its own persisted assumptions
    expect(reconcileEconomicsDraft(state, 'b:unconfigured', emptyDraft()).draft).toEqual(
      emptyDraft(),
    )
    // a successful save advances the revision → the draft reconciles to what was saved
    const saved = { ...CONFIG, currencyCode: 'EUR' }
    expect(reconcileEconomicsDraft(state, 'a:r2', persistedDraft(saved)).draft).toEqual(
      persistedDraft(saved),
    )
  })
})
