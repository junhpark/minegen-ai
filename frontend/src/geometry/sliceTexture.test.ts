/**
 * Phase 18 slice rendering contract: the backend display mask decides what
 * is drawn. Masked cells are fully transparent, so a grade slice can never
 * present the whole numerical lattice as ore (rule 129); unmasked cells are
 * colour-mapped over the backend display range.
 */
import { describe, expect, it } from 'vitest'
import type { SlicePayload } from '@/types/scene'
import { SLICE_ALPHA, sliceTextureData } from './sliceTexture'

function slice(values: number[], mask: number[], field: SlicePayload['field']): SlicePayload {
  return {
    field,
    axis: 'z',
    index: 0,
    count: 1,
    coordinate: 0,
    rows: { axis: 'x', origin: 0, spacing: 10, n: 2 },
    cols: { axis: 'y', origin: 0, spacing: 10, n: 2 },
    values,
    mask,
    maskSemantics: field === 'grade' ? 'OREBODY_INTERSECTION_BELOW_TERRAIN' : 'BELOW_TERRAIN',
    min: 0,
    max: 10,
  }
}

describe('sliceTextureData', () => {
  it('makes masked-out cells transparent and shown cells opaque', () => {
    const data = sliceTextureData(slice([1, 2, 3, 4], [1, 0, 1, 0], 'grade'))
    expect(data.length).toBe(16)
    expect(data[3]).toBe(SLICE_ALPHA)
    expect(data[7]).toBe(0)
    expect(data[11]).toBe(SLICE_ALPHA)
    expect(data[15]).toBe(0)
    // hidden texels carry no colour either
    expect([data[4], data[5], data[6]]).toEqual([0, 0, 0])
  })

  it('colour-maps shown cells over the backend display range', () => {
    const data = sliceTextureData(slice([0, 10, 5, 5], [1, 1, 1, 1], 'rockQuality'))
    const lo = [data[0], data[1], data[2]]
    const hi = [data[4], data[5], data[6]]
    expect(lo).not.toEqual(hi)
    expect(data.filter((_, i) => i % 4 === 3).every((a) => a === SLICE_ALPHA)).toBe(true)
  })

  it('treats a missing mask entry as shown (defensive, never hides data silently)', () => {
    const data = sliceTextureData(slice([1, 2, 3, 4], [], 'faultInfluence'))
    expect(data.filter((_, i) => i % 4 === 3).every((a) => a === SLICE_ALPHA)).toBe(true)
  })
})
