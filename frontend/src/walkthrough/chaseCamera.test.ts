import { describe, expect, it } from 'vitest'
import {
  applyOrbit,
  backOf,
  chaseCameraPose,
  CRAMPED_FLOOR_M,
  lerpAngle,
  pitchFallbacks,
  pullIn,
  resolveChase,
  rightOf,
  viewDirection,
  wrapAngle,
  type ChaseConfig,
} from './chaseCamera'
import { NO_LOOK } from './movement'

const CFG: ChaseConfig = {
  distanceM: 4.5,
  minDistanceM: 1.0,
  pitchMinDeg: -65,
  pitchMaxDeg: 25,
  defaultPitchDeg: -14,
  occlusionPaddingM: 0.35,
  lateralOffsetM: 0,
  anchorBackM: 0,
  lookAheadM: 0,
}
const SPEEDS = { yawSpeedDegPerSec: 90, pitchSpeedDegPerSec: 70 }
const DEG = Math.PI / 180

describe('chase camera orbit (PR-4 W2)', () => {
  it('J/L yaw left/right, I/K pitch up/down, dt-scaled, pitch clamped to the config', () => {
    const s0 = { yaw: 0, pitch: 0 }
    expect(applyOrbit(s0, { ...NO_LOOK, yawLeft: true }, 0.5, SPEEDS, CFG).yaw).toBeCloseTo(
      45 * DEG,
    )
    expect(applyOrbit(s0, { ...NO_LOOK, yawRight: true }, 0.5, SPEEDS, CFG).yaw).toBeCloseTo(
      -45 * DEG,
    )
    expect(applyOrbit(s0, { ...NO_LOOK, pitchUp: true }, 0.5, SPEEDS, CFG).pitch).toBeCloseTo(
      25 * DEG,
    )
    expect(applyOrbit(s0, { ...NO_LOOK, pitchDown: true }, 5, SPEEDS, CFG).pitch).toBeCloseTo(
      -65 * DEG,
    )
    expect(applyOrbit(s0, NO_LOOK, 1, SPEEDS, CFG)).toEqual(s0)
  })

  it('view direction follows the Three convention and the camera sits behind the anchor', () => {
    expect(viewDirection(0, 0)).toEqual([-0, 0, -1])
    const d = viewDirection(Math.PI / 2, 0)
    expect(d[0]).toBeCloseTo(-1)
    expect(d[2]).toBeCloseTo(0)
    const pose = chaseCameraPose([10, 2, -5], 0, -14 * DEG, 4.5)
    // behind (+Z) and above the anchor when looking down at it
    expect(pose.position[2]).toBeGreaterThan(-5)
    expect(pose.position[1]).toBeGreaterThan(2)
    expect(pose.lookAt).toEqual([10, 2, -5])
    const dist = Math.hypot(pose.position[0] - 10, pose.position[1] - 2, pose.position[2] + 5)
    expect(dist).toBeCloseTo(4.5, 9)
  })

  it('occlusion pull-in keeps the padding and never goes below the minimum', () => {
    expect(pullIn(4.5, null, CFG)).toBe(4.5)
    expect(pullIn(4.5, 6.0, CFG)).toBe(4.5)
    expect(pullIn(4.5, 2.0, CFG)).toBeCloseTo(1.65)
    expect(pullIn(4.5, 0.5, CFG)).toBe(1.0)
  })

  it('angle helpers wrap to (−π, π] and interpolate along the shortest arc', () => {
    expect(wrapAngle(3 * Math.PI)).toBeCloseTo(Math.PI)
    expect(wrapAngle(-3 * Math.PI)).toBeCloseTo(Math.PI)
    expect(lerpAngle(0.1, 0.1 + 2 * Math.PI + 0.4, 0.5)).toBeCloseTo(0.3)
    expect(lerpAngle(0, 1, 2)).toBe(1)
  })
})

