/**
 * Temporal frontier barrier pose (rules 115): ONE ephemeral runtime
 * traversal barrier closing a partial ACTIVE decline prefix. This is
 * access-control geometry ("unexcavated region — traversal stops here"),
 * NOT tunnel engineering geometry: rule 100 is unamended, the tunnel shell
 * remains exclusively Phase 06 GLB, and nothing here is persisted.
 *
 * Pose comes ONLY from the authoritative last-active Phase 05 effective
 * segment boundary: position = final effective centerline point (the FLOOR
 * centerline), orientation = the persisted boundaryTangents.end. A
 * gravity-aligned mine frame (forward, up = gravity component ⊥ forward,
 * right = forward × up... right-handed) is converted through the canonical
 * mine→Three rotation. The rectangular gate covers the Scenario-authored
 * ramp cross-section with a small conservative margin — it is intentionally
 * NOT the D-profile and must never be reported as excavation geometry.
 */
import { Matrix4, Quaternion, Vector3 } from 'three'
import { mineToThree } from '@/geometry/coordinateTransform'
import type { SmoothedSegmentPayload } from '@/types/scene'

export const FRONTIER_MARGIN_M = 0.25
export const FRONTIER_HALF_DEPTH_M = 0.125

export function frontierColliderId(lastActiveSegmentId: string): string {
  return `WALK:TEMPORAL:FRONTIER:${lastActiveSegmentId}`
}

export interface FrontierPose {
  colliderId: string
  /** gate CENTER, Three coordinates (floor point + up·height/2) */
  positionThree: [number, number, number]
  /** orientation quaternion [x,y,z,w], Three coordinates */
  quaternion: [number, number, number, number]
  /** [width/2+margin, height/2+margin, depth/2] for a cuboid */
  halfExtents: [number, number, number]
  /** authoritative mine-space fields, pinned by tests */
  floorPositionMine: [number, number, number]
  forwardMine: [number, number, number]
  upMine: [number, number, number]
}

function norm(v: [number, number, number]): [number, number, number] | null {
  const l = Math.hypot(v[0], v[1], v[2])
  if (!(l > 1e-9)) return null
  return [v[0] / l, v[1] / l, v[2] / l]
}

export function resolveFrontierPose(
  segment: SmoothedSegmentPayload,
  lastActiveSegmentId: string,
  ramp: { tunnelWidth: number; tunnelHeight: number },
): FrontierPose | null {
  const pts = segment.effectiveCenterline?.points
  if (!Array.isArray(pts) || pts.length < 3 || pts.length % 3 !== 0) return null
  const n = pts.length
  const floor: [number, number, number] = [pts[n - 3]!, pts[n - 2]!, pts[n - 1]!]
  if (!floor.every((v) => Number.isFinite(v))) return null
  const forward = norm(segment.boundaryTangents.end)
  if (!forward) return null
  // gravity-aligned up: Z minus its component along forward
  const dz = forward[2]
  const up = norm([-dz * forward[0], -dz * forward[1], 1 - dz * forward[2]])
  if (!up) return null // vertical tangent cannot host a gate
  const right: [number, number, number] = [
    forward[1] * up[2] - forward[2] * up[1],
    forward[2] * up[0] - forward[0] * up[2],
    forward[0] * up[1] - forward[1] * up[0],
  ]
  const halfH = ramp.tunnelHeight / 2
  const centerMine: [number, number, number] = [
    floor[0] + up[0] * halfH,
    floor[1] + up[1] * halfH,
    floor[2] + up[2] * halfH,
  ]
  const rT = new Vector3(...mineToThree(...right))
  const uT = new Vector3(...mineToThree(...up))
  const fT = new Vector3(...mineToThree(...forward))
  const q = new Quaternion().setFromRotationMatrix(new Matrix4().makeBasis(rT, uT, fT))
  if (![q.x, q.y, q.z, q.w].every((v) => Number.isFinite(v))) return null
  return {
    colliderId: frontierColliderId(lastActiveSegmentId),
    positionThree: mineToThree(...centerMine),
    quaternion: [q.x, q.y, q.z, q.w],
    halfExtents: [
      ramp.tunnelWidth / 2 + FRONTIER_MARGIN_M,
      ramp.tunnelHeight / 2 + FRONTIER_MARGIN_M,
      FRONTIER_HALF_DEPTH_M,
    ],
    floorPositionMine: floor,
    forwardMine: forward,
    upMine: up,
  }
}
