/**
 * Third-person VEHICLE presets and heading math (hardening PR-4 W2, Park:
 * "차량은 실제 RDT나 ADT 크기 준용").
 *
 * The presets are REPRESENTATIVE PLANNING DIMENSIONS of three underground /
 * mine truck classes, rounded to 0.1 m — never a manufacturer's
 * specification, a certified clearance or a vehicle-dynamics model. They
 * size the kinematic box the walkthrough drives through the excavation
 * (the same Phase 06 / Phase 20B collision geometry every mode uses) so the
 * tunnel section (5 × 5 m default) can be read against a truck body; the
 * clearance readout is navigation information only.
 *
 *   UG_ADT_45T  underground articulated dump truck, 45 t payload class
 *               (≈ 10.5 × 3.0 × 2.9 m, outer turning radius ≈ 8.5 m)
 *   UG_ADT_60T  underground articulated dump truck, 60 t payload class
 *               (≈ 11.6 × 3.6 × 3.4 m, ≈ 9.5 m)
 *   RDT_40T     rigid dump truck, 40 t class — a surface / large-section
 *               body kept for comparison (≈ 9.0 × 3.6 × 3.3 m, ≈ 9.0 m)
 *
 * Heading follows a kinematic bicycle-like rule: yaw rate = speed / turning
 * radius, floored at `VEHICLE_MIN_STEER_SPEED_MPS` so a stopped truck can
 * still be aimed, capped at `VEHICLE_STEER_CAP_DEG_PER_SEC`; the steering
 * sense flips in reverse. Ephemeral runtime state, never persisted (rule 99).
 */

export type VehiclePresetId = 'UG_ADT_45T' | 'UG_ADT_60T' | 'RDT_40T'

export interface VehiclePreset {
  id: VehiclePresetId
  /** short HUD label */
  label: string
  /** what the class is — shown in the HUD note */
  classNote: string
  lengthM: number
  widthM: number
  heightM: number
  /** outer turning radius of the class, m (planning value) */
  turningRadiusM: number
  articulated: boolean
  wheelRadiusM: number
  /** chase-camera anchor height above the floor (cab roof line), m */
  eyeHeightM: number
}

export const VEHICLE_PRESETS: readonly VehiclePreset[] = [
  {
    id: 'UG_ADT_45T',
    label: 'UG ADT 45 t',
    classNote: 'underground articulated dump truck, 45 t class',
    lengthM: 10.5,
    widthM: 3.0,
    heightM: 2.9,
    turningRadiusM: 8.5,
    articulated: true,
    wheelRadiusM: 0.85,
    eyeHeightM: 2.9,
  },
  {
    id: 'UG_ADT_60T',
    label: 'UG ADT 60 t',
    classNote: 'underground articulated dump truck, 60 t class',
    lengthM: 11.6,
    widthM: 3.6,
    heightM: 3.4,
    turningRadiusM: 9.5,
    articulated: true,
    wheelRadiusM: 0.95,
    eyeHeightM: 3.4,
  },
  {
    id: 'RDT_40T',
    label: 'RDT 40 t',
    classNote: 'rigid dump truck, 40 t class (surface body, for comparison)',
    lengthM: 9.0,
    widthM: 3.6,
    heightM: 3.3,
    turningRadiusM: 9.0,
    articulated: false,
    wheelRadiusM: 1.0,
    eyeHeightM: 3.3,
  },
]

export const DEFAULT_VEHICLE_PRESET: VehiclePresetId = 'UG_ADT_45T'

/** Below this speed the heading still turns as if driving at it (so a
 * stopped truck can be aimed); an inspection convenience, not dynamics. */
export const VEHICLE_MIN_STEER_SPEED_MPS = 2.0
/** Hard cap of the heading rate, deg/s (no instant flips — Phase 16 §6). */
export const VEHICLE_STEER_CAP_DEG_PER_SEC = 60

