/**
 * Phase 21B/C — the method card edits explicit parameters only: defaults
 * come from the backend registry table, the draft starts at the persisted
 * configuration, and Apply is only offered for a real change.
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import {
  miningDraftFor,
  miningDraftIsDirty,
  persistedMining,
  reconcileMiningDraft,
} from './miningDraft'
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
      <MiningMethodCard
        summary={LONGHOLE}
        identity="a:1"
        pending={false}
        enabled
        onApply={() => undefined}
      />,
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
      <MiningMethodCard
        summary={LONGHOLE}
        identity="a:1"
        pending
        enabled
        onApply={() => undefined}
      />,
    )
    expect(html).toContain('Applying method…')
  })
})

describe('draft isolation across scenario revisions (review blocker 3)', () => {
  const persistedA = persistedMining(LONGHOLE) // stopeLength 20
  const summaryB = { ...LONGHOLE, stopeLength: 50 }
  const persistedB = persistedMining(summaryB)

  it('an edited, unapplied draft of scenario A never shows under scenario B', () => {
    // A: the user types 35 but does not apply
    const edited = reconcileMiningDraft({ identity: 'A:1', draft: persistedA }, 'A:1', persistedA)
    const afterEdit = { identity: 'A:1', draft: { ...edited.draft, stopeLength: 35 } }
    expect(miningDraftIsDirty(afterEdit.draft, persistedA)).toBe(true)
    // B (same method, same absence of methodParameters — the old card key
    // would have been identical) is loaded: the draft is B's persisted values
    const underB = reconcileMiningDraft(afterEdit, 'B:2', persistedB)
    expect(underB.draft).toEqual(persistedB)
    expect(underB.draft.stopeLength).toBe(50)
    expect(miningDraftIsDirty(underB.draft, persistedB)).toBe(false)
  })

  it('the same identity keeps the pending edits', () => {
    const afterEdit = { identity: 'A:1', draft: { ...persistedA, stopeLength: 35 } }
    expect(reconcileMiningDraft(afterEdit, 'A:1', persistedA)).toBe(afterEdit)
  })

  it('a document replacement (same id, new epoch) restarts from the new persisted values', () => {
    const afterEdit = { identity: 'A:1', draft: { ...persistedA, stopeLength: 35 } }
    const applied = { ...LONGHOLE, stopeLength: 35 }
    const next = reconcileMiningDraft(afterEdit, 'A:2', persistedMining(applied))
    expect(next.draft).toEqual(persistedMining(applied))
    expect(miningDraftIsDirty(next.draft, persistedMining(applied))).toBe(false)
  })

  it('renders the persisted values of the identity it is given', () => {
    const html = renderToStaticMarkup(
      <MiningMethodCard
        summary={summaryB}
        identity="B:2"
        pending={false}
        enabled
        onApply={() => undefined}
      />,
    )
    expect(html).toContain('value="50"')
    const button = html.slice(html.indexOf('Apply method') - 400, html.indexOf('Apply method'))
    expect(button).toContain('disabled=""') // not dirty
  })

  it('an unsupported method edits the shared sublevel interval only', () => {
    const html = renderToStaticMarkup(
      <MiningMethodCard
        summary={{
          ...LONGHOLE,
          method: 'SUBLEVEL_CAVING',
          displayName: 'Sublevel Caving',
          implementationStatus: 'UNSUPPORTED_METHOD',
          productionKind: null,
        }}
        identity="c:3"
        pending={false}
        enabled
        onApply={() => undefined}
      />,
    )
    expect(html).toContain('Sublevel interval (m)')
    expect(html).not.toContain('Stope length (m)')
    expect(html).not.toContain('Minimum pillar (m)')
    expect(html).toContain('none (not implemented)')
  })
})
