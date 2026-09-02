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
  vehicleDriveVelocity,
  vehicleSteerDelta,
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
    expect(PERSON_CONFIG.walkSpeedMps).toBe(4.0) // inspection pace (hotfix 2)
    expect(PERSON_CONFIG.runSpeedMps).toBeCloseTo(7.0)
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
    expect(personSpeed(false)).toBe(4.0)
    expect(personSpeed(true)).toBeCloseTo(7.0)
  })
})

describe('VEHICLE (camera-yaw drive, hotfix 2)', () => {
  it('drives exactly along the camera yaw: forward 8, boost 12, reverse mirrored', () => {
    const fwd = vehicleDriveVelocity({ forward: true, backward: false, boost: false }, 0)
    expect(Math.hypot(fwd[0], fwd[1])).toBeCloseTo(8.0, 9)
    expect(fwd[1]).toBeCloseTo(-8.0, 9) // yaw 0 drives down -Z
    const boost = vehicleDriveVelocity({ forward: true, backward: false, boost: true }, 0)
    expect(Math.hypot(boost[0], boost[1])).toBeCloseTo(12.0, 9)
    const rev = vehicleDriveVelocity({ forward: false, backward: true, boost: false }, 0)
    expect(rev[1]).toBeCloseTo(8.0, 9)
    const yawed = vehicleDriveVelocity(
      { forward: true, backward: false, boost: false },
      Math.PI / 2,
    )
    expect(yawed[0]).toBeCloseTo(-8.0, 9) // looking west drives west
    expect(yawed[1]).toBeCloseTo(0, 9)
  })

  it('W+S is neutral and the drive has NO vertical output', () => {
    const both = vehicleDriveVelocity({ forward: true, backward: true, boost: true }, 1.2)
    expect(Math.hypot(both[0], both[1])).toBe(0)
    expect(both).toHaveLength(2) // [vx, vz] only — gravity owns vy
  })

  it('A/D steer the camera yaw at a bounded dt-scaled 60 deg/s', () => {
    const rate = (VEHICLE_CONFIG.steeringRateDegPerSec * Math.PI) / 180
    expect(vehicleSteerDelta({ left: true, right: false }, 0.5)).toBeCloseTo(rate * 0.5, 12)
    expect(vehicleSteerDelta({ left: false, right: true }, 0.5)).toBeCloseTo(-rate * 0.5, 12)
    expect(vehicleSteerDelta({ left: true, right: true }, 0.5)).toBe(0)
    // one 60 fps frame turns at most 1 degree — no instant flips
    expect(Math.abs(vehicleSteerDelta({ left: true, right: false }, 1 / 60))).toBeLessThan(0.02)
  })
})

describe('DRONE (3D camera-direction flight, hotfix 2)', () => {
  it('W follows the full camera direction — pitch flies the drone', () => {
    const level = droneVelocity(K({ forward: true }), { up: false, down: false }, 0, 0)
    expect(level[0]).toBeCloseTo(0, 12)
    expect(level[1]).toBeCloseTo(0, 12)
    expect(level[2]).toBeCloseTo(-DRONE_CONFIG.horizontalSpeedMps, 12)
    // pitched 45 deg down: W descends along the view ray (ramp following)
    const down = droneVelocity(K({ forward: true }), { up: false, down: false }, 0, -Math.PI / 4)
    expect(down[1]).toBeCloseTo(-DRONE_CONFIG.horizontalSpeedMps * Math.SQRT1_2, 9)
    expect(down[2]).toBeCloseTo(-DRONE_CONFIG.horizontalSpeedMps * Math.SQRT1_2, 9)
    expect(Math.hypot(...down)).toBeCloseTo(DRONE_CONFIG.horizontalSpeedMps, 9)
    expect(DRONE_CONFIG.gravityScale).toBe(0)
  })

  it('normalizes the flight vector, bounds boost, and adds Space/C on top', () => {
    const diag = droneVelocity(K({ forward: true, right: true }), { up: false, down: false }, 0, 0)
    expect(Math.hypot(...diag)).toBeCloseTo(DRONE_CONFIG.horizontalSpeedMps, 9)
    const boost = droneVelocity(K({ forward: true, boost: true }), { up: false, down: false }, 0, 0)
    expect(Math.hypot(...boost)).toBeCloseTo(DRONE_CONFIG.boostSpeedMps, 9)
    const up = droneVelocity(K({}), { up: true, down: false }, 0, 0.7)
    expect(up).toEqual([0, DRONE_CONFIG.verticalSpeedMps, 0])
    const both = droneVelocity(K({}), { up: true, down: true }, 0, 0)
    expect(both[1]).toBe(0)
  })
})
