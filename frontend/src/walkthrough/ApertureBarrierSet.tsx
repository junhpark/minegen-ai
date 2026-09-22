import { CuboidCollider, RigidBody } from '@react-three/rapier'
import type { ApertureBarrierPiece } from './apertureBarrier'

/**
 * Temporal aperture barriers (Phase 20D.2, rule 187): fixed runtime
 * cuboids along the ramp wall line over every declared RAMP_ACCESS
 * aperture of the TIMELINE_SNAPSHOT walkthrough, plus the same subtle dark
 * face the frontier barrier uses — "temporal traversal boundary: the
 * branch is not modelled at this day". Access-control geometry only:
 * never a bulkhead, never excavation geometry, never persisted.
 */
export function ApertureBarrierSet({ pieces }: { pieces: readonly ApertureBarrierPiece[] }) {
  return (
    <>
      {pieces.map((p) => (
        <RigidBody
          key={p.colliderId}
          type="fixed"
          colliders={false}
          name={p.colliderId}
          position={p.positionThree}
          quaternion={p.quaternion}
        >
          <CuboidCollider args={p.halfExtents} />
          <mesh>
            <boxGeometry
              args={[p.halfExtents[0] * 2, p.halfExtents[1] * 2, p.halfExtents[2] * 2]}
            />
            <meshStandardMaterial color="#2a251f" roughness={1} metalness={0} />
          </mesh>
        </RigidBody>
      ))}
    </>
  )
}
