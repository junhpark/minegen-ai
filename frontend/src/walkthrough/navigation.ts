/**
 * Walkthrough navigation modes (Phase 16 §3–9): PERSON / VEHICLE / DRONE
 * are ephemeral frontend runtime proxies for mine inspection — never
 * pedestrian biomechanics, vehicle dynamics or UAV flight control, and
 * never persisted into Scenario. All modes share the exact Phase 06
 * tunnel trimesh boundary and the temporal frontier; no mode is noclip.
 */
import type { LookKeys, MovementKeys } from './movement'

export type WalkthroughNavigationMode = 'PERSON' | 'VEHICLE' | 'DRONE'
export const NAVIGATION_MODES: readonly WalkthroughNavigationMode[] = ['PERSON', 'VEHICLE', 'DRONE']

export interface NavigationBodyConfig {
  /** total upright body height, m (capsule incl. caps) */
  bodyHeightM: number
  bodyRadiusM: number
  /** camera height above the floor, m */
  eyeHeightM: number
  /** rigid-body gravity scale (0 = free flight) */
  gravityScale: 0 | 1
}

export interface PersonConfig extends NavigationBodyConfig {
  walkSpeedMps: number
  runSpeedMps: number
}

export interface VehicleConfig extends NavigationBodyConfig {
  speedMps: number
  boostSpeedMps: number
  /** bounded steering yaw rate, deg/s (§6: no instant 180° flips) */
  steeringRateDegPerSec: number
}

export interface DroneConfig extends NavigationBodyConfig {
  horizontalSpeedMps: number
  boostSpeedMps: number
  verticalSpeedMps: number
}

export const PERSON_CONFIG: PersonConfig = {
  bodyHeightM: 1.7,
  bodyRadiusM: 0.3,
  eyeHeightM: 1.6,
  gravityScale: 1,
  walkSpeedMps: 2.0,
  runSpeedMps: 5.8,
}

export const VEHICLE_CONFIG: VehicleConfig = {
  bodyHeightM: 2.0,
  bodyRadiusM: 0.9,
  eyeHeightM: 2.2,
  gravityScale: 1,
  speedMps: 8.0,
  boostSpeedMps: 12.0,
  steeringRateDegPerSec: 60,
}

export const DRONE_CONFIG: DroneConfig = {
  bodyHeightM: 0.7, // small inspection capsule (halfHeight 0 -> near-sphere)
  bodyRadiusM: 0.35,
  eyeHeightM: 0.35, // camera at body center height above its own floor ref
  gravityScale: 0,
  horizontalSpeedMps: 7.0,
  boostSpeedMps: 13.0,
  verticalSpeedMps: 5.0,
}

export function navigationBody(mode: WalkthroughNavigationMode): NavigationBodyConfig {
  if (mode === 'PERSON') return PERSON_CONFIG
  if (mode === 'VEHICLE') return VEHICLE_CONFIG
  return DRONE_CONFIG
}

/** PERSON speed: walking by default, run while Shift is held (§5). Sprint
 * never touches vertical velocity — this is a horizontal magnitude only. */
export function personSpeed(boost: boolean, config: PersonConfig = PERSON_CONFIG): number {
  return boost ? config.runSpeedMps : config.walkSpeedMps
}

export interface VehicleState {
  /** movement heading (Three yaw convention), decoupled from camera look */
  headingYaw: number
}

/**
 * Vehicle navigation step (§6): W/S drive along a heading that A/D steer
 * at a bounded dt-scaled rate — smoother than strafing, no instantaneous
 * direction flips, no vertical user motion (gravity keeps the body on the
 * road). Reverse uses the same bounded speed.
 */
export function vehicleStep(
  state: VehicleState,
  keys: MovementKeys & { boost: boolean },
  dtSeconds: number,
  config: VehicleConfig = VEHICLE_CONFIG,
): { headingYaw: number; vx: number; vz: number } {
  const rate = (config.steeringRateDegPerSec * Math.PI) / 180
  let heading = state.headingYaw
  if (keys.left) heading += rate * dtSeconds
  if (keys.right) heading -= rate * dtSeconds
  const drive = (keys.forward ? 1 : 0) - (keys.backward ? 1 : 0)
  const speed = (keys.boost ? config.boostSpeedMps : config.speedMps) * drive
  return { headingYaw: heading, vx: -Math.sin(heading) * speed, vz: -Math.cos(heading) * speed }
}

/**
 * Drone velocity (§8–9): WASD horizontal from camera YAW only (diagonals
 * normalized), Space/C vertical at a fixed rate, Shift boosts the
 * horizontal magnitude. Gravity is off; the exact tunnel trimesh and the
 * temporal frontier remain the collision boundary — never noclip.
 */
export function droneVelocity(
  keys: MovementKeys & { boost: boolean },
  vertical: { up: boolean; down: boolean },
  yaw: number,
  config: DroneConfig = DRONE_CONFIG,
): [number, number, number] {
  const fx = -Math.sin(yaw)
  const fz = -Math.cos(yaw)
  const rx = Math.cos(yaw)
  const rz = -Math.sin(yaw)
  let dx = 0
  let dz = 0
  if (keys.forward) {
    dx += fx
    dz += fz
  }
  if (keys.backward) {
    dx -= fx
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
  const len = Math.hypot(dx, dz)
  const speed = keys.boost ? config.boostSpeedMps : config.horizontalSpeedMps
  const vx = len > 1e-9 ? (dx / len) * speed : 0
  const vz = len > 1e-9 ? (dz / len) * speed : 0
  const vy =
    (vertical.up ? config.verticalSpeedMps : 0) - (vertical.down ? config.verticalSpeedMps : 0)
  return [vx, vy, vz]
}

/** Guard for HUD/store input: unknown strings never become a mode. */
export function isNavigationMode(v: unknown): v is WalkthroughNavigationMode {
  return v === 'PERSON' || v === 'VEHICLE' || v === 'DRONE'
}

export interface LookKeysRef {
  look: LookKeys
}
