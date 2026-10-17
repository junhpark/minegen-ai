import { useMemo } from 'react'
import { RigidBody, TrimeshCollider } from '@react-three/rapier'
import {
  buildDevelopmentColliderUnits,
  type DevelopmentColliderSelection,
  type DevelopmentRuntimeGeometry,
} from './developmentRuntimeGeometry'

/**
 * Fixed development collision (rule 187): STATIC_FINAL mounts one trimesh
 * per emitted batched tube primitive (LEVEL_ACCESS / DRIFT / CROSSCUT) plus
 * one per emitted cap primitive; a TIMELINE_SNAPSHOT (PR-4 W1a) passes the
 * plan's `selection` and mounts one trimesh per ACTIVE piece (its validated
 * `ranges` window of the same buffers) plus the caps of the active kinds.
 * Derived only from the Phase 20D.1 `development_mesh.glb` triangles in
 * canonical Three coordinates; same fixed-body / default-material semantics
 * as the ramp's `TunnelColliderSet`; nothing is tuned to "help" traversal.
 */
export function DevelopmentColliderSet({
  geometry,
  selection = null,
}: {
  geometry: DevelopmentRuntimeGeometry
  selection?: DevelopmentColliderSelection | null
}) {
  const units = useMemo(
    () => buildDevelopmentColliderUnits(geometry, selection),
    [geometry, selection],
  )
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
