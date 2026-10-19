import { CuboidCollider, RigidBody } from '@react-three/rapier'
import type { TemporalPlug } from './temporalDevelopmentPlan'

/**
 * Temporal development plugs (PR-4 W1a, rule 115 analogue): fixed runtime
 * cuboids closing every opening of an ACTIVE excavation onto a development
 * that is not yet active at the snapshot day — the unexcavated face. The
 * same subtle dark face as the frontier barrier: access-control geometry,
 * never a bulkhead, never excavation geometry, never persisted.
 */
export function PlugBarrierSet({ plugs }: { plugs: readonly TemporalPlug[] }) {
  return (
    <>
      {plugs.map((p) => (
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
