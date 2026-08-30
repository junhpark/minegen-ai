import { useMemo } from 'react'
import { RigidBody, TrimeshCollider } from '@react-three/rapier'
import {
  buildColliderUnits,
  segmentColliderId,
  type TunnelRuntimeGeometry,
} from './tunnelRuntimeGeometry'

/**
 * Fixed tunnel collision (rules 100/104): one trimesh collider per decline
 * segment plus separately identifiable portal/terminal caps, derived only
 * from the Phase 06 GLB triangles in canonical Three coordinates.
 *
 * `activeSegmentIds` is the explicit Phase 15 hook: a future time-aware
 * walkthrough can toggle individual segment colliders by ID without
 * rebuilding the physics world. Phase 13 always passes ALL segments and
 * keeps both caps active (contained decline baseline).
 */
export function TunnelColliderSet({
  geometry,
  activeSegmentIds,
}: {
  geometry: TunnelRuntimeGeometry
  activeSegmentIds: readonly string[]
}) {
  const units = useMemo(() => buildColliderUnits(geometry), [geometry])
  const active = useMemo(() => {
    const wanted = new Set(activeSegmentIds.map(segmentColliderId))
    return units.filter((u) => u.segmentId === null || wanted.has(u.id))
  }, [units, activeSegmentIds])
  return (
    <>
      {active.map((u) => (
        <RigidBody key={u.id} type="fixed" colliders={false} name={u.id}>
          <TrimeshCollider args={[u.vertices, u.indices]} />
        </RigidBody>
      ))}
    </>
  )
}
