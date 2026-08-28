import { useGLTF } from '@react-three/drei'
import { useMemo } from 'react'
import { DoubleSide, Mesh, MeshStandardMaterial } from 'three'

const TUNNEL_MATERIAL = new MeshStandardMaterial({
  color: '#8a7a63',
  roughness: 0.95,
  metalness: 0.0,
  side: DoubleSide, // visible from inside the void too (rule 66 note)
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
 * Phase 06 excavation mesh. The GLB is in mine coordinates (ENU, Z-up); the
 * group rotation −90° about X is exactly the mineToThree pure rotation, so
 * backend positions/normals/winding are used untouched (rule 17/32 — the
 * frontend only presents).
 */
export function TunnelMeshLayer({ url }: { url: string }) {
  const gltf = useGLTF(url)
  const object = useMemo(() => {
    const scene = gltf.scene
    scene.traverse((o) => {
      if (o instanceof Mesh) {
        const role = (o.userData as { role?: string }).role
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
