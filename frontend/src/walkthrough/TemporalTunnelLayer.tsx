import { useGLTF } from '@react-three/drei'
import { useMemo } from 'react'
import { Mesh } from 'three'
import { applyRockTexture, CAP_MATERIAL, TUNNEL_MATERIAL } from './tunnelMaterials'
import { useRockTexture } from './useRockTexture'
import { readTunnelPrimitiveMetadata } from './tunnelRuntimeGeometry'

/**
 * Temporal visual tunnel (rule 114, §13): the SAME cached Phase 06 GLB,
 * cloned ONCE (the shared useGLTF source object is never mutated), with
 * per-primitive visibility from the proven geometry.userData metadata:
 * SEGMENT visible iff active, PORTAL_CAP always, TERMINAL_CAP only when
 * the whole decline is complete. No future primitive is shown, no tunnel
 * vertex is invented, and the canonical −90° X group rotation is reused.
 */
export function TemporalTunnelLayer({
  url,
  activeSegmentIds,
  allSegmentsActive,
}: {
  url: string
  activeSegmentIds: readonly string[]
  allSegmentsActive: boolean
}) {
  const gltf = useGLTF(url)
  const rock = useRockTexture()
  // PR #13 blocker 1: the temporal layer applies the SAME deterministic
  // rock texture through the single shared material path — visibility
  // semantics below are untouched
  useMemo(() => applyRockTexture(rock), [rock])
  const object = useMemo(() => {
    const clone = gltf.scene.clone(true)
    const active = new Set(activeSegmentIds)
    clone.traverse((o) => {
      if (o instanceof Mesh) {
        const { role, segmentId } = readTunnelPrimitiveMetadata(o as Mesh)
        o.material = role?.endsWith('_CAP') ? CAP_MATERIAL : TUNNEL_MATERIAL
        if (role === 'SEGMENT') o.visible = segmentId !== null && active.has(segmentId)
        else if (role === 'PORTAL_CAP') o.visible = true
        else if (role === 'TERMINAL_CAP') o.visible = allSegmentsActive
        else o.visible = false
      }
    })
    return clone
  }, [gltf, activeSegmentIds, allSegmentsActive])
  return (
    <group rotation={[-Math.PI / 2, 0, 0]}>
      <primitive object={object} />
    </group>
  )
}
