/**
 * Shared pose builder for ephemeral runtime barriers (frontier, aperture
 * pieces, PR-4 temporal plugs): a thin cuboid centred on a mine-space point,
 * oriented by a gravity-aligned frame around a mine-space forward direction,
 * converted ONCE through the canonical mine→Three rotation (a pure rotation,
 * so the right-handed basis survives and the quaternion is well defined).
 * Access-control geometry only (rule 115 analogue): never excavation
 * geometry, never persisted, never exported.
 */
import { Matrix4, Quaternion, Vector3 } from 'three'
import { mineToThree } from '@/geometry/coordinateTransform'

export type Vec3 = [number, number, number]

export function norm3(v: Vec3): Vec3 | null {
  const l = Math.hypot(v[0], v[1], v[2])
  if (!(l > 1e-9)) return null
  return [v[0] / l, v[1] / l, v[2] / l]
}

export function cross3(a: Vec3, b: Vec3): Vec3 {
  return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
}

/** gravity-aligned up for a unit forward (rule 26): Z minus its forward component */
export function gravityUp(forward: Vec3): Vec3 | null {
  const dz = forward[2]
  return norm3([-dz * forward[0], -dz * forward[1], 1 - dz * forward[2]])
}

export interface BarrierPose {
  /** cuboid CENTER, Three coordinates */
  positionThree: Vec3
  /** orientation quaternion [x, y, z, w], Three coordinates */
  quaternion: [number, number, number, number]
  /** mine-space centre / frame (tests, diagnostics) */
  centerMine: Vec3
  forwardMine: Vec3
  upMine: Vec3
  lateralMine: Vec3
}

/**
 * Pose of a barrier whose local x spans the LATERAL extent, y the height
 * and z the (thin) depth along `forward`; `centerMine` is the cuboid centre.
 * Null for a degenerate or vertical forward (no gravity frame).
 */
export function barrierPose(centerMine: Vec3, forwardMine: Vec3): BarrierPose | null {
  const forward = norm3(forwardMine)
  if (!forward) return null
  const up = gravityUp(forward)
  if (!up) return null
  // lateral = up × forward → (lateral, up, forward) is right-handed (det +1)
  const lateral = cross3(up, forward)
  const lT = new Vector3(...mineToThree(...lateral))
  const uT = new Vector3(...mineToThree(...up))
  const fT = new Vector3(...mineToThree(...forward))
  const q = new Quaternion().setFromRotationMatrix(new Matrix4().makeBasis(lT, uT, fT))
  if (![q.x, q.y, q.z, q.w].every((v) => Number.isFinite(v))) return null
  return {
    positionThree: mineToThree(...centerMine),
    quaternion: [q.x, q.y, q.z, q.w],
    centerMine,
    forwardMine: forward,
    upMine: up,
    lateralMine: lateral,
  }
}
