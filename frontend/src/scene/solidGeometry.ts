import * as THREE from 'three'
import { mineToThree } from '@/geometry/coordinateTransform'
import type { SolidGeometry } from '@/types/scene'

/** The backend world-space prism, assembled verbatim (rule 80): vertices +
 * triangle indices only, no bounds arithmetic, no dip / thickness math. */
export function solidGeometry(g: SolidGeometry): THREE.BufferGeometry {
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.BufferAttribute(solidPositions(g), 3))
  geometry.setIndex(g.triangleIndices)
  geometry.computeVertexNormals()
  return geometry
}

/** The persisted vertices in Three space (the canonical mine → Three
 * transform applied per vertex; nothing else). */
export function solidPositions(g: SolidGeometry): Float32Array {
  const v = g.vertices
  const positions = new Float32Array(v.length)
  for (let i = 0; i + 2 < v.length; i += 3) {
    const p = mineToThree(v[i] ?? 0, v[i + 1] ?? 0, v[i + 2] ?? 0)
    positions[i] = p[0]
    positions[i + 1] = p[1]
    positions[i + 2] = p[2]
  }
  return positions
}

/** A solid prepared once for batching: transformed positions + persisted
 * triangle indices (never recomputed per frame). */
export interface PreparedSolid {
  positions: Float32Array
  indices: number[]
}

export function prepareSolid(g: SolidGeometry): PreparedSolid {
  return { positions: solidPositions(g), indices: g.triangleIndices }
}

/**
 * ONE BufferGeometry from many prepared solids: positions concatenated in
 * order, each solid's triangle indices offset by the vertices before it.
 * Pure concatenation of persisted triangles — no welding, no decimation, no
 * new vertices (rule 80: the frontend assembles, it never re-derives).
 * Normals are computed per vertex exactly as the per-solid geometry did
 * (solids share no vertices, so the result is identical).
 */
export function mergeSolids(solids: PreparedSolid[]): THREE.BufferGeometry {
  let vertexFloats = 0
  let indexCount = 0
  for (const s of solids) {
    vertexFloats += s.positions.length
    indexCount += s.indices.length
  }
  const positions = new Float32Array(vertexFloats)
  const vertexCount = vertexFloats / 3
  const indices = vertexCount > 65535 ? new Uint32Array(indexCount) : new Uint16Array(indexCount)
  let vOffset = 0
  let iOffset = 0
  for (const s of solids) {
    positions.set(s.positions, vOffset * 3)
    for (let k = 0; k < s.indices.length; k += 1) {
      indices[iOffset + k] = (s.indices[k] ?? 0) + vOffset
    }
    vOffset += s.positions.length / 3
    iOffset += s.indices.length
  }
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  geometry.setIndex(new THREE.BufferAttribute(indices, 1))
  geometry.computeVertexNormals()
  return geometry
}
