/**
 * Walkthrough navigation modes (Phase 16 §3–9, hardening PR-4 W2 third
 * person): PERSON / VEHICLE / DRONE are ephemeral frontend runtime proxies
 * for mine inspection — never pedestrian biomechanics, vehicle dynamics or
 * UAV flight control, and never persisted into Scenario. All modes share
 * the exact Phase 06 / Phase 20B excavation collision geometry and the
 * temporal barriers; no mode is noclip. Since PR-4 every mode is driven in
 * THIRD PERSON: a rendered avatar moves on a kinematic character controller
 * and a chase camera orbits it (`chaseCamera.ts`).
 */
import type { ChaseConfig } from './chaseCamera'
import type { MovementKeys } from './movement'
import { DEFAULT_VEHICLE_PRESET, vehiclePreset, type VehiclePresetId } from './vehicle'

export type WalkthroughNavigationMode = 'PERSON' | 'VEHICLE' | 'DRONE'
export const NAVIGATION_MODES: readonly WalkthroughNavigationMode[] = ['PERSON', 'VEHICLE', 'DRONE']

export interface NavigationBodyConfig {
  /** total upright body height, m (capsule incl. caps / box height) */
  bodyHeightM: number
  bodyRadiusM: number
  /** avatar eye / chase anchor height above the floor, m */
  eyeHeightM: number
  /** 0 = free flight (no gravity), 1 = grounded locomotion */
  gravityScale: 0 | 1
}

export interface PersonConfig extends NavigationBodyConfig {
  walkSpeedMps: number
  runSpeedMps: number
}

export interface VehicleConfig extends NavigationBodyConfig {
  speedMps: number
  boostSpeedMps: number
}

export interface DroneConfig extends NavigationBodyConfig {
  horizontalSpeedMps: number
  boostSpeedMps: number
  verticalSpeedMps: number
}

/**
 * Kinematic character-controller settings per mode (PR-4 W1b). Autostep is
 * sized for the real floor residuals the backend documents (the rule-188
 * un-banked wall-line offset ≈ 0.2 m at a turnout, the sill strips) and a
 * truck's wheel climb — it is never a substitute for an open doorway: the
 * backend doorway probe (`tests/test_junction_passability.py`) proves every
 * declared junction open along its traffic section at 0.3 m above the floor
 * WITHOUT any step assistance.
 */
export interface LocomotionConfig {
  gravity: boolean
  autostepMaxHeightM: number
  autostepMinWidthM: number
  snapToGroundM: number
  maxSlopeClimbDeg: number
  minSlopeSlideDeg: number
}

export const PERSON_CONFIG: PersonConfig = {
  bodyHeightM: 1.7,
  bodyRadiusM: 0.3,
  eyeHeightM: 1.6,
  gravityScale: 1,
  walkSpeedMps: 4.0,
  runSpeedMps: 7.0,
}

/** speeds shared by every vehicle preset (the preset supplies the body) */
export const VEHICLE_CONFIG: VehicleConfig = {
  bodyHeightM: vehiclePreset(DEFAULT_VEHICLE_PRESET).heightM,
  bodyRadiusM: vehiclePreset(DEFAULT_VEHICLE_PRESET).widthM / 2,
  eyeHeightM: vehiclePreset(DEFAULT_VEHICLE_PRESET).eyeHeightM,
  gravityScale: 1,
  speedMps: 8.0,
  boostSpeedMps: 12.0,
}

export const DRONE_CONFIG: DroneConfig = {
  bodyHeightM: 0.7, // small inspection body (halfHeight 0 → near-sphere)
  bodyRadiusM: 0.35,
  eyeHeightM: 0.35,
  gravityScale: 0,
  horizontalSpeedMps: 7.0,
  boostSpeedMps: 13.0,
  verticalSpeedMps: 5.0,
}