export function isVehiclePresetId(v: unknown): v is VehiclePresetId {
  return VEHICLE_PRESETS.some((p) => p.id === v)
}

export function vehiclePreset(id: VehiclePresetId): VehiclePreset {
  const found = VEHICLE_PRESETS.find((p) => p.id === id)
  if (!found) throw new Error(`unknown vehicle preset ${String(id)}`)
  return found
}

/** The preset after `id` in declaration order (wraps around). */
export function nextVehiclePreset(id: VehiclePresetId): VehiclePresetId {
  const i = VEHICLE_PRESETS.findIndex((p) => p.id === id)
  return VEHICLE_PRESETS[(i + 1) % VEHICLE_PRESETS.length]!.id
}

/** Heading rate magnitude, rad/s, for a signed speed (bicycle rule). */
export function vehicleYawRate(speedMps: number, preset: VehiclePreset): number {
  const v = Math.max(Math.abs(speedMps), VEHICLE_MIN_STEER_SPEED_MPS)
  const cap = (VEHICLE_STEER_CAP_DEG_PER_SEC * Math.PI) / 180
  return Math.min(v / preset.turningRadiusM, cap)
}

/**
 * Integrate the vehicle heading (Three yaw: 0 → −Z, positive = left) for
 * one frame. A turns left while driving forward; the sense flips while
 * reversing, as the rear of a real vehicle swings. No input → unchanged.
 */
export function integrateHeading(
  heading: number,
  keys: { left: boolean; right: boolean },
  signedSpeedMps: number,
  dtSeconds: number,
  preset: VehiclePreset,
): number {
  const input = (keys.left ? 1 : 0) - (keys.right ? 1 : 0)
  if (input === 0) return heading
  const sense = signedSpeedMps < 0 ? -1 : 1
  return heading + input * sense * vehicleYawRate(signedSpeedMps, preset) * dtSeconds
}

/** Kinematic box half extents in the body frame: x = width, y = height,
 * z = length (the body drives along its local −Z, the camera convention). */
export function vehicleBoxHalfExtents(preset: VehiclePreset): [number, number, number] {
  return [preset.widthM / 2, preset.heightM / 2, preset.lengthM / 2]
}

/** Quaternion [x, y, z, w] of a rotation by `yaw` about +Y. */
export function yawQuaternion(yaw: number): [number, number, number, number] {
  return [0, Math.sin(yaw / 2), 0, Math.cos(yaw / 2)]
}

/** Side / head clearance of a preset inside a rectangular section (m);
 * navigation information for the HUD, never an engineering clearance. */
export function vehicleClearance(
  preset: VehiclePreset,
  tunnel: { tunnelWidth: number; tunnelHeight: number },
): { sideM: number; headM: number } {
  return {
    sideM: (tunnel.tunnelWidth - preset.widthM) / 2,
    headM: tunnel.tunnelHeight - preset.heightM,
  }
}

/** Axis-aligned box of the procedural truck in the BODY frame (origin at
 * the collider centre, +Y up, −Z forward): centre and full size. */
export interface TruckBox {
  id: 'FRONT_CHASSIS' | 'HOOD' | 'CAB' | 'CAB_GLASS' | 'REAR_CHASSIS' | 'BIN' | 'HINGE'
  center: [number, number, number]
  size: [number, number, number]
}

/**
 * The procedural truck's layout on the preset's planning box (hardening
 * PR-6 — one authority for `avatars.tsx::TruckAvatar` and the cab eye of
 * `cameraView.ts`). Articulated: front power unit + rear dump body on
 * separate chassis; rigid: one chassis. The cab is the left-hand box at
 * the very front (an underground truck's operator sits ahead of the
 * engine), the hood sits behind it, the bin top is EXACTLY the preset
 * height (the visual envelope never exceeds the collider box). `cabEye`
 * is the driver's eye inside the cab box — the first-person camera point
 * of the CAB view: cab centre line, window height, seat depth.
 */
