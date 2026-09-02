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
  walkSpeedMps: 4.0,
  runSpeedMps: 7.0,
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

/**
 * Vehicle drive velocity (hotfix 2): the vehicle drives WHERE THE CAMERA
 * LOOKS — one mental model, no hidden heading state. W/S drive
 * forward/reverse along the camera yaw at a bounded speed (Shift boost);
 * A/D contribute additional yaw steering (see vehicleSteerDelta) so both
 * A/D and J/L turn the same camera. No strafing, no vertical user motion.
 */
export function vehicleDriveVelocity(
  keys: { forward: boolean; backward: boolean; boost: boolean },
  yaw: number,
  config: VehicleConfig = VEHICLE_CONFIG,
): [number, number] {
  const drive = (keys.forward ? 1 : 0) - (keys.backward ? 1 : 0)
  const speed = (keys.boost ? config.boostSpeedMps : config.speedMps) * drive
  return [-Math.sin(yaw) * speed, -Math.cos(yaw) * speed]
}

/**
 * Bounded A/D steering as a camera-yaw delta (dt-scaled, 60 deg/s):
 * applied ON TOP of the shared IJKL look, so the drive direction is
 * always exactly the view direction.
 */
export function vehicleSteerDelta(
  keys: { left: boolean; right: boolean },
  dtSeconds: number,
  config: VehicleConfig = VEHICLE_CONFIG,
): number {
  const rate = (config.steeringRateDegPerSec * Math.PI) / 180
  let d = 0
  if (keys.left) d += rate * dtSeconds
  if (keys.right) d -= rate * dtSeconds
  return d
}

/**
 * Drone velocity (hotfix 2): FULL 3D camera-direction flight. W/S move
 * along the exact camera view direction (yaw + pitch) so following a
 * declining tunnel is just "look along it and press W" — the previous
 * horizontal-only model forced constant manual descent. A/D strafe
 * horizontally, Space/C add direct vertical on top, Shift boosts the
 * whole flight vector. Gravity stays off; the tunnel trimesh + temporal
 * frontier remain the collision boundary — never noclip.
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

export interface LookKeysRef {
  look: LookKeys
}
