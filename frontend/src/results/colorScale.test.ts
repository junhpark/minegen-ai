import { describe, expect, it } from 'vitest'
import { displayRange, legendTicks, NEUTRAL_COLOR, rampRgb, rgbToHex, valueRgb } from './colorScale'

describe('display range', () => {
  it('uses the frame extent, the manual range when set, and widens a degenerate extent', () => {
    expect(displayRange(1, 5, null)).toEqual({ min: 1, max: 5 })
    expect(displayRange(1, 5, { min: 0, max: 10 })).toEqual({ min: 0, max: 10 })
    expect(displayRange(1, 5, { min: 10, max: 0 })).toEqual({ min: 0, max: 10 })
    expect(displayRange(null, null, null)).toBeNull()
    const d = displayRange(4, 4, null)
    expect(d && d.min < 4 && d.max > 4).toBe(true)
    expect(displayRange(0, 0, null)).toEqual({ min: -0.5, max: 0.5 })
  })

  it('maps values monotonically and clamps outside the range', () => {
    const r = { min: 0, max: 10 }
    expect(valueRgb(-5, r)).toEqual(rampRgb(0))
    expect(valueRgb(50, r)).toEqual(rampRgb(1))
    expect(valueRgb(5, r)).toEqual(rampRgb(0.5))
    expect(rgbToHex(rampRgb(0))).toBe('#440154')
    expect(rgbToHex(rampRgb(1))).toBe('#fde725')
    expect(NEUTRAL_COLOR).toBe('#5a6470')
    expect(legendTicks({ min: 0, max: 4 })).toEqual([0, 1, 2, 3, 4])
  })
})
