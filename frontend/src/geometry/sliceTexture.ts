/**
 * RGBA texel data for a spatial-field slice (assembly only, rule 17).
 * Values are colour-mapped over the backend display range; cells the
 * backend masked out (``mask[i] === 0`` — above terrain, or outside the
 * analytic orebody for the grade field) are fully transparent so the
 * numerical lattice is never shown as if every cell were ore (rule 129).
 */
import type { SlicePayload } from '@/types/scene'
import { normalize, rampForField } from '@/utils/colormap'

export const SLICE_ALPHA = 235

export function sliceTextureData(slice: SlicePayload): Uint8Array<ArrayBuffer> {
  const { rows, cols, values, mask, min, max, field } = slice
  const ramp = rampForField(field)
  const data = new Uint8Array(new ArrayBuffer(rows.n * cols.n * 4))
  for (let r = 0; r < rows.n; r++) {
    for (let c = 0; c < cols.n; c++) {
      const i = r * cols.n + c
      const k = i * 4
      const shown = (mask[i] ?? 1) !== 0
      if (!shown) continue // stays (0, 0, 0, 0): transparent
      const [cr, cg, cb] = ramp(normalize(values[i] ?? 0, min, max))
      data[k] = Math.round(cr * 255)
      data[k + 1] = Math.round(cg * 255)
      data[k + 2] = Math.round(cb * 255)
      data[k + 3] = SLICE_ALPHA
    }
  }
  return data
}
