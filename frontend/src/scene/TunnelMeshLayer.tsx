import { useGLTF } from '@react-three/drei'
import { useMemo } from 'react'
import { DoubleSide, Mesh, MeshStandardMaterial } from 'three'
import { readTunnelPrimitiveMetadata } from '@/walkthrough/tunnelRuntimeGeometry'
import { useRockTexture } from '@/walkthrough/useRockTexture'

const TUNNEL_MATERIAL = new MeshStandardMaterial({
  color: '#c9c2b6',
  roughness: 0.95,
  metalness: 0.0,
  side: DoubleSide, // visible from inside the void too (rule 66 note)
})
const CAP_MATERIAL = new MeshStandardMaterial({
  color: '#8f877a',
  roughness: 1.0,
  metalness: 0.0,
  side: DoubleSide,
  transparent: true,
  opacity: 0.55,
})

/**
 * Phase 06 excavation mesh. The GLB is in mine coordinates (ENU, Z-up); the
 * group rotation −90° about X is exactly the mineToThree pure rotation, so
 * backend positions/normals/winding are used untouched (rule 17/32 — the
 * frontend only presents).
 */
export function TunnelMeshLayer({ url }: { url: string }) {
  const gltf = useGLTF(url)
  const rock = useRockTexture()
  useMemo(() => {
    // §20–26: ONE deterministic rock/joint texture shared by the existing
    // two materials — no per-segment materials, no extra draw calls
    for (const m of [TUNNEL_MATERIAL, CAP_MATERIAL]) {
      if (m.map !== rock) {
        m.map = rock
        m.needsUpdate = true
      }
    }
  }, [rock])
  const object = useMemo(() => {
    const scene = gltf.scene
    scene.traverse((o) => {
      if (o instanceof Mesh) {
        // primitive extras live on geometry.userData (proven representation;
        // the old mesh.userData read never matched — hardened in Phase 15)
        const { role } = readTunnelPrimitiveMetadata(o as Mesh)
        o.material = role?.endsWith('_CAP') ? CAP_MATERIAL : TUNNEL_MATERIAL
      }
    })
    return scene
  }, [gltf])
  return (
    <group rotation={[-Math.PI / 2, 0, 0]}>
      <primitive object={object} />
    </group>
  )
}