export interface TruckLayout {
  floor: number
  axleY: number
  chassisH: number
  chassisY: number
  frontL: number
  rearL: number
  frontZ: number
  rearZ: number
  binH: number
  cabH: number
  boxes: readonly TruckBox[]
  /** wheel centres (x, z) at `axleY`, radius `wheelRadiusM` */
  wheels: readonly [number, number][]
  headlights: readonly [number, number, number][]
  cabEye: [number, number, number]
}

export function truckLayout(preset: VehiclePreset): TruckLayout {
  const L = preset.lengthM
  const W = preset.widthM
  const H = preset.heightM
  const floor = -H / 2
  const r = preset.wheelRadiusM
  const axleY = floor + r
  const frontL = preset.articulated ? L * 0.42 : L * 0.3
  const rearL = preset.articulated ? L * 0.52 : L * 0.68
  const frontZ = -L / 2 + frontL / 2
  const rearZ = L / 2 - rearL / 2
  const chassisH = Math.max(0.5, H * 0.22)
  const chassisY = axleY + chassisH / 2
  const binH = H - r - chassisH
  const cabH = H - r - chassisH
  const cabCenter: [number, number, number] = [
    -W * 0.18,
    chassisY + chassisH / 2 + cabH / 2,
    -L / 2 + frontL * 0.3,
  ]
  const boxes: TruckBox[] = [
    { id: 'FRONT_CHASSIS', center: [0, chassisY, frontZ], size: [W * 0.92, chassisH, frontL] },
    {
      id: 'HOOD',
      center: [0, chassisY + chassisH / 2 + H * 0.17, -L / 2 + frontL * 0.72],
      size: [W * 0.78, H * 0.34, frontL * 0.5],
    },
    { id: 'CAB', center: cabCenter, size: [W * 0.5, cabH, frontL * 0.42] },
    {
      id: 'CAB_GLASS',
      center: [cabCenter[0], cabCenter[1] + cabH * 0.15, cabCenter[2] - frontL * 0.215],
      size: [W * 0.42, cabH * 0.5, 0.02],
    },
    { id: 'REAR_CHASSIS', center: [0, chassisY, rearZ], size: [W * 0.92, chassisH, rearL] },
    {
      id: 'BIN',
      center: [0, chassisY + chassisH / 2 + binH / 2, rearZ + rearL * 0.02],
      size: [W, binH, rearL * 0.96],
    },
  ]
  if (preset.articulated) {
    boxes.push({
      id: 'HINGE',
      center: [0, chassisY, -L / 2 + frontL + (L - frontL - rearL) / 2],
      size: [W * 0.4, chassisH * 0.8, L - frontL - rearL + 0.2],
    })
  }
  const wheels: [number, number][] = [
    [-(W / 2 - 0.3), -L / 2 + frontL * 0.55],
    [W / 2 - 0.3, -L / 2 + frontL * 0.55],
    [-(W / 2 - 0.3), L / 2 - rearL * 0.45],
    [W / 2 - 0.3, L / 2 - rearL * 0.45],
  ]
  if (!preset.articulated) {
    wheels.push([-(W / 2 - 0.3), L / 2 - rearL * 0.15], [W / 2 - 0.3, L / 2 - rearL * 0.15])
  }
  const headlights: [number, number, number][] = [
    [-W * 0.3, chassisY + chassisH * 0.3, -L / 2 - 0.02],
    [W * 0.3, chassisY + chassisH * 0.3, -L / 2 - 0.02],
  ]
  // driver's eye: the cab's centre line, at the window band (the glass
  // pane's centre height), one seat depth behind the cab's centre plane
  const cabEye: [number, number, number] = [cabCenter[0], cabCenter[1] + cabH * 0.15, cabCenter[2]]
  return {
    floor,
    axleY,
    chassisH,
    chassisY,
    frontL,
    rearL,
    frontZ,
    rearZ,
    binH,
    cabH,
    boxes,
    wheels,
    headlights,
    cabEye,
  }
}
