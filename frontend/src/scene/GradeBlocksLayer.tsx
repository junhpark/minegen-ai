import { useLayoutEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'
import { mineToThree } from '@/geometry/coordinateTransform'
import type { OreBlocksPayload } from '@/types/scene'
import { gradeRamp, normalize } from '@/utils/colormap'

/** Ore-flagged blocks as one InstancedMesh, colored by grade. */
export function GradeBlocksLayer({ blocks }: { blocks: OreBlocksPayload }) {
  const ref = useRef<THREE.InstancedMesh>(null)
  const [dx, dy, dz] = blocks.spacing
  // block box in three space: mine (dx, dy, dz) → three (dx, dz, dy)
  const geometry = useMemo(
    () => new THREE.BoxGeometry(dx * 0.92, dz * 0.92, dy * 0.92),
    [dx, dy, dz],
  )

  useLayoutEffect(() => {
    const mesh = ref.current
    if (!mesh) return
    const m = new THREE.Matrix4()
    const c = new THREE.Color()
    for (let i = 0; i < blocks.count; i++) {
      const x = blocks.centers[i * 3] ?? 0
      const y = blocks.centers[i * 3 + 1] ?? 0
      const z = blocks.centers[i * 3 + 2] ?? 0
      m.setPosition(...mineToThree(x, y, z))
      mesh.setMatrixAt(i, m)
      const [r, g, b] = gradeRamp(normalize(blocks.grade[i] ?? 0, blocks.gradeMin, blocks.gradeMax))
      mesh.setColorAt(i, c.setRGB(r, g, b))
    }
    mesh.instanceMatrix.needsUpdate = true
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
  }, [blocks])

  if (blocks.count === 0) return null
  return (
    <instancedMesh
      ref={ref}
      args={[geometry, undefined, blocks.count]}
      userData={{ kind: 'gradeBlocks' }}
    >
      <meshStandardMaterial roughness={0.7} metalness={0.05} />
    </instancedMesh>
  )
}
