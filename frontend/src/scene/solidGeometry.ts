import * as THREE from 'three'
import { mineToThree } from '@/geometry/coordinateTransform'
import type { SolidGeometry } from '@/types/scene'

/** The backend world-space prism, assembled verbatim (rule 80): vertices +
 * triangle indices only, no bounds arithmetic, no dip / thickness math. */
export function solidGeometry(g: SolidGeometry): THREE.BufferGeometry {
  const v = g.vertices
  const positions = new Float32Array(v.length)
  for (let i = 0; i + 2 < v.length; i += 3) {
    const p = mineToThree(v[i] ?? 0, v[i + 1] ?? 0, v[i + 2] ?? 0)
    positions[i] = p[0]
    positions[i + 1] = p[1]
    positions[i + 2] = p[2]
  }
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  geometry.setIndex(g.triangleIndices)
  geometry.computeVertexNormals()
  return geometry
}
