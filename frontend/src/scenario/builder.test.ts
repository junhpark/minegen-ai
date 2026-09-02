import { describe, expect, it } from 'vitest'
import type { ScenarioCreate } from '@/types/api'
import {
  addFault,
  DEFAULT_BUILDER,
  DESIGN_UNSUPPORTED_NOTICE,
  designSupported,
  editFault,
  editOrebody,
  editRockQuality,
  EDITABLE_OREBODY_TYPES,
  faultCountEnabled,
  MAX_FAULTS,
  realizedSummary,
  realizeRequest,
  removeFault,
} from './builder'

describe('scenario builder model (Phase 17, rule 124)', () => {
  it('BASELINE never sends a fault count; RANDOM presets do', () => {
    expect(faultCountEnabled('BASELINE')).toBe(false)
    expect(faultCountEnabled('RANDOM_TABULAR')).toBe(true)
    expect(realizeRequest({ preset: 'BASELINE', seed: 42, faultCount: 5 })).toEqual({
      preset: 'BASELINE',
      seed: 42,
      faultCount: null,
    })
    expect(realizeRequest({ preset: 'RANDOM_ELLIPSOID', seed: 7, faultCount: 3 })).toEqual({
      preset: 'RANDOM_ELLIPSOID',
      seed: 7,
      faultCount: 3,
    })
    expect(DEFAULT_BUILDER.preset).toBe('BASELINE')
  })

  it('summary echoes backend-realized values verbatim (no local geometry)', () => {
    const sc = {
      orebody: {
        orebodyType: 'ELLIPSOID',
        center: { x: 120.4, y: -80.2, z: -35.7 },
        strikeDeg: 123.4,
        dipDeg: 61.8,
        length: 512.3,
        height: 288.9,
        thickness: 14.25,
        meanGrade: 3.94,
      },
      geology: { faults: [{}, {}] },
    } as unknown as ScenarioCreate
    const lines = realizedSummary(sc)
    expect(lines[0]).toBe('ELLIPSOID orebody · 512×289×14.3 m')
    expect(lines[1]).toBe('center E 120 / N -80 / RL -36 m')
    expect(lines[2]).toBe('strike 123° · dip 62° · grade 3.9 g/t')
    expect(lines[3]).toBe('faults 2')
  })

  it('design gate mirrors the backend typed failure', () => {
    expect(designSupported(null)).toBe(true) // nothing loaded yet
    expect(designSupported({ orebody: { orebodyType: 'TABULAR' } } as never)).toBe(true)
    expect(designSupported({ orebody: { orebodyType: 'ELLIPSOID' } } as never)).toBe(false)
    expect(DESIGN_UNSUPPORTED_NOTICE).toContain('Phase 18')
  })
})

/** stand-in for a backend-realized document */
function realizedDraft(): ScenarioCreate {
  return {
    name: 'Random Tabular mine',
    seed: 12345,
    orebody: {
      orebodyType: 'TABULAR',
      center: { x: 100, y: -50, z: -80 },
      strikeDeg: 35,
      dipDeg: 70,
      length: 500,
      height: 300,
      thickness: 12,
      meanGrade: 4.2,
      gradeVariability: 0.3,
      gradeCorrelationLengthXy: 80,
      gradeCorrelationLengthZ: 40,
      density: 2.8,
    },
    geology: {
      rockQuality: {
        mean: 65,
        std: 12,
        correlationLengthXy: 80,
        correlationLengthZ: 40,
        minimum: 20,
        maximum: 90,
      },
      faults: [
        {
          origin: { x: -100, y: -200, z: 0 },
          strikeDeg: 120,
          dipDeg: 65,
          coreHalfWidth: 2.5,
          influenceHalfWidth: 20,
          corePenalty: 50,
          damageZonePenalty: 10,
        },
      ],
    },
  } as unknown as ScenarioCreate
}

describe('explicit draft editing (Phase 17 acceptance, rule 124)', () => {
  it('only offers implemented geometries — reserved enum members stay hidden', () => {
    expect(EDITABLE_OREBODY_TYPES).toEqual(['TABULAR', 'ELLIPSOID'])
    expect(EDITABLE_OREBODY_TYPES).not.toContain('PIPE')
    expect(EDITABLE_OREBODY_TYPES).not.toContain('LENS')
  })

  it('edits orebody scalars and center components immutably', () => {
    const draft = realizedDraft()
    const next = editOrebody(editOrebody(draft, { center: { z: -140 } }), {
      dipDeg: 55,
      thickness: 18,
      orebodyType: 'ELLIPSOID',
    })
    expect(next.orebody.center).toEqual({ x: 100, y: -50, z: -140 })
    expect(next.orebody.dipDeg).toBe(55)
    expect(next.orebody.thickness).toBe(18)
    expect(next.orebody.orebodyType).toBe('ELLIPSOID')
    expect(next.orebody.length).toBe(500) // untouched fields survive
    expect(draft.orebody.dipDeg).toBe(70) // original not mutated
  })

  it('edits rock quality and faults, and ignores non-finite input', () => {
    const draft = realizedDraft()
    const rq = editRockQuality(draft, { mean: 72, std: Number.NaN })
    expect(rq.geology.rockQuality.mean).toBe(72)
    expect(rq.geology.rockQuality.std).toBe(12) // NaN rejected
    const f = editFault(rq, 0, { strikeDeg: 200, origin: { x: 250 } })
    expect(f.geology.faults[0]!.strikeDeg).toBe(200)
    expect(f.geology.faults[0]!.origin).toEqual({ x: 250, y: -200, z: 0 })
    expect(f.geology.faults[0]!.corePenalty).toBe(50)
    expect(editFault(f, 9, { dipDeg: 10 })).toBe(f) // out-of-range index is a no-op
  })

  it('adds and removes faults within the backend 0–6 contract, without randomness', () => {
    let draft = realizedDraft()
    for (let i = 1; i < MAX_FAULTS; i++) draft = addFault(draft)
    expect(draft.geology.faults).toHaveLength(MAX_FAULTS)
    // the appended fault copies the previous one — no drawn parameters
    expect(draft.geology.faults[5]).toEqual(draft.geology.faults[0])
    expect(addFault(draft).geology.faults).toHaveLength(MAX_FAULTS) // capped
    const removed = removeFault(draft, 0)
    expect(removed.geology.faults).toHaveLength(MAX_FAULTS - 1)
    expect(removeFault(realizedDraft(), 0).geology.faults).toEqual([])
  })

  it('summary reflects the EDITED draft, so the preview never shows stale values', () => {
    const edited = editOrebody(realizedDraft(), { thickness: 33, orebodyType: 'ELLIPSOID' })
    expect(realizedSummary(edited)[0]).toContain('ELLIPSOID')
    expect(realizedSummary(edited)[0]).toContain('33.0 m')
  })
})
