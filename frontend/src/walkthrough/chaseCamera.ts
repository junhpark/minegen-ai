/**
 * Third-person chase camera math (hardening PR-4 W2). Pure: the camera
 * orbits an ANCHOR (the avatar's eye point) at a mode-specific distance;
 * IJKL rotate the orbit (yaw / pitch, dt-scaled, pitch clamped so the camera
 * never dives below the floor or flips over the top); the runtime pulls the
 * camera in along the view line when an authoritative collider stands
 * between the anchor and the desired position (`pullIn`). Runtime
 * presentation only — never engineering geometry, never persisted.
 */
import type { LookKeys } from './movement'

export interface ChaseConfig {
  /** nominal camera distance behind the anchor, m */
  distanceM: number
  /** the occlusion pull-in never brings the camera closer than this, m —
   * for a truck, behind its own body (half length + a margin) */
  minDistanceM: number
  /** view pitch clamp, deg (negative = looking down at the avatar) */
  pitchMinDeg: number
  pitchMaxDeg: number
  /** view pitch at spawn / reset, deg */
  defaultPitchDeg: number
  /** gap kept between the camera and the occluding surface, m */
  occlusionPaddingM: number
  /** over-the-shoulder offset of the camera line to the avatar's right, m
   * (a truck fills a 5 m drive; the offset keeps part of the way ahead
   * visible beside it) */
  lateralOffsetM: number
  /** shift of the camera line's anchor toward the avatar's rear, m — a
   * truck is chased from just behind its dump body (tail camera), a person
   * from its eye */
  anchorBackM: number
  /** the camera aims this far AHEAD of its base point along the view
   * azimuth, m (0 = at the base): a truck looks one body length ahead so
   * the bin sits in the lower part of the frame and the drive in the
   * centre; a person just over the avatar's head */
  lookAheadM: number
}

export interface OrbitState {
  yaw: number
  pitch: number
}

export type Vec3 = [number, number, number]

const DEG = Math.PI / 180

/** (−π, π] */
export function wrapAngle(a: number): number {
  let x = a % (2 * Math.PI)
  if (x <= -Math.PI) x += 2 * Math.PI
  if (x > Math.PI) x -= 2 * Math.PI
  return x
}

/** Orbit update: J/L yaw (positive = left, the Three convention), I/K pitch
 * (I looks up), dt-scaled, pitch clamped to the config. */
export function applyOrbit(
  state: OrbitState,
  keys: LookKeys,
  dtSeconds: number,
  speeds: { yawSpeedDegPerSec: number; pitchSpeedDegPerSec: number },
  cfg: ChaseConfig,
): OrbitState {
  const yawStep = speeds.yawSpeedDegPerSec * DEG * dtSeconds
  const pitchStep = speeds.pitchSpeedDegPerSec * DEG * dtSeconds
  let yaw = state.yaw
  let pitch = state.pitch
  if (keys.yawLeft) yaw += yawStep
  if (keys.yawRight) yaw -= yawStep
  if (keys.pitchUp) pitch += pitchStep
  if (keys.pitchDown) pitch -= pitchStep
  const lo = cfg.pitchMinDeg * DEG
  const hi = cfg.pitchMaxDeg * DEG
  if (pitch < lo) pitch = lo
  if (pitch > hi) pitch = hi
  return { yaw, pitch }
}

/** Unit view direction for a yaw / pitch (yaw 0 → −Z, pitch > 0 looks up). */
export function viewDirection(yaw: number, pitch: number): Vec3 {
  const cp = Math.cos(pitch)
  return [-Math.sin(yaw) * cp, Math.sin(pitch), -Math.cos(yaw) * cp]
}

/** Camera position for an anchor, orbit and distance: the camera sits
 * `distance` behind the anchor along the view line and looks at it. */
export function chaseCameraPose(
  anchor: Vec3,
  yaw: number,
  pitch: number,
  distanceM: number,
): { position: Vec3; lookAt: Vec3 } {
  const d = viewDirection(yaw, pitch)
  return {
    position: [
      anchor[0] - d[0] * distanceM,
      anchor[1] - d[1] * distanceM,
      anchor[2] - d[2] * distanceM,
    ],
    lookAt: anchor,
  }
}

/** Effective camera distance after an occlusion cast from the anchor toward
 * the desired position: the hit distance minus the padding, never below the
 * configured minimum; no hit keeps the desired distance. */
