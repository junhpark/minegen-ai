/**
 * Hardening PR-6 — walk camera view contract and the frame-coverage
 * instrument that measured Park's complaint ("the truck hides the way
 * ahead") before the ghost / cab view were written.
 */
import { describe, expect, it } from 'vitest'
import {
  CAB_DEFAULT_PITCH_DEG,
  CAB_PITCH_MAX_DEG,
  CAB_PITCH_MIN_DEG,
  DEFAULT_WALK_CAMERA_VIEW,
  GHOST_OPACITY,
  avatarPresentation,
  cabPose,
  cabViewLabel,
  cabViewLegend,
  defaultPitchDegFor,
  firstPersonEyeOffset,
  isWalkCameraView,
  lampOffset,
  orbitConfigFor,
  rotateOffsetByYaw,
  toggleCameraView,
} from './cameraView'
import { resolveChase, viewDirection, type Vec3 } from './chaseCamera'
import { chaseFor, navigationBody, DRONE_CONFIG, PERSON_CONFIG } from './navigation'
import { VEHICLE_PRESETS, truckLayout, vehicleBoxHalfExtents, vehiclePreset } from './vehicle'

const DEG = Math.PI / 180

// ---- frame-coverage instrument ------------------------------------------
// The MineCanvas camera: 45° vertical field of view on a 1600 × 950 viewport.
const FOV_DEG = 45
const ASPECT = 1600 / 950
const COLS = 160
const ROWS = 95

function norm(v: Vec3): Vec3 {
  const l = Math.hypot(v[0], v[1], v[2])
  return [v[0] / l, v[1] / l, v[2] / l]
}
function cross(a: Vec3, b: Vec3): Vec3 {
  return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
}
function rayHitsBox(
  o: Vec3,
  d: Vec3,
  center: readonly [number, number, number],
  size: readonly [number, number, number],
): boolean {
  let tmin = -Infinity
  let tmax = Infinity
  for (const k of [0, 1, 2] as const) {
    const lo = center[k] - size[k] / 2
    const hi = center[k] + size[k] / 2
    if (Math.abs(d[k]) < 1e-12) {
      if (o[k] < lo || o[k] > hi) return false
      continue
    }
    const t1 = (lo - o[k]) / d[k]
    const t2 = (hi - o[k]) / d[k]
    tmin = Math.max(tmin, Math.min(t1, t2))
    tmax = Math.min(tmax, Math.max(t1, t2))
  }
  return tmax >= Math.max(tmin, 0)
}

/** Fraction of the frame's pixel-centre rays that hit any of the boxes;
 * `region(x, y)` (normalized device coordinates) restricts the count. */
function frameCoverage(
  position: Vec3,
  lookAt: Vec3,
  boxes: readonly {
    center: readonly [number, number, number]
    size: readonly [number, number, number]
  }[],
  region: (x: number, y: number) => boolean = () => true,
): number {
  const f = norm([lookAt[0] - position[0], lookAt[1] - position[1], lookAt[2] - position[2]])
  const r = norm(cross(f, [0, 1, 0]))
  const u = cross(r, f)
  const tanV = Math.tan((FOV_DEG / 2) * DEG)
  const tanH = tanV * ASPECT
  let total = 0
  let hits = 0
  for (let j = 0; j < ROWS; j++) {
    const y = 1 - (2 * (j + 0.5)) / ROWS
    for (let i = 0; i < COLS; i++) {
      const x = (2 * (i + 0.5)) / COLS - 1
      if (!region(x, y)) continue
      total++
      const d: Vec3 = [
        f[0] + x * tanH * r[0] + y * tanV * u[0],
        f[1] + x * tanH * r[1] + y * tanV * u[1],
        f[2] + x * tanH * r[2] + y * tanV * u[2],
      ]
      if (boxes.some((b) => rayHitsBox(position, d, b.center, b.size))) hits++
    }
  }
  return total === 0 ? 0 : hits / total
}
const CENTRE_THIRD = (x: number, y: number) => Math.abs(x) <= 1 / 3 && Math.abs(y) <= 1 / 3
/** the drive ahead: the central quarter of the frame width between 20 % and
 * 60 % of its height (the chase line aims one body length ahead, so the
 * floor ahead sits in this band) */
const FORWARD_LANE = (x: number, y: number) => Math.abs(x) <= 0.25 && y >= -0.6 && y <= 0.2