describe('occlusion-aware chase resolution (PR-4 W2, acceptance finding)', () => {
  const TRUCK: ChaseConfig = {
    distanceM: 10.3,
    minDistanceM: 6.75,
    pitchMinDeg: -45,
    pitchMaxDeg: 15,
    defaultPitchDeg: -9,
    occlusionPaddingM: 0.4,
    lateralOffsetM: 1.2,
    anchorBackM: 0,
    lookAheadM: 0,
  }

  it('an unobstructed line keeps the nominal pitch and distance, shifted over the right shoulder', () => {
    const r = resolveChase([0, 2.9, 0], 0, -9 * DEG, TRUCK, () => null)
    expect(r.cramped).toBe(false)
    expect(r.pitch).toBeCloseTo(-9 * DEG)
    expect(r.distance).toBe(10.3)
    expect(r.lookAt).toEqual([1.2, 2.9, 0]) // +X is the right of yaw 0
    expect(rightOf(Math.PI / 2)[2]).toBeCloseTo(-1)
    // a tail camera anchors the line behind the body (+Z is the rear of yaw 0)
    const tail = resolveChase([0, 2.9, 0], 0, -12 * DEG, { ...TRUCK, anchorBackM: 5 }, () => null)
    expect(tail.lookAt).toEqual([1.2, 2.9, 5])
    expect(backOf(Math.PI / 2)[0]).toBeCloseTo(1)
    // the look-ahead aims the camera ahead of the base along the view
    // azimuth (−Z for yaw 0); the camera position is unchanged
    const ahead = resolveChase(
      [0, 2.9, 0],
      0,
      -12 * DEG,
      { ...TRUCK, anchorBackM: 5, lookAheadM: 10.5 },
      () => null,
    )
    expect(ahead.lookAt).toEqual([1.2, 2.9, 5 - 10.5])
    expect(ahead.position).toEqual(tail.position)
  })

  it('a roof hit before the minimum distance flattens the view instead of entering the body', () => {
    // the look-down line hits the roof at 3 m; the flat line is clear
    const cast = (_o: [number, number, number], dir: [number, number, number]) =>
      dir[1] > 1e-6 ? 3.0 : null
    const r = resolveChase([0, 2.9, 0], 0, -9 * DEG, TRUCK, cast)
    expect(r.cramped).toBe(false)
    expect(r.pitch).toBe(0)
    expect(r.distance).toBe(10.3)
    expect(r.position[1]).toBeCloseTo(2.9)
    expect(pitchFallbacks(-9 * DEG).length).toBe(4)
  })

  it('a hit beyond the minimum distance is pulled in; blocked at every pitch is cramped at the clear point', () => {
    const r = resolveChase([0, 2.9, 0], 0, -9 * DEG, TRUCK, () => 8.0)
    expect(r.cramped).toBe(false)
    expect(r.distance).toBeCloseTo(7.6)
    // every pitch blocked at 2 m: the camera stops at the clear point
    // (hit − padding), never at the minimum distance beyond the hit
    const c = resolveChase([0, 2.9, 0], 0, -9 * DEG, TRUCK, () => 2.0)
    expect(c.cramped).toBe(true)
    expect(c.distance).toBeCloseTo(1.6)
    expect(c.pitch).toBeCloseTo(-9 * DEG)
    expect(Math.hypot(c.position[0] - 1.2, c.position[1] - 2.9, c.position[2])).toBeCloseTo(1.6)
  })

  it('cramped takes the pitch with the longest clear line and never passes a hit', () => {
    // look-down lines (camera rising) blocked at 1 m, the flat line at 3 m,
    // the upward line at 0.5 m — all inside the minimum: the flat line wins
    const cast = (_o: [number, number, number], dir: [number, number, number]) =>
      dir[1] > 1e-6 ? 1.0 : dir[1] < -1e-6 ? 0.5 : 3.0
    const c = resolveChase([0, 2.9, 0], 0, -9 * DEG, TRUCK, cast)
    expect(c.cramped).toBe(true)
    expect(c.pitch).toBe(0)
    expect(c.distance).toBeCloseTo(2.6)
    expect(c.position[1]).toBeCloseTo(2.9)
    // a hit at the padding itself floors the distance just past the near plane
    const f = resolveChase([0, 2.9, 0], 0, -9 * DEG, TRUCK, () => 0.4)
    expect(f.cramped).toBe(true)
    expect(f.distance).toBe(CRAMPED_FLOOR_M)
  })
})
