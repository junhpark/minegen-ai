import { useMemo } from 'react'
import * as THREE from 'three'
import { buildSliceQuad } from '@/geometry/sliceGeometry'
import { sliceTextureData } from '@/geometry/sliceTexture'
import type { SlicePayload } from '@/types/scene'

/**
 * One axis-aligned slice of a spatial field, drawn as a textured quad.
 * Texture is rows × cols (height × width); uv (0,0) at (row0, col0).
 * Assembly only: values, extents AND the display mask come from the backend
 * slice payload — masked cells are transparent (Phase 18).
 */
export function RockQualitySliceLayer({ slice }: { slice: SlicePayload }) {
  const { texture, geometry } = useMemo(() => {
    const { rows, cols } = slice
    const data = sliceTextureData(slice)
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
