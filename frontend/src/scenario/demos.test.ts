import { describe, expect, it } from 'vitest'
import type { Scenario } from '@/types/api'
import { cloneDraft, nextTourPreset, TOUR_ORDER } from './demos'

describe('cloneDraft (hardening PR-2 H4 — Clone to edit)', () => {
  const demo = {
    id: 'demo-tabular-longhole',
    schemaVersion: 2,
    name: 'Demo — Tabular Longhole',
    seed: 1,
    orebody: { orebodyType: 'TABULAR' },
  } as unknown as Scenario

  it('is the demo document without its identity, renamed as a copy', () => {
    const draft = cloneDraft(demo)
    expect('id' in draft).toBe(false)
    expect('schemaVersion' in draft).toBe(false)
    expect(draft.name).toBe('Demo — Tabular Longhole (copy)')
    expect(draft.seed).toBe(1) // the same seed reproduces the same world (rule 119)
    expect(draft.orebody).toEqual({ orebodyType: 'TABULAR' })
    expect(cloneDraft(demo, 'Mine A').name).toBe('Mine A')
  })

  it('never mutates the source document', () => {
    const before = JSON.stringify(demo)
    cloneDraft(demo)
    expect(JSON.stringify(demo)).toBe(before)
  })
})

describe('Auto tour', () => {
  it('cycles the three camera presets', () => {
    expect(TOUR_ORDER).toEqual(['ISO', 'TOP', 'FIT'])
    expect(nextTourPreset('ISO')).toBe('TOP')
    expect(nextTourPreset('TOP')).toBe('FIT')
    expect(nextTourPreset('FIT')).toBe('ISO')
  })
})
