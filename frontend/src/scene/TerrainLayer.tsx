import { useMemo } from 'react'
import * as THREE from 'three'
import { buildTerrainBuffers } from '@/geometry/terrainGeometry'
import type { TerrainPayload } from '@/types/scene'

/** Heightmap → BufferGeometry (assembly only, see geometry/terrainGeometry). */
export function TerrainLayer({ terrain }: { terrain: TerrainPayload }) {
  const geometry = useMemo(() => {
    const b = buildTerrainBuffers(terrain)
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(b.positions, 3))
    g.setAttribute('color', new THREE.BufferAttribute(b.colors, 3))
    g.setIndex(new THREE.BufferAttribute(b.indices, 1))
    g.computeVertexNormals()
    return g
  }, [terrain])

  return (
    <mesh geometry={geometry}>
      <meshStandardMaterial
        vertexColors
        side={THREE.DoubleSide}
        roughness={0.95}
        metalness={0}
        transparent
        opacity={0.92}
      />
    </mesh>
  )
}