export const PERSON_LOCOMOTION: LocomotionConfig = {
  gravity: true,
  autostepMaxHeightM: 0.35,
  autostepMinWidthM: 0.2,
  snapToGroundM: 0.3,
  maxSlopeClimbDeg: 50,
  minSlopeSlideDeg: 60,
}

export const VEHICLE_LOCOMOTION: LocomotionConfig = {
  gravity: true,
  autostepMaxHeightM: 0.5,
  autostepMinWidthM: 0.3,
  snapToGroundM: 0.4,
  maxSlopeClimbDeg: 35,
  minSlopeSlideDeg: 45,
}

export const DRONE_LOCOMOTION: LocomotionConfig = {
  gravity: false,
  autostepMaxHeightM: 0,
  autostepMinWidthM: 0,
  snapToGroundM: 0,
  maxSlopeClimbDeg: 90,
  minSlopeSlideDeg: 90,
}

export const PERSON_CHASE: ChaseConfig = {
  distanceM: 4.5,
  minDistanceM: 1.0,
  pitchMinDeg: -65,
  pitchMaxDeg: 25,
  defaultPitchDeg: -14,
  occlusionPaddingM: 0.35,
  lateralOffsetM: 0,
  anchorBackM: 0,
  lookAheadM: 1.5,
}

export const DRONE_CHASE: ChaseConfig = {
  distanceM: 3.5,
  minDistanceM: 0.8,
  pitchMinDeg: -70,
  pitchMaxDeg: 30,
  defaultPitchDeg: -18,
  occlusionPaddingM: 0.3,
  lateralOffsetM: 0,
  anchorBackM: 0,
  lookAheadM: 1.0,
}

/**
 * The truck is chased by a TAIL camera: the camera line is anchored just
 * behind the dump body's top (`anchorBackM` ≈ half the length), shifted
 * 0.9 m right and 5 m back at 18° elevation (camera ≈ 4.4 m above the
 * floor for the 2.9 m body — under the 4.8 m arch at 0.9 m lateral of the
 * default 5 × 5 m horseshoe), AIMED one body length ahead (`lookAheadM`)
 * so the bin fills the lower part of the frame and the drive ahead the
 * centre (measured on tour 6: aimed at the tail itself, the bin took the
 * frame from the upper quarter down). A 5 m drive has
 * no room for a long look-down line behind a 3 m tall body (measured on the
 * acceptance tours: a cab-anchored 10 m line was pulled by the roof to the
 * bin's rear face, and a 4 m / 12° tail line still saw mostly the bin), so
 * the line is short and `resolveChase` flattens it pitch by pitch where the
 * roof is lower (the 3.4 m body, a curve) and pulls it in against walls.
 */
export function vehicleChase(presetId: VehiclePresetId): ChaseConfig {
  const p = vehiclePreset(presetId)
  return {
    distanceM: 5.0,
    minDistanceM: 1.5,
    pitchMinDeg: -45,
    pitchMaxDeg: 15,
    defaultPitchDeg: -18,
    occlusionPaddingM: 0.3,
    lateralOffsetM: 0.9,
    anchorBackM: p.lengthM / 2 - 0.3,
    lookAheadM: p.lengthM,
  }
}

export function navigationBody(
  mode: WalkthroughNavigationMode,
  presetId: VehiclePresetId = DEFAULT_VEHICLE_PRESET,
): NavigationBodyConfig {
  if (mode === 'PERSON') return PERSON_CONFIG
  if (mode === 'VEHICLE') {
    const p = vehiclePreset(presetId)
    return {
      bodyHeightM: p.heightM,
      bodyRadiusM: p.widthM / 2,
      eyeHeightM: p.eyeHeightM,
      gravityScale: 1,
    }
  }
  return DRONE_CONFIG
}

export function locomotionFor(mode: WalkthroughNavigationMode): LocomotionConfig {
  if (mode === 'PERSON') return PERSON_LOCOMOTION
  if (mode === 'VEHICLE') return VEHICLE_LOCOMOTION
  return DRONE_LOCOMOTION
}

