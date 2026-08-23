import { useMemo } from 'react'
import * as THREE from 'three'
import { buildSliceQuad } from '@/geometry/sliceGeometry'
import type { SlicePayload } from '@/types/scene'
import { normalize, rampForField } from '@/utils/colormap'

/**
 * One axis-aligned slice of a block field, drawn as a textured quad.
 * Texture is rows × cols (height × width); uv (0,0) at (row0, col0).
 * Assembly only: values and extents come from the backend slice payload.
 */
export function RockQualitySliceLayer({ slice }: { slice: SlicePayload }) {
  const { texture, geometry } = useMemo(() => {
    const { rows, cols, values, min, max, field } = slice
    const ramp = rampForField(field)
    const data = new Uint8Array(rows.n * cols.n * 4)
    for (let r = 0; r < rows.n; r++) {
      for (let c = 0; c < cols.n; c++) {
        const v = values[r * cols.n + c] ?? 0
        const [cr, cg, cb] = ramp(normalize(v, min, max))
        const k = (r * cols.n + c) * 4
        data[k] = Math.round(cr * 255)
        data[k + 1] = Math.round(cg * 255)
        data[k + 2] = Math.round(cb * 255)
        data[k + 3] = 235
      }
    }
    const tex = new THREE.DataTexture(data, cols.n, rows.n, THREE.RGBAFormat)
    tex.magFilter = THREE.NearestFilter
    tex.minFilter = THREE.NearestFilter
    tex.needsUpdate = true

    const quad = buildSliceQuad(slice)
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(quad.positions, 3))
    g.setAttribute('uv', new THREE.BufferAttribute(quad.uvs, 2))
    g.setIndex(quad.indices)
    g.computeVertexNormals()
    return { texture: tex, geometry: g }
  }, [slice])

  return (
    <mesh geometry={geometry} userData={{ kind: 'slice' }}>
      <meshBasicMaterial map={texture} side={THREE.DoubleSide} transparent depthWrite={false} />
    </mesh>
  )
}
