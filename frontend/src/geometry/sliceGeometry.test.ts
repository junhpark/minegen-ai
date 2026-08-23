import { describe, expect, it } from 'vitest'
import { buildSliceQuad, sliceMineCoord } from './sliceGeometry'
import type { SlicePayload } from '@/types/scene'

const base = {
  field: 'rockQuality' as const,
  index: 0,
  count: 1,
  values: [],
  min: 0,
  max: 1,
}

describe('slice geometry', () => {
  it('z slice: rows=x, cols=y, plane at z', () => {
    const s: SlicePayload = {
      ...base,
      axis: 'z',
      coordinate: -50,
      rows: { axis: 'x', origin: -100, spacing: 10, n: 20 },
      cols: { axis: 'y', origin: -200, spacing: 10, n: 40 },
    }
    expect(sliceMineCoord(s, -100, -200)).toEqual([-100, -200, -50])
    const q = buildSliceQuad(s)
    // corner (r1, c1) = mine (100, 200, -50) → three (100, -50, -200)
    expect(Array.from(q.positions.slice(6, 9))).toEqual([100, -50, -200])
    // every corner on the slice plane: three Y = mine z = -50
    for (let i = 0; i < 4; i++) expect(q.positions[i * 3 + 1]).toBe(-50)
  })

  it('x slice: rows=y, cols=z, plane at x', () => {
    const s: SlicePayload = {
      ...base,
      axis: 'x',
      coordinate: 35,
      rows: { axis: 'y', origin: 0, spacing: 5, n: 2 },
      cols: { axis: 'z', origin: -10, spacing: 5, n: 2 },
    }
    expect(sliceMineCoord(s, 0, -10)).toEqual([35, 0, -10])
    const q = buildSliceQuad(s)
    for (let i = 0; i < 4; i++) expect(q.positions[i * 3]).toBe(35) // three X = mine x
  })

  it('uv (0,0) maps to (row0, col0) so texture row-major data aligns', () => {
    const s: SlicePayload = {
      ...base,
      axis: 'y',
      coordinate: 0,
      rows: { axis: 'x', origin: 0, spacing: 1, n: 1 },
      cols: { axis: 'z', origin: 0, spacing: 1, n: 1 },
    }
    const q = buildSliceQuad(s)
    expect(Array.from(q.uvs.slice(0, 2))).toEqual([0, 0])
    expect(Array.from(q.positions.slice(0, 3))).toEqual([0, 0, -0]) // mine (0,0,0)
    expect(Array.from(q.uvs.slice(4, 6))).toEqual([1, 1])
    expect(Array.from(q.positions.slice(6, 9))).toEqual([1, 1, -0]) // mine (1,0,1)
  })
})
