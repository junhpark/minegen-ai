/**
 * Phase 21B/C review item 5 — production render batching is a pure
 * presentation grouping over persisted solids: a bounded number of merged
 * geometries whose triangles are the persisted triangles, concatenated.
 */
import { describe, expect, it } from 'vitest'
import type { ProductionSolid, ProductionUnitState } from './production'
import { staticBatches, timelineBatches } from './productionBatches'
import { mergeSolids, prepareSolid, solidGeometry } from './solidGeometry'
import type { SolidGeometry } from '@/types/scene'

/** an axis-aligned box prism `[x0, x0+1] × [0, 1] × [0, 1]` in mine space */
function box(x0: number): SolidGeometry {
  const vertices: number[] = []
  for (const [dx, dy, dz] of [
    [0, 0, 0],
    [1, 0, 0],
    [1, 1, 0],
    [0, 1, 0],
    [0, 0, 1],
    [1, 0, 1],
    [1, 1, 1],
    [0, 1, 1],
  ]) {
    vertices.push(x0 + (dx ?? 0), dy ?? 0, dz ?? 0)
  }
  const triangleIndices = [
    0, 2, 1, 0, 3, 2, 4, 5, 6, 4, 6, 7, 0, 1, 5, 0, 5, 4, 1, 2, 6, 1, 6, 5, 2, 3, 7, 2, 7, 6, 3, 0,
    4, 3, 4, 7,
  ]
  return { vertices, triangleIndices }
}

function solid(
  id: string,
  kind: ProductionSolid['kind'],
  over: Partial<ProductionSolid> = {},
): ProductionSolid {
  return { id, kind, geometry: box(0), valid: true, scheduled: kind !== 'PILLAR', ...over }
}

describe('mergeSolids', () => {
  it('concatenates persisted triangles verbatim with offset indices', () => {
    const a = box(0)
    const b = box(10)
    const merged = mergeSolids([prepareSolid(a), prepareSolid(b)])
    const pos = merged.getAttribute('position')
    expect(pos.count).toBe(16)
    const idx = merged.getIndex()
    expect(idx?.count).toBe(72)
    // the first solid's positions are exactly the single-solid geometry's
    const single = solidGeometry(a).getAttribute('position')
    for (let i = 0; i < single.array.length; i += 1) {
      expect(pos.array[i]).toBe(single.array[i])
    }
    // the second solid's indices are offset by the first solid's 8 vertices
    for (let k = 0; k < 36; k += 1) {
      expect(idx?.array[36 + k]).toBe((b.triangleIndices[k] ?? 0) + 8)
    }
    // normals exist for every vertex and the merged buffer is finite
    expect(merged.getAttribute('normal').count).toBe(16)
    expect(Array.from(pos.array).every((v) => Number.isFinite(v))).toBe(true)
  })

  it('switches to 32-bit indices past 65,535 vertices', () => {
    const many = Array.from({ length: 8200 }, (_, i) => prepareSolid(box(i)))
    const merged = mergeSolids(many)
    expect(merged.getAttribute('position').count).toBe(65600)
    expect(merged.getIndex()?.array).toBeInstanceOf(Uint32Array)
    const idx = merged.getIndex()
    expect(idx?.array[idx.array.length - 1]).toBeLessThan(65600)
  })
})

describe('staticBatches', () => {
  it('groups thousands of solids into at most two batches per kind', () => {
    const solids: ProductionSolid[] = []
    for (let i = 0; i < 7000; i += 1) solids.push(solid(`BENCH:${i}`, 'BENCH'))
    for (let i = 0; i < 300; i += 1) solids.push(solid(`PILLAR:${i}`, 'PILLAR'))
    solids.push(solid('BENCH:bad', 'BENCH', { valid: false }))
    const batches = staticBatches(solids)
    expect(batches.map((b) => b.key)).toEqual(['BENCH:valid', 'PILLAR:valid', 'BENCH:invalid'])
    expect(batches.reduce((n, b) => n + b.solids.length, 0)).toBe(7301)
    expect(batches[0]?.solids.length).toBe(7000)
  })
})

describe('timelineBatches', () => {
  const units = new Map<string, ProductionUnitState>([
    ['U1', { unitId: 'U1', initialState: 'PLANNED', transitions: [{ day: 10, state: 'ACTIVE' }] }],
    ['U2', { unitId: 'U2', initialState: 'PLANNED', transitions: [{ day: 20, state: 'ACTIVE' }] }],
  ])
  const solids = [solid('U1', 'BENCH'), solid('U2', 'BENCH'), solid('P1', 'PILLAR')]

  it('one batch per visual state at the day, pillars retained, exact boundary semantics', () => {
    const d5 = timelineBatches(solids, units, 5)
    expect(d5.batches.map((b) => [b.state, b.solids.length])).toEqual([
      ['PLANNED', 2],
      ['RETAINED', 1],
    ])
    const d10 = timelineBatches(solids, units, 10) // transition.day <= day → ACTIVE
    expect(d10.batches.map((b) => [b.state, b.solids.length])).toEqual([
      ['ACTIVE', 1],
      ['PLANNED', 1],
      ['RETAINED', 1],
    ])
    expect(d10.unmapped).toEqual([])
  })

  it('drops a scheduled solid without a state machine instead of guessing', () => {
    const out = timelineBatches([...solids, solid('U9', 'CUT')], units, 0)
    expect(out.unmapped).toEqual(['U9'])
    expect(out.batches.reduce((n, b) => n + b.solids.length, 0)).toBe(3)
  })
})
