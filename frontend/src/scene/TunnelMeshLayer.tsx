import { useGLTF } from '@react-three/drei'
import { useMemo } from 'react'
import { Mesh } from 'three'
import { applyRockTexture, CAP_MATERIAL, TUNNEL_MATERIAL } from '@/walkthrough/tunnelMaterials'
import { readTunnelPrimitiveMetadata } from '@/walkthrough/tunnelRuntimeGeometry'
import { useRockTexture } from '@/walkthrough/useRockTexture'

/**
 * Phase 06 excavation mesh. The GLB is in mine coordinates (ENU, Z-up); the
 * group rotation −90° about X is exactly the mineToThree pure rotation, so
 * backend positions/normals/winding are used untouched (rule 17/32 — the
 * frontend only presents).
 */
export function TunnelMeshLayer({ url }: { url: string }) {
  const gltf = useGLTF(url)
  const rock = useRockTexture()
  useMemo(() => applyRockTexture(rock), [rock])
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