export function chaseFor(
  mode: WalkthroughNavigationMode,
  presetId: VehiclePresetId = DEFAULT_VEHICLE_PRESET,
): ChaseConfig {
  if (mode === 'PERSON') return PERSON_CHASE
  if (mode === 'VEHICLE') return vehicleChase(presetId)
  return DRONE_CHASE
}

/** PERSON speed: walking by default, run while Shift is held (§5). Sprint
 * never touches vertical velocity — this is a horizontal magnitude only. */
export function personSpeed(boost: boolean, config: PersonConfig = PERSON_CONFIG): number {
  return boost ? config.runSpeedMps : config.walkSpeedMps
}

/**
 * Vehicle drive velocity along the vehicle HEADING (PR-4: the heading is the
 * avatar's own yaw integrated by `vehicle.ts::integrateHeading`; the camera
 * follows it). W/S drive forward / reverse at a bounded speed (Shift boost).
 * No strafing, no vertical user motion.
 */
export function vehicleDriveVelocity(
  keys: { forward: boolean; backward: boolean; boost: boolean },
  heading: number,
  config: VehicleConfig = VEHICLE_CONFIG,
): [number, number] {
  const drive = (keys.forward ? 1 : 0) - (keys.backward ? 1 : 0)
  const speed = (keys.boost ? config.boostSpeedMps : config.speedMps) * drive
  return [-Math.sin(heading) * speed, -Math.cos(heading) * speed]
}

/** Signed drive speed (m/s) for the heading integration: + forward, − reverse. */
export function vehicleSignedSpeed(
  keys: { forward: boolean; backward: boolean; boost: boolean },
  config: VehicleConfig = VEHICLE_CONFIG,
): number {
  const drive = (keys.forward ? 1 : 0) - (keys.backward ? 1 : 0)
  return (keys.boost ? config.boostSpeedMps : config.speedMps) * drive
}

/**
 * Drone velocity: W/S move along the view direction (yaw + pitch), A/D
 * strafe horizontally, Space/C add direct vertical on top, Shift boosts the
 * whole flight vector. In third person the runtime passes the HORIZONTAL
 * heading (pitch 0) and leaves climbing to Space/C, so the chase camera's
 * look-down angle never becomes a flight attitude. Gravity stays off; the
 * excavation trimesh + temporal barriers remain the boundary — never noclip.
 */
export function droneVelocity(
  keys: MovementKeys & { boost: boolean },
  vertical: { up: boolean; down: boolean },
  yaw: number,
  pitch: number,
  config: DroneConfig = DRONE_CONFIG,
): [number, number, number] {
  const cp = Math.cos(pitch)
  const sp = Math.sin(pitch)
  const fx = -Math.sin(yaw) * cp
  const fy = sp
  const fz = -Math.cos(yaw) * cp
  const rx = Math.cos(yaw)
  const rz = -Math.sin(yaw)
  let dx = 0
  let dy = 0
  let dz = 0
  if (keys.forward) {
    dx += fx
    dy += fy
    dz += fz
  }
  if (keys.backward) {
    dx -= fx
    dy -= fy
    dz -= fz
  }
  if (keys.right) {
    dx += rx
    dz += rz
  }
  if (keys.left) {
    dx -= rx
    dz -= rz
  }
  const len = Math.hypot(dx, dy, dz)
  const speed = keys.boost ? config.boostSpeedMps : config.horizontalSpeedMps
  let vx = 0
  let vy = 0
  let vz = 0
  if (len > 1e-9) {
    vx = (dx / len) * speed
    vy = (dy / len) * speed
    vz = (dz / len) * speed
  }
  vy += (vertical.up ? config.verticalSpeedMps : 0) - (vertical.down ? config.verticalSpeedMps : 0)
  return [vx, vy, vz]
}

/** Guard for HUD/store input: unknown strings never become a mode. */
export function isNavigationMode(v: unknown): v is WalkthroughNavigationMode {
  return v === 'PERSON' || v === 'VEHICLE' || v === 'DRONE'
}