export function pullIn(desiredM: number, hitDistanceM: number | null, cfg: ChaseConfig): number {
  if (hitDistanceM === null || !(hitDistanceM < desiredM)) return desiredM
  return Math.max(hitDistanceM - cfg.occlusionPaddingM, cfg.minDistanceM)
}

/** Shortest-arc interpolation between two yaws. */
export function lerpAngle(a: number, b: number, t: number): number {
  return a + wrapAngle(b - a) * Math.min(Math.max(t, 0), 1)
}

/** Unit right vector of a yaw (yaw 0 → −Z, right = +X). */
export function rightOf(yaw: number): Vec3 {
  return [Math.cos(yaw), 0, -Math.sin(yaw)]
}

/** Unit horizontal rear vector of a yaw (yaw 0 → +Z). */
export function backOf(yaw: number): Vec3 {
  return [Math.sin(yaw), 0, Math.cos(yaw)]
}

/** Pitch candidates tried when the nominal view line is blocked before the
 * minimum distance: flatten the view step by step (looking down from behind
 * a truck in a low drive hits the roof first), then slightly upward. */
export function pitchFallbacks(pitch: number): number[] {
  const out = [pitch]
  if (pitch < 0) out.push(pitch * 0.5, 0, 6 * DEG)
  else out.push(0, -6 * DEG)
  return out
}

export interface ChaseResolution {
  position: Vec3
  lookAt: Vec3
  /** the pitch actually used (a fallback when the nominal line was blocked) */
  pitch: number
  distance: number
  /** the nominal line was blocked before the minimum distance at every pitch */
  cramped: boolean
}

/** Closest the cramped camera ever sits to its base point (m): just past
 * the render near plane, so a body against a wall gives a close-up rather
 * than a view from inside the rock. */
export const CRAMPED_FLOOR_M = 0.2

/**
 * Resolve the chase pose with an occlusion caster: `cast(origin, dir, max)`
 * returns the hit distance along `dir` (unit) from `origin`, or null. The
 * camera line starts at the anchor shifted by the lateral offset and aims
 * `lookAheadM` ahead of that base along the view azimuth; the first pitch
 * whose line is clear up to the minimum distance wins and is pulled in to
 * its hit. When every pitch is blocked inside the minimum distance the
 * camera is `cramped`: it takes the pitch with the LONGEST clear line and
 * sits at that line's clear point (hit − padding, floored at
 * `CRAMPED_FLOOR_M`) — never beyond a hit. Measured on the acceptance tour:
 * the old rule kept the minimum distance and put the camera 1 m outside the
 * portal plane behind a truck at the spawn. Pure apart from the caster.
 */
export function resolveChase(
  anchor: Vec3,
  yaw: number,
  pitch: number,
  cfg: ChaseConfig,
  cast: (origin: Vec3, dir: Vec3, maxDistance: number) => number | null,
): ChaseResolution {
  const r = rightOf(yaw)
  const b = backOf(yaw)
  const base: Vec3 = [
    anchor[0] + r[0] * cfg.lateralOffsetM + b[0] * cfg.anchorBackM,
    anchor[1] + r[1] * cfg.lateralOffsetM + b[1] * cfg.anchorBackM,
    anchor[2] + r[2] * cfg.lateralOffsetM + b[2] * cfg.anchorBackM,
  ]
  const lookAt: Vec3 = [
    base[0] - b[0] * cfg.lookAheadM,
    base[1] - b[1] * cfg.lookAheadM,
    base[2] - b[2] * cfg.lookAheadM,
  ]
  let bestPitch = pitch
  let bestClear = -Infinity
  for (const candidate of pitchFallbacks(pitch)) {
    const d = viewDirection(yaw, candidate)
    const back: Vec3 = [-d[0], -d[1], -d[2]]
    const hit = cast(base, back, cfg.distanceM)
    if (hit !== null && hit - cfg.occlusionPaddingM < cfg.minDistanceM) {
      const clear = hit - cfg.occlusionPaddingM
      if (clear > bestClear) {
        bestClear = clear
        bestPitch = candidate
      }
      continue
    }
    const distance = pullIn(cfg.distanceM, hit, cfg)
    const pose = chaseCameraPose(base, yaw, candidate, distance)
    return { position: pose.position, lookAt, pitch: candidate, distance, cramped: false }
  }
  const distance = Math.max(bestClear, CRAMPED_FLOOR_M)
  const pose = chaseCameraPose(base, yaw, bestPitch, distance)
  return { position: pose.position, lookAt, pitch: bestPitch, distance, cramped: true }
}
