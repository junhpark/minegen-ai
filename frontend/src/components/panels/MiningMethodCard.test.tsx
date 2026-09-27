/**
 * Phase 21B/C — the method card edits explicit parameters only: defaults
 * come from the backend registry table, the draft starts at the persisted
 * configuration, and Apply is only offered for a real change.
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { miningDraftFor, miningDraftIsDirty, persistedMining } from './miningDraft'
import { LONGHOLE } from './miningMethod.fixture'
import { MiningMethodCard } from './MiningMethodCard'

describe('miningDraftFor', () => {
  it('starts from the persisted configuration', () => {
    expect(persistedMining(LONGHOLE)).toEqual({
      method: 'LONGHOLE_OPEN_STOPING',
      sublevelInterval: 25,
      stopeLength: 20,
      minimumPillar: 15,
    })
    expect(miningDraftIsDirty(persistedMining(LONGHOLE), persistedMining(LONGHOLE))).toBe(false)
  })

  it('switching the method takes the registry defaults, never a frontend constant', () => {
    const cf = miningDraftFor(LONGHOLE, 'CUT_AND_FILL', persistedMining(LONGHOLE))
    expect(cf.methodParameters).toEqual({ kind: 'CUT_AND_FILL', liftHeightM: 4, cutLengthM: 15 })
    expect(cf.sublevelInterval).toBe(25) // the shared parameter is carried over
    const rp = miningDraftFor(LONGHOLE, 'ROOM_AND_PILLAR', cf)
    expect(rp.methodParameters?.kind).toBe('ROOM_AND_PILLAR')
    // a method without a parameter block drops it entirely (the backend
    // rejects a stray block for Longhole / reserved methods)
    const back = miningDraftFor(LONGHOLE, 'LONGHOLE_OPEN_STOPING', rp)
    expect(back.methodParameters).toBeUndefined()
    expect(miningDraftIsDirty(back, persistedMining(LONGHOLE))).toBe(false)
    expect(miningDraftIsDirty(cf, persistedMining(LONGHOLE))).toBe(true)
  })

  it('keeps the persisted method-specific block when re-selecting the active method', () => {
    const summary = {
      ...LONGHOLE,
      method: 'CUT_AND_FILL',
      methodParameters: { kind: 'CUT_AND_FILL' as const, liftHeightM: 3.5, cutLengthM: 12 },
    }
    expect(miningDraftFor(summary, 'CUT_AND_FILL').methodParameters).toEqual({
      kind: 'CUT_AND_FILL',
      liftHeightM: 3.5,
      cutLengthM: 12,
    })
  })
})

describe('MiningMethodCard markup', () => {
  it('lists every registry method with its status and disables Apply until dirty', () => {
    const html = renderToStaticMarkup(
      <MiningMethodCard summary={LONGHOLE} pending={false} enabled onApply={() => undefined} />,
    )
    expect(html).toContain('data-testid="mining-method-select"')
    expect((html.match(/<option /g) ?? []).length).toBe(5)
    expect(html).toContain('Room &amp; Pillar — Implemented')
    expect(html).toContain('Shrinkage Stoping — Not implemented')
    const button = html.slice(html.indexOf('Apply method') - 400, html.indexOf('Apply method'))
    expect(button).toContain('disabled=""')
  })

  it('reports Applying while the scenario rewrite runs', () => {
    const html = renderToStaticMarkup(
      <MiningMethodCard summary={LONGHOLE} pending enabled onApply={() => undefined} />,
    )
    expect(html).toContain('Applying method…')
  })
})