describe('walk camera view (PR-6)', () => {
  it('two views, F toggles, chase is the default, labels per body', () => {
    expect(DEFAULT_WALK_CAMERA_VIEW).toBe('CHASE')
    expect(toggleCameraView('CHASE')).toBe('CAB')
    expect(toggleCameraView('CAB')).toBe('CHASE')
    expect(isWalkCameraView('CAB')).toBe(true)
    expect(isWalkCameraView('ORBIT')).toBe(false)
    expect(cabViewLabel('VEHICLE')).toBe('Cab view')
    expect(cabViewLabel('PERSON')).toBe('First person')
    expect(cabViewLabel('DRONE')).toBe('First person')
    expect(cabViewLegend('VEHICLE')).toBe('Cab / Chase')
    expect(cabViewLegend('DRONE')).toBe('First person / Chase')
  })

  it('CAB replaces only the pitch clamp and starts level; CHASE keeps the chase config', () => {
    const chase = chaseFor('VEHICLE', 'UG_ADT_45T')
    expect(orbitConfigFor('CHASE', chase)).toBe(chase)
    const cab = orbitConfigFor('CAB', chase)
    expect(cab.pitchMinDeg).toBe(CAB_PITCH_MIN_DEG)
    expect(cab.pitchMaxDeg).toBe(CAB_PITCH_MAX_DEG)
    expect(cab.distanceM).toBe(chase.distanceM)
    expect(cab.lateralOffsetM).toBe(chase.lateralOffsetM)
    expect(CAB_PITCH_MIN_DEG).toBeLessThan(0)
    expect(CAB_PITCH_MAX_DEG).toBeGreaterThan(chase.pitchMaxDeg)
    expect(defaultPitchDegFor('CHASE', chase)).toBe(chase.defaultPitchDeg)
    expect(defaultPitchDegFor('CAB', chase)).toBe(CAB_DEFAULT_PITCH_DEG)
    expect(CAB_DEFAULT_PITCH_DEG).toBe(0)
  })

  it('the first-person eye is the driver seat inside the cab box of every truck, inside its collider', () => {
    for (const p of VEHICLE_PRESETS) {
      const eye = firstPersonEyeOffset('VEHICLE', p)
      const layout = truckLayout(p)
      expect(eye).toEqual(layout.cabEye)
      const cab = layout.boxes.find((b) => b.id === 'CAB')!
      const half = vehicleBoxHalfExtents(p)
      for (const k of [0, 1, 2] as const) {
        expect(eye[k]).toBeGreaterThan(cab.center[k] - cab.size[k] / 2)
        expect(eye[k]).toBeLessThan(cab.center[k] + cab.size[k] / 2)
        expect(Math.abs(eye[k])).toBeLessThan(half[k])
      }
      // left-hand seat, ahead of the body centre, between 2.3 and 2.9 m above the floor
      expect(eye[0]).toBeLessThan(0)
      expect(eye[2]).toBeLessThan(0)
      const aboveFloor = eye[1] + p.heightM / 2
      expect(aboveFloor).toBeGreaterThan(2.3)
      expect(aboveFloor).toBeLessThan(2.9)
    }
    // the miner's eye on the body axis, the drone's eye at its front
    expect(firstPersonEyeOffset('PERSON', vehiclePreset('UG_ADT_45T'))).toEqual([
      0,
      PERSON_CONFIG.eyeHeightM - PERSON_CONFIG.bodyHeightM / 2,
      0,
    ])
    const drone = firstPersonEyeOffset('DRONE', vehiclePreset('UG_ADT_45T'))
    expect(drone[0]).toBe(0)
    expect(drone[1]).toBe(0)
    expect(drone[2]).toBeLessThan(0)
    expect(Math.abs(drone[2])).toBeLessThan(DRONE_CONFIG.bodyRadiusM)
  })

  it('the lamp point is the truck headlights midpoint, the eye for the other bodies', () => {
    for (const p of VEHICLE_PRESETS) {
      const lamp = lampOffset('VEHICLE', p)
      const layout = truckLayout(p)
      expect(lamp[0]).toBeCloseTo(0, 12) // between the two headlights
      expect(lamp[2]).toBeCloseTo(-p.lengthM / 2 - 0.02, 12) // on the front bumper
      expect(lamp[1]).toBeCloseTo(layout.chassisY + layout.chassisH * 0.3, 12)
      // low on the body: below the driver's eye, above the floor
      expect(lamp[1]).toBeLessThan(layout.cabEye[1])
      expect(lamp[1]).toBeGreaterThan(layout.floor)
    }
    const p45 = vehiclePreset('UG_ADT_45T')
    expect(lampOffset('PERSON', p45)).toEqual(firstPersonEyeOffset('PERSON', p45))
    expect(lampOffset('DRONE', p45)).toEqual(firstPersonEyeOffset('DRONE', p45))
  })

  it('body-frame offsets rotate with the body yaw and the cab pose looks along the orbit', () => {
    const left = rotateOffsetByYaw([0, 1, -1], Math.PI / 2)
    expect(left[0]).toBeCloseTo(-1, 12) // forward (−Z) turned left is −X
    expect(left[1]).toBe(1)
    expect(left[2]).toBeCloseTo(0, 12)
    const seat = rotateOffsetByYaw([-0.5, 0, -2], Math.PI)
    expect(seat[0]).toBeCloseTo(0.5, 12)
    expect(seat[2]).toBeCloseTo(2, 12)
    expect(rotateOffsetByYaw([0.3, 0.2, -0.7], 0)).toEqual([0.3, 0.2, -0.7])
    const pose = cabPose([10, 2, -5], 0.4, -0.2)
    expect(pose.position).toEqual([10, 2, -5])
    const d = viewDirection(0.4, -0.2)
    expect(pose.lookAt[0]).toBeCloseTo(10 + d[0], 12)
    expect(pose.lookAt[1]).toBeCloseTo(2 + d[1], 12)
    expect(pose.lookAt[2]).toBeCloseTo(-5 + d[2], 12)
  })

  it('presentation: the chased truck is a ghost, the cab view hides the cab shell or the avatar', () => {
    expect(avatarPresentation('VEHICLE', 'CHASE')).toEqual({
      visible: true,
      ghost: true,
      cabVisible: true,
    })
    expect(avatarPresentation('PERSON', 'CHASE')).toEqual({
      visible: true,
      ghost: false,
      cabVisible: true,
    })
    expect(avatarPresentation('DRONE', 'CHASE').ghost).toBe(false)
    // the cab view keeps the ghost: looking down shows the own hood as an
    // outline over the floor, never a solid lamp-lit plane
    expect(avatarPresentation('VEHICLE', 'CAB')).toEqual({
      visible: true,
      ghost: true,
      cabVisible: false,
    })
    expect(avatarPresentation('PERSON', 'CAB').visible).toBe(false)
    expect(avatarPresentation('DRONE', 'CAB').visible).toBe(false)
    expect(GHOST_OPACITY).toBeGreaterThan(0.2)
    expect(GHOST_OPACITY).toBeLessThan(0.5)
  })
})

