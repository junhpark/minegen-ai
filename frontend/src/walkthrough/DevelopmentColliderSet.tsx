import { useMemo } from 'react'
import { RigidBody, TrimeshCollider } from '@react-three/rapier'
import {
  buildDevelopmentColliderUnits,
  type DevelopmentRuntimeGeometry,
} from './developmentRuntimeGeometry'

/**
 * Fixed development collision for the STATIC_FINAL walkthrough (rule 187):
 * one trimesh collider per emitted batched tube primitive (LEVEL_ACCESS /
 * DRIFT / CROSSCUT) plus one per emitted cap primitive, derived only from
 * the Phase 20D.1 `development_mesh.glb` triangles in canonical Three
 * coordinates. Same fixed-body / default-material semantics as the ramp's
 * `TunnelColliderSet`; nothing is tuned to "help" junction traversal.
 */
export function DevelopmentColliderSet({ geometry }: { geometry: DevelopmentRuntimeGeometry }) {
  const units = useMemo(() => buildDevelopmentColliderUnits(geometry), [geometry])
  return (
    <>
      {units.map((u) => (
        <RigidBody key={u.id} type="fixed" colliders={false} name={u.id}>
          <TrimeshCollider args={[u.vertices, u.indices]} />
        </RigidBody>
      ))}
    </>
  )
}
