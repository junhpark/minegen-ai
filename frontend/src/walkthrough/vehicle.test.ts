import { describe, expect, it } from 'vitest'
import {
  DEFAULT_VEHICLE_PRESET,
  VEHICLE_MIN_STEER_SPEED_MPS,
  VEHICLE_PRESETS,
  VEHICLE_STEER_CAP_DEG_PER_SEC,
  integrateHeading,
  isVehiclePresetId,
  nextVehiclePreset,
  vehicleBoxHalfExtents,
  vehicleClearance,
  vehiclePreset,
  vehicleYawRate,
  yawQuaternion,
} from './vehicle'

const DEG = Math.PI / 180

describe('vehicle presets (PR-4 W2 — representative class dimensions)', () => {
  it('declares three distinct classes with positive planning dimensions', () => {
    expect(VEHICLE_PRESETS.map((p) => p.id)).toEqual(['UG_ADT_45T', 'UG_ADT_60T', 'RDT_40T'])
    for (const p of VEHICLE_PRESETS) {
      expect(p.lengthM).toBeGreaterThan(p.widthM)
      expect(p.widthM).toBeGreaterThan(0)
      expect(p.heightM).toBeGreaterThan(0)
      expect(p.turningRadiusM).toBeGreaterThan(p.widthM)
      expect(p.eyeHeightM).toBeLessThanOrEqual(p.heightM + 1e-9)
      expect(p.classNote.length).toBeGreaterThan(10)
    }
    // the underground articulated classes fit the default 5 m section with
    // side clearance; the surface rigid body is flagged in its note
    expect(vehiclePreset('UG_ADT_45T').widthM).toBeLessThan(5)
    expect(vehiclePreset('RDT_40T').classNote).toMatch(/comparison/)
  })

  it('default, guard and cycling are deterministic', () => {
    expect(DEFAULT_VEHICLE_PRESET).toBe('UG_ADT_45T')
    expect(isVehiclePresetId('UG_ADT_60T')).toBe(true)
    expect(isVehiclePresetId('TRUCK')).toBe(false)
    expect(nextVehiclePreset('UG_ADT_45T')).toBe('UG_ADT_60T')
    expect(nextVehiclePreset('RDT_40T')).toBe('UG_ADT_45T')
    expect(() => vehiclePreset('NOPE' as never)).toThrow(/unknown vehicle preset/)
  })

  it('box half extents follow width × height × length and the yaw quaternion rotates about +Y', () => {
    const p = vehiclePreset('UG_ADT_60T')
    expect(vehicleBoxHalfExtents(p)).toEqual([1.8, 1.7, 5.8])
    const [x, y, z, w] = yawQuaternion(Math.PI / 2)
    expect(x).toBe(0)
    expect(z).toBe(0)
    expect(y).toBeCloseTo(Math.SQRT1_2, 12)
    expect(w).toBeCloseTo(Math.SQRT1_2, 12)
  })

  it('clearance is the plain section minus the body (navigation information)', () => {
    const c = vehicleClearance(vehiclePreset('UG_ADT_45T'), { tunnelWidth: 5, tunnelHeight: 5 })
    expect(c.sideM).toBeCloseTo(1.0, 12)
    expect(c.headM).toBeCloseTo(2.1, 12)
  })
})

describe('bicycle-rule heading (PR-4 W2)', () => {
  const p = vehiclePreset('UG_ADT_45T') // R = 8.5 m

  it('yaw rate = speed / turning radius, floored at the aiming speed, capped at 60 deg/s', () => {
    expect(vehicleYawRate(8.5, p)).toBeCloseTo(1.0, 12)
    expect(vehicleYawRate(0, p)).toBeCloseTo(VEHICLE_MIN_STEER_SPEED_MPS / 8.5, 12)
    expect(vehicleYawRate(-8.5, p)).toBeCloseTo(1.0, 12) // reverse: magnitude only
    const cap = VEHICLE_STEER_CAP_DEG_PER_SEC * DEG
    expect(vehicleYawRate(1000, p)).toBeCloseTo(cap, 12)
  })

  it('A turns left (+yaw) driving forward, the sense flips in reverse, no input holds', () => {
    const left = { left: true, right: false }
    const right = { left: false, right: true }
    const none = { left: false, right: false }
    const fwd = integrateHeading(0, left, 8.5, 0.5, p)
    expect(fwd).toBeCloseTo(0.5, 12)
    expect(integrateHeading(0, right, 8.5, 0.5, p)).toBeCloseTo(-0.5, 12)
    expect(integrateHeading(0, left, -8.5, 0.5, p)).toBeCloseTo(-0.5, 12)
    expect(integrateHeading(1.2, none, 8.5, 0.5, p)).toBe(1.2)
    // frame-rate independent: ten small steps == one big step
    let h = 0
    for (let i = 0; i < 10; i++) h = integrateHeading(h, left, 8.5, 0.05, p)
    expect(h).toBeCloseTo(fwd, 9)
  })
})