describe('frame coverage of the truck body (PR-6 measurement)', () => {
  /** the chase pose of a truck at the body origin, yaw 0, unobstructed */
  function chaseOf(presetId: (typeof VEHICLE_PRESETS)[number]['id']) {
    const cfg = chaseFor('VEHICLE', presetId)
    const nav = navigationBody('VEHICLE', presetId)
    const anchor: Vec3 = [0, nav.eyeHeightM - nav.bodyHeightM / 2, 0]
    return resolveChase(anchor, 0, cfg.defaultPitchDeg * DEG, cfg, () => null)
  }

  it('the chased 45 t body covers a large share of the frame — the complaint, measured', () => {
    const layout = truckLayout(vehiclePreset('UG_ADT_45T'))
    const pose = chaseOf('UG_ADT_45T')
    const whole = frameCoverage(pose.position, pose.lookAt, layout.boxes)
    const centre = frameCoverage(pose.position, pose.lookAt, layout.boxes, CENTRE_THIRD)
    const lane = frameCoverage(pose.position, pose.lookAt, layout.boxes, FORWARD_LANE)
    // measured at 320 × 190: 18.0 % of the frame, 24.9 % of the central third,
    // 50.9 % of the forward lane (60 t 21.3 / 27.6 / 58.3, RDT 22.3 / 31.7 /
    // 61.9 — docs/findings/pr6-truck-views.md); a change here is a chase-line
    // or layout change and must be explained there
    expect(whole).toBeGreaterThan(0.15)
    expect(whole).toBeLessThan(0.3)
    expect(centre).toBeGreaterThan(0.2)
    expect(lane).toBeGreaterThan(0.45)
    // the ghost does not change the geometry: the same coverage, drawn at GHOST_OPACITY
  })

  it('the cab view of every truck sees a clear way ahead: no body part in the frame at level pitch or looking 10° down', () => {
    for (const p of VEHICLE_PRESETS) {
      const layout = truckLayout(p)
      const shown = layout.boxes.filter((b) => b.id !== 'CAB' && b.id !== 'CAB_GLASS')
      const eye = firstPersonEyeOffset('VEHICLE', p)
      for (const pitchDeg of [CAB_DEFAULT_PITCH_DEG, -10, 20]) {
        const pose = cabPose(eye, 0, pitchDeg * DEG)
        expect(frameCoverage(pose.position, pose.lookAt, shown)).toBe(0)
      }
      // looking 20° down the articulated trucks see their own bumper at the
      // frame bottom (measured 17.2 % / 11.9 %), as a real cab does; never
      // the lane ahead
      const down = cabPose(eye, 0, -20 * DEG)
      expect(frameCoverage(down.position, down.lookAt, shown)).toBeLessThan(0.2)
      expect(frameCoverage(down.position, down.lookAt, shown, FORWARD_LANE)).toBe(0)
      // the cab shell itself would surround the camera — it is not drawn in the cab view
      const shell = layout.boxes.filter((b) => b.id === 'CAB')
      expect(frameCoverage(cabPose(eye, 0, 0).position, cabPose(eye, 0, 0).lookAt, shell)).toBe(1)
    }
  })
})
