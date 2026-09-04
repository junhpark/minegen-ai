import { useGLTF } from '@react-three/drei'
import { useMemo } from 'react'
import { Mesh } from 'three'
import { applyRockTexture, CAP_MATERIAL, TUNNEL_MATERIAL } from '@/walkthrough/tunnelMaterials'
import { useRockTexture } from '@/walkthrough/useRockTexture'

/**
 * Phase 20B closeout v3 §4: LEVEL_ACCESS / DRIFT / CROSSCUT excavation meshes.
 * The GLB is backend-authored in mine coordinates (ENU, Z-up) and batched
 * per development kind (one tube primitive + one cap primitive per kind, the
 * `ranges` extras map index ranges back to development ids); this layer only
 * assigns the SHARED tunnel materials by primitive role — no geometry, no
 * per-development objects, no engineering (rules 17/32). The centerline
 * overlays (levels / crosscuts / levelAccesses layers) stay independent.
 */
export function DevelopmentMeshLayer({ url }: { url: string }) {
  const gltf = useGLTF(url)
  const rock = useRockTexture()
  useMemo(() => applyRockTexture(rock), [rock])
  const object = useMemo(() => {
    const scene = gltf.scene
    scene.traverse((o) => {
      if (o instanceof Mesh) {
        // primitive extras live on geometry.userData (same representation as
        // the ramp tunnel GLB); roles are DEVELOPMENT | <KIND>_CAP
        const extras = (o as Mesh).geometry.userData as { role?: unknown }
        const role = extras.role
        o.material =
          typeof role === 'string' && role.endsWith('_CAP') ? CAP_MATERIAL : TUNNEL_MATERIAL
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
