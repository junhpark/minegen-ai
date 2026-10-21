import { describe, expect, it } from 'vitest'
import {
  DEFAULT_VEHICLE_PRESET,
  VEHICLE_MIN_STEER_SPEED_MPS,
  VEHICLE_PRESETS,
  VEHICLE_STEER_CAP_DEG_PER_SEC,
  integrateHeading,
  isVehiclePresetId,
  nextVehiclePreset,
  truckLayout,
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

describe('truck layout (PR-6 — one geometry authority for the avatar and the cab eye)', () => {
  it('every box stays inside the planning box and the bin top IS the preset height', () => {
    for (const p of VEHICLE_PRESETS) {
      const layout = truckLayout(p)
      const half = vehicleBoxHalfExtents(p)
      for (const b of layout.boxes) {
        for (const k of [0, 1, 2] as const) {
          expect(Math.abs(b.center[k]) + b.size[k] / 2).toBeLessThanOrEqual(half[k] + 1e-9)
        }
      }
      const bin = layout.boxes.find((b) => b.id === 'BIN')!
      expect(bin.center[1] + bin.size[1] / 2).toBeCloseTo(p.heightM / 2, 12)
      const cab = layout.boxes.find((b) => b.id === 'CAB')!
      expect(cab.center[1] + cab.size[1] / 2).toBeCloseTo(p.heightM / 2, 12)
      // the cab sits at the front, left-hand side; the hood behind it
      const hood = layout.boxes.find((b) => b.id === 'HOOD')!
      expect(cab.center[2]).toBeLessThan(hood.center[2])
      expect(cab.center[0]).toBeLessThan(0)
      expect(layout.floor).toBe(-p.heightM / 2)
      expect(layout.axleY).toBeCloseTo(layout.floor + p.wheelRadiusM, 12)
      expect(layout.headlights).toHaveLength(2)
    }
  })

  it('articulated trucks carry a hinge and four wheels, the rigid body six wheels and no hinge', () => {
    const adt = truckLayout(vehiclePreset('UG_ADT_45T'))
    expect(adt.boxes.some((b) => b.id === 'HINGE')).toBe(true)
    expect(adt.wheels).toHaveLength(4)
    const rdt = truckLayout(vehiclePreset('RDT_40T'))
    expect(rdt.boxes.some((b) => b.id === 'HINGE')).toBe(false)
    expect(rdt.wheels).toHaveLength(6)
  })

  it('reproduces the PR-4 avatar numbers for the 45 t class (visual parity)', () => {
    // L 10.5, W 3.0, H 2.9, r 0.85: floor −1.45, chassis 0.638 high,
    // cab at (−0.54, 0.744, −3.927) and the driver's eye 0.212 above its centre
    const l = truckLayout(vehiclePreset('UG_ADT_45T'))
    expect(l.floor).toBeCloseTo(-1.45, 12)
    expect(l.chassisH).toBeCloseTo(0.638, 12)
    expect(l.frontL).toBeCloseTo(4.41, 12)
    expect(l.rearL).toBeCloseTo(5.46, 12)
    const cab = l.boxes.find((b) => b.id === 'CAB')!
    expect(cab.center[0]).toBeCloseTo(-0.54, 12)
    expect(cab.center[1]).toBeCloseTo(0.744, 9)
    expect(cab.center[2]).toBeCloseTo(-3.927, 9)
    expect(cab.size).toEqual([
      1.5,
      expect.closeTo(1.412, 9) as unknown as number,
      expect.closeTo(1.8522, 9) as unknown as number,
    ])
    expect(l.cabEye[0]).toBeCloseTo(-0.54, 12)
    expect(l.cabEye[1]).toBeCloseTo(0.744 + 0.15 * 1.412, 9)
    expect(l.cabEye[2]).toBeCloseTo(-3.927, 9)
    // ≈ 2.41 m above the floor
    expect(l.cabEye[1] - l.floor).toBeCloseTo(2.4058, 3)
  })
})
