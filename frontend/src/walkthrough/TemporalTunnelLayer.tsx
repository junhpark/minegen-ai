import { useGLTF } from '@react-three/drei'
import { useMemo } from 'react'
import { DoubleSide, Mesh, MeshStandardMaterial } from 'three'
import { readTunnelPrimitiveMetadata } from './tunnelRuntimeGeometry'

const TUNNEL_MATERIAL = new MeshStandardMaterial({
  color: '#8a7a63',
  roughness: 0.95,
  metalness: 0.0,
  side: DoubleSide,
})
const CAP_MATERIAL = new MeshStandardMaterial({
  color: '#5c5348',
  roughness: 1.0,
  metalness: 0.0,
  side: DoubleSide,
  transparent: true,
  opacity: 0.55,
})

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
