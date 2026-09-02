import { describe, expect, it } from 'vitest'
import type { ScenarioCreate } from '@/types/api'
import {
  DEFAULT_BUILDER,
  DESIGN_UNSUPPORTED_NOTICE,
  designSupported,
  faultCountEnabled,
  realizedSummary,
  realizeRequest,
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
