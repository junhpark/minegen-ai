/** Corner/uv layout for an axis-aligned block-field slice quad. */
import { mineToThree } from './coordinateTransform'
import type { SliceAxis, SlicePayload } from '@/types/scene'

export function sliceMineCoord(
  slice: SlicePayload,
  r: number,
  c: number,
): [number, number, number] {
  const p: Record<SliceAxis, number> = { x: 0, y: 0, z: 0 }
  p[slice.rows.axis] = r
  p[slice.cols.axis] = c
  p[slice.axis] = slice.coordinate
  return [p.x, p.y, p.z]
}

export interface SliceQuad {
  /** 4 corners × 3, Three coords, order (r0,c0) (r0,c1) (r1,c1) (r1,c0) */
  positions: Float32Array
  /** matching uv: (0,0) (1,0) (1,1) (0,1) — u along cols, v along rows */
  uvs: Float32Array
  indices: number[]
}

export function buildSliceQuad(slice: SlicePayload): SliceQuad {
  const { rows, cols } = slice
  const r0 = rows.origin
  const r1 = rows.origin + rows.n * rows.spacing
  const c0 = cols.origin
  const c1 = cols.origin + cols.n * cols.spacing
  const corners: [number, number][] = [
    [r0, c0],
    [r0, c1],
    [r1, c1],
    [r1, c0],
  ]
  const positions = new Float32Array(12)
  corners.forEach(([r, c], i) => {
    const [tx, ty, tz] = mineToThree(...sliceMineCoord(slice, r, c))
    positions[i * 3] = tx
    positions[i * 3 + 1] = ty
    positions[i * 3 + 2] = tz
  })
  return {
    positions,
    uvs: new Float32Array([0, 0, 1, 0, 1, 1, 0, 1]),
    indices: [0, 1, 2, 0, 2, 3],
  }
}
