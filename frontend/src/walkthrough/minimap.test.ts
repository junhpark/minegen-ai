import { describe, expect, it } from 'vitest'
import type { SmoothedDeclinePayload } from '@/types/scene'
import { approximateChainage, bearingDegFromYaw, buildMinimapModel, mineXYToMap } from './minimap'

function smoothed(): SmoothedDeclinePayload {
  const seg = (levelId: string, pts: number[]) => ({
    levelId,
    effectiveCenterline: { points: pts, pointCount: pts.length / 3 },
  })
  return {
    segments: [
      seg('SEG:A', [0, 0, 0, 0, 50, -5]),
      seg('SEG:B', [0, 50, -5, 40, 50, -10]),
      seg('SEG:C', [40, 50, -10, 40, 90, -15]),
    ],
  } as unknown as SmoothedDeclinePayload
}

describe('minimap model + projection (§39)', () => {
  it('projects mine XY north-up (east right, north UP => SVG y negated)', () => {
    expect(mineXYToMap(10, 0)).toEqual([10, -0])
    expect(mineXYToMap(0, 25)).toEqual([0, -25]) // north goes UP on screen
  })

  it('heading arrow bearing: yaw 0 => north 0°, west-facing yaw => 270°', () => {
    expect(bearingDegFromYaw(0)).toBe(0)
    expect(bearingDegFromYaw(Math.PI / 2)).toBeCloseTo(270, 9) // looking -X (west)
    expect(bearingDegFromYaw(-Math.PI / 2)).toBeCloseTo(90, 9) // east
  })

  it('static model carries the full decline with portal and deep end', () => {
    const m = buildMinimapModel(smoothed(), null)
    expect(m.polylines.map((p) => p.segmentId)).toEqual(['SEG:A', 'SEG:B', 'SEG:C'])
    expect(m.portal).toEqual([0, 0])
    expect(m.end).toEqual([40, 90])
    expect(m.chainagePoints.length / 3).toBe(6)
  })

  it('temporal model emits ONLY the ACTIVE prefix — future segments hidden (§14)', () => {
    const m = buildMinimapModel(smoothed(), ['SEG:A', 'SEG:B'])
    expect(m.polylines.map((p) => p.segmentId)).toEqual(['SEG:A', 'SEG:B'])
    expect(m.end).toEqual([40, 50]) // frontier end, never the future terminal
    // future SEG:C never appears anywhere in the model
    expect(m.chainagePoints).not.toContain(90)
    expect(buildMinimapModel(smoothed(), []).polylines).toEqual([])
  })

  it('approximates chainage from the nearest centerline segment', () => {
    const m = buildMinimapModel(smoothed(), null)
    // portal
    expect(approximateChainage([0, 0, 0], m.chainagePoints)!.chainageM).toBeCloseTo(0, 6)
    // 30 m up the first (50.25 m long) segment, slightly off-axis
    const c = approximateChainage([1.5, 30, -3], m.chainagePoints)!
    expect(c.chainageM).toBeGreaterThan(28)
    expect(c.chainageM).toBeLessThan(33)
    // deep end ~= total length of all three segments
    const total = approximateChainage([40, 90, -15], m.chainagePoints)!
    const expected = Math.hypot(0, 50, 5) + Math.hypot(40, 0, 5) + Math.hypot(0, 40, 5)
    expect(total.chainageM).toBeCloseTo(expected, 6)
    expect(approximateChainage([0, 0, 0], [])).toBeNull()
  })
})
