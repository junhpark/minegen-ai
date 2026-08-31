import { useMemo } from 'react'
import { CuboidCollider, RigidBody } from '@react-three/rapier'
import type { SmoothedSegmentPayload } from '@/types/scene'
import { resolveFrontierPose } from './frontier'

/**
 * Temporal frontier barrier (rule 115): one fixed runtime cuboid at the
 * authoritative last-ACTIVE segment boundary, plus a subtle dark face —
 * "Development frontier": unexcavated rock / temporal traversal boundary.
 * Not a bulkhead, not a door, not engineering geometry, never persisted.
 */
export function FrontierBarrier({
  segment,
  lastActiveSegmentId,
  ramp,
}: {
  segment: SmoothedSegmentPayload
  lastActiveSegmentId: string
  ramp: { tunnelWidth: number; tunnelHeight: number }
}) {
  const pose = useMemo(
    () => resolveFrontierPose(segment, lastActiveSegmentId, ramp),
    [segment, lastActiveSegmentId, ramp],
  )
  if (!pose) return null
  return (
    <RigidBody
      type="fixed"
      colliders={false}
      name={pose.colliderId}
      position={pose.positionThree}
      quaternion={pose.quaternion}
    >
      <CuboidCollider args={pose.halfExtents} />
      <mesh>
        <boxGeometry
          args={[pose.halfExtents[0] * 2, pose.halfExtents[1] * 2, pose.halfExtents[2] * 2]}
        />
        <meshStandardMaterial color="#2a251f" roughness={1} metalness={0} />
      </mesh>
    </RigidBody>
  )
}
