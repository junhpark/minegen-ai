import { describe, expect, it } from 'vitest'
import type { ShaftPlanningConfig } from '@/types/api'
import {
  SHAFT_SPEC_DEFAULTS,
  nextShaftId,
  persistedShafts,
  reconcileShaftDraft,
  shaftDraftIsDirty,
  shaftDraftProblems,
} from './shaftDraft'

/** hardening PR-2 H2-SH — the shaft declaration draft helpers (pure). */
describe('shaft declaration draft', () => {
  const persisted: ShaftPlanningConfig = {
    specs: [{ shaftId: 'SHAFT-01', ...SHAFT_SPEC_DEFAULTS, levelIds: ['L02'] }],
    maximumStationAccessLength: 200,
    minimumShaftSeparation: null,
  }

  it('starts from the persisted section or the schema default (no shaft)', () => {
    expect(persistedShafts(undefined)).toEqual({
      specs: [],
      maximumStationAccessLength: 200,
      minimumShaftSeparation: null,
    })
    const copy = persistedShafts(persisted)
    expect(copy).toEqual(persisted)
    expect(copy.specs[0]).not.toBe(persisted.specs[0]) // a copy, never the store object
  })

  it('allocates the next free SHAFT-nn id', () => {
    expect(nextShaftId([])).toBe('SHAFT-01')
    expect(nextShaftId(persisted.specs)).toBe('SHAFT-02')
    expect(nextShaftId([{ shaftId: 'SHAFT-02', ...SHAFT_SPEC_DEFAULTS }])).toBe('SHAFT-01')
  })

  it('is scoped to one scenario revision — another identity discards the edits', () => {
    const dirty = { ...persisted, specs: [] }
    const state = { identity: 'a:1', draft: dirty }
    expect(reconcileShaftDraft(state, 'a:1', persisted).draft).toBe(dirty)
    expect(reconcileShaftDraft(state, 'a:2', persisted).draft).toEqual(persisted)
    expect(reconcileShaftDraft(state, 'b:1', persisted).draft).toEqual(persisted)
    expect(shaftDraftIsDirty(dirty, persisted)).toBe(true)
    expect(shaftDraftIsDirty(persistedShafts(persisted), persisted)).toBe(false)
  })

  it('reports the obvious shape problems before the PUT (the backend 422 stays the authority)', () => {
    expect(shaftDraftProblems(persisted)).toEqual([])
    const bad: ShaftPlanningConfig = {
      specs: [
        { shaftId: 'shaft 1', ...SHAFT_SPEC_DEFAULTS, diameter: 20 },
        { shaftId: 'SHAFT-01', ...SHAFT_SPEC_DEFAULTS },
        { shaftId: 'SHAFT-01', ...SHAFT_SPEC_DEFAULTS, bottomSumpDepth: 0 },
      ],
      maximumStationAccessLength: 0,
      minimumShaftSeparation: -1,
    }
    const problems = shaftDraftProblems(bad)
    expect(problems.some((p) => p.includes('upper-case'))).toBe(true)
    expect(problems.some((p) => p.includes('diameter'))).toBe(true)
    expect(problems.some((p) => p.includes('declared twice'))).toBe(true)
    expect(problems.some((p) => p.includes('sump'))).toBe(true)
    expect(problems.some((p) => p.includes('access length'))).toBe(true)
    expect(problems.some((p) => p.includes('separation'))).toBe(true)
  })
})
