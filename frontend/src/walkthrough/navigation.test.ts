import { describe, expect, it } from 'vitest'
import { NO_KEYS } from './movement'
import {
  DRONE_CONFIG,
  droneVelocity,
  isNavigationMode,
  NAVIGATION_MODES,
  navigationBody,
  PERSON_CONFIG,
  personSpeed,
  VEHICLE_CONFIG,
  vehicleStep,
} from './navigation'

const K = (over: Partial<typeof NO_KEYS & { boost: boolean }>) => ({
  ...NO_KEYS,
  boost: false,
  ...over,
})

describe('navigation mode configuration (§35)', () => {
  it('exposes exactly PERSON/VEHICLE/DRONE with valid bodies', () => {
    expect(NAVIGATION_MODES).toEqual(['PERSON', 'VEHICLE', 'DRONE'])
    expect(isNavigationMode('VEHICLE')).toBe(true)
    expect(isNavigationMode('HELICOPTER')).toBe(false)
    for (const mode of NAVIGATION_MODES) {
      const b = navigationBody(mode)
      for (const v of [b.bodyHeightM, b.bodyRadiusM, b.eyeHeightM]) {
        expect(Number.isFinite(v)).toBe(true)
        expect(v).toBeGreaterThan(0)
      }
    }
  })

  it('pins speeds and gravity per mode', () => {
    expect(PERSON_CONFIG.walkSpeedMps).toBe(2.0)
    expect(PERSON_CONFIG.runSpeedMps).toBeCloseTo(5.8)
    expect(PERSON_CONFIG.gravityScale).toBe(1)
    expect(VEHICLE_CONFIG.speedMps).toBe(8.0)
    expect(VEHICLE_CONFIG.boostSpeedMps).toBe(12.0)
    expect(VEHICLE_CONFIG.gravityScale).toBe(1)
    expect(VEHICLE_CONFIG.bodyRadiusM).toBeGreaterThan(PERSON_CONFIG.bodyRadiusM)
    expect(DRONE_CONFIG.gravityScale).toBe(0)
    expect(DRONE_CONFIG.horizontalSpeedMps).toBeGreaterThanOrEqual(6)
    expect(DRONE_CONFIG.horizontalSpeedMps).toBeLessThanOrEqual(8)
    expect(DRONE_CONFIG.verticalSpeedMps).toBeGreaterThanOrEqual(4)
    expect(DRONE_CONFIG.verticalSpeedMps).toBeLessThanOrEqual(6)
  })
})

describe('PERSON (§36)', () => {
  it('walks by default and runs while Shift is held — horizontal magnitude only', () => {
    expect(personSpeed(false)).toBe(2.0)
    expect(personSpeed(true)).toBeCloseTo(5.8)
  })
})

describe('VEHICLE (§37)', () => {
  it('drives along a heading with a bounded dt-scaled steering rate', () => {
    const rate = (VEHICLE_CONFIG.steeringRateDegPerSec * Math.PI) / 180
    const s1 = vehicleStep({ headingYaw: 0 }, K({ left: true }), 0.5, VEHICLE_CONFIG)
    expect(s1.headingYaw).toBeCloseTo(rate * 0.5, 12) // A steers left (+yaw)
    const s2 = vehicleStep({ headingYaw: 0 }, K({ right: true }), 0.5, VEHICLE_CONFIG)
    expect(s2.headingYaw).toBeCloseTo(-rate * 0.5, 12)
    // no instantaneous 180°: one 60 fps frame turns at most rate/60
    const frame = vehicleStep({ headingYaw: 0 }, K({ left: true }), 1 / 60, VEHICLE_CONFIG)
    expect(Math.abs(frame.headingYaw)).toBeLessThan(0.02)
  })

  it('bounds speed, supports reverse and boost, never moves vertically', () => {
    const fwd = vehicleStep({ headingYaw: 0 }, K({ forward: true }), 0.1, VEHICLE_CONFIG)
    expect(Math.hypot(fwd.vx, fwd.vz)).toBeCloseTo(8.0, 9)
    expect(fwd.vz).toBeCloseTo(-8.0, 9) // heading 0 drives down -Z
    const rev = vehicleStep({ headingYaw: 0 }, K({ backward: true }), 0.1, VEHICLE_CONFIG)
    expect(rev.vz).toBeCloseTo(8.0, 9)
    const boost = vehicleStep(
      { headingYaw: 0 },
      K({ forward: true, boost: true }),
      0.1,
      VEHICLE_CONFIG,
    )
    expect(Math.hypot(boost.vx, boost.vz)).toBeCloseTo(12.0, 9)
    const idle = vehicleStep({ headingYaw: 1.2 }, K({}), 0.1, VEHICLE_CONFIG)
    expect(Math.hypot(idle.vx, idle.vz)).toBe(0) // no drive input, no motion
    // the step has NO vertical output at all — gravity owns vy
    expect('vy' in fwd).toBe(false)
  })
})

describe('DRONE (§38)', () => {
  it('produces yaw-based XYZ velocity with vertical keys and no gravity', () => {
    const v = droneVelocity(K({ forward: true }), { up: false, down: false }, 0)
    expect(v[0]).toBeCloseTo(0, 12)
    expect(v[1]).toBe(0)
    expect(v[2]).toBeCloseTo(-DRONE_CONFIG.horizontalSpeedMps, 12)
    const up = droneVelocity(K({}), { up: true, down: false }, 0)
    expect(up[1]).toBe(DRONE_CONFIG.verticalSpeedMps)
    const down = droneVelocity(K({}), { up: false, down: true }, 0)
    expect(down[1]).toBe(-DRONE_CONFIG.verticalSpeedMps)
    expect(DRONE_CONFIG.gravityScale).toBe(0)
  })

  it('normalizes diagonals and bounds boost', () => {
    const diag = droneVelocity(K({ forward: true, right: true }), { up: false, down: false }, 0)
    expect(Math.hypot(diag[0], diag[2])).toBeCloseTo(DRONE_CONFIG.horizontalSpeedMps, 9)
    const boost = droneVelocity(K({ forward: true, boost: true }), { up: false, down: false }, 0)
    expect(Math.hypot(boost[0], boost[2])).toBeCloseTo(DRONE_CONFIG.boostSpeedMps, 9)
    // camera pitch is not an input: only yaw shapes the horizontal vector
    const yawed = droneVelocity(K({ forward: true }), { up: false, down: false }, Math.PI / 2)
    expect(yawed[0]).toBeCloseTo(-DRONE_CONFIG.horizontalSpeedMps, 9)
    expect(yawed[2]).toBeCloseTo(0, 9)
  })
})
