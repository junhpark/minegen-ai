import { describe, expect, it } from 'vitest'
import { gradeRamp, normalize, rockQualityRamp } from './colormap'

describe('colormap', () => {
  it('clamps and interpolates', () => {
    expect(rockQualityRamp(-1)).toEqual(rockQualityRamp(0))
    expect(rockQualityRamp(2)).toEqual(rockQualityRamp(1))
    const mid = rockQualityRamp(0.25)
    const lo = rockQualityRamp(0)
    const hi = rockQualityRamp(0.5)
    for (let i = 0; i < 3; i++) {
      expect(mid[i]).toBeCloseTo(((lo[i] as number) + (hi[i] as number)) / 2)
    }
  })
  it('treats non-finite input as 0', () => {
    expect(gradeRamp(Number.NaN)).toEqual(gradeRamp(0))
  })
  it('normalizes with degenerate range', () => {
    expect(normalize(5, 0, 10)).toBe(0.5)
    expect(normalize(5, 5, 5)).toBe(0)
  })
})
