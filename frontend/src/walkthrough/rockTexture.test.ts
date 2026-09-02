import { describe, expect, it } from 'vitest'
import { mulberry32, rockTextureSpec } from './rockTexture'

describe('rock/joint texture determinism (§23/§40)', () => {
  it('same seed -> identical spec; different seed -> variation allowed', () => {
    const a = rockTextureSpec(1234)
    const b = rockTextureSpec(1234)
    expect(a).toEqual(b) // fully deterministic generator
    const c = rockTextureSpec(9999)
    expect(JSON.stringify(c.jointFamilies)).not.toBe(JSON.stringify(a.jointFamilies))
  })

  it('spec honours the visual contract: 2–3 families, dark base, floor band', () => {
    for (const seed of [1, 42, 77777]) {
      const s = rockTextureSpec(seed)
      expect(s.jointFamilies.length).toBeGreaterThanOrEqual(2)
      expect(s.jointFamilies.length).toBeLessThanOrEqual(3)
      for (const f of s.jointFamilies) {
        expect(f.spacingPx).toBeGreaterThan(30) // no high-frequency noise
        expect(f.strength).toBeLessThan(0.35) // no bright/cartoon cracks
      }
      expect(s.floorBandU).toEqual([0.72, 1.0]) // empirically proven floor u-band
      expect(s.sizePx).toBe(512)
    }
  })

  it('mulberry32 streams are reproducible', () => {
    const a = mulberry32(7)
    const b = mulberry32(7)
    for (let i = 0; i < 5; i++) expect(a()).toBe(b())
  })
})
