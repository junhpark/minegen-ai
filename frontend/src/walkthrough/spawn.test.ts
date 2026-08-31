import { describe, expect, it } from 'vitest'
import type { SmoothedDeclinePayload } from '@/types/scene'
import { WALKTHROUGH_CONFIG } from './config'
import { resolveWalkthroughSpawn } from './spawn'

function smoothed(points: number[]): SmoothedDeclinePayload {
  return {
    segments: [
      {
        effectiveCenterline: { points, pointCount: points.length / 3 },
      },
    ],
  } as unknown as SmoothedDeclinePayload
}

// straight decline heading +Y (north), 12 % down, 40 m (spawn chainage 6.0 m fits)
const LINE: number[] = []
for (let i = 0; i <= 20; i++) LINE.push(10, 2 * i, 100 - 0.24 * i)

describe('deterministic walkthrough spawn (rule 102)', () => {
  it('is deterministic, finite, on the centerline chainage, above the floor', () => {
    const a = resolveWalkthroughSpawn(smoothed(LINE), WALKTHROUGH_CONFIG)
    const b = resolveWalkthroughSpawn(smoothed([...LINE]), WALKTHROUGH_CONFIG)
    expect(a).not.toBeNull()
    expect(a).toEqual(b) // same input -> identical output
    const s = a!
    ;[...s.floorPositionMine, ...s.bodyPositionThree, ...s.forwardThree, s.yaw].forEach((v) =>
      expect(Number.isFinite(v)).toBe(true),
    )
    // fixed chainage from the portal along the effective centerline
    const chain = Math.hypot(
      s.floorPositionMine[0] - 10,
      s.floorPositionMine[1] - 0,
      s.floorPositionMine[2] - 100,
    )
    expect(chain).toBeCloseTo(WALKTHROUGH_CONFIG.spawnChainageM, 9)
    // body center above floor by half height + clearance (Three Y-up)
    const floorY = s.floorPositionMine[2]
    expect(s.bodyPositionThree[1]).toBeCloseTo(
      floorY + WALKTHROUGH_CONFIG.bodyHeightM / 2 + WALKTHROUGH_CONFIG.spawnFloorClearanceM,
      9,
    )
  })

  it('faces into the tunnel with pitch-free horizontal forward', () => {
    const s = resolveWalkthroughSpawn(smoothed(LINE), WALKTHROUGH_CONFIG)!
    // mine +Y (north) maps to Three -Z: into-tunnel forward is [0, 0, -1]
    expect(s.forwardThree[0]).toBeCloseTo(0, 9)
    expect(s.forwardThree[1]).toBe(0)
    expect(s.forwardThree[2]).toBeCloseTo(-1, 9)
    expect(s.yaw).toBeCloseTo(0, 9)
  })

  it('rejects malformed centerlines with no arbitrary fallback', () => {
    expect(resolveWalkthroughSpawn(null, WALKTHROUGH_CONFIG)).toBeNull()
    expect(resolveWalkthroughSpawn(smoothed([]), WALKTHROUGH_CONFIG)).toBeNull()
    expect(resolveWalkthroughSpawn(smoothed([0, 0, 0, 1, 0]), WALKTHROUGH_CONFIG)).toBeNull()
    expect(
      resolveWalkthroughSpawn(smoothed([0, 0, 0, Number.NaN, 0, 0]), WALKTHROUGH_CONFIG),
    ).toBeNull()
    // tunnel shorter than the spawn chainage
    expect(resolveWalkthroughSpawn(smoothed([0, 0, 0, 4, 0, 0]), WALKTHROUGH_CONFIG)).toBeNull()
    // vertical shaft-like tangent cannot define yaw
    expect(
      resolveWalkthroughSpawn(smoothed([0, 0, 0, 0, 0, -10, 0, 0, -20]), WALKTHROUGH_CONFIG),
    ).toBeNull()
  })
})
