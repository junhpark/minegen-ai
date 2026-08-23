import { describe, expect, it } from 'vitest'
import { buildTerrainBuffers, triangleNormal } from './terrainGeometry'
import type { TerrainPayload } from '@/types/scene'

const flat: TerrainPayload = {
  x0: -10,
  y0: -10,
  spacing: 10,
  nx: 3,
  ny: 3,
  z: Array.from({ length: 9 }, () => 100),
  zMin: 100,
  zMax: 100,
}

describe('terrain geometry', () => {
  it('produces two triangles per cell', () => {
    const b = buildTerrainBuffers(flat)
    expect(b.positions.length).toBe(9 * 3)
    expect(b.indices.length).toBe(4 * 6)
  })

  it('winds triangles so normals point up (+Y in Three) for a flat surface', () => {
    const b = buildTerrainBuffers(flat)
    for (let t = 0; t < b.indices.length; t += 3) {
      const n = triangleNormal(
        b.positions,
        b.indices[t] as number,
        b.indices[t + 1] as number,
        b.indices[t + 2] as number,
      )
      expect(n[1]).toBeGreaterThan(0)
      expect(n[0]).toBeCloseTo(0)
      expect(n[2]).toBeCloseTo(0)
    }
  })

  it('places mine elevation on the Three Y axis', () => {
    const b = buildTerrainBuffers(flat)
    expect(b.positions[1]).toBe(100)
    // mine (x0, y0) = (-10, -10) → three (-10, z, +10)
    expect(b.positions[0]).toBe(-10)
    expect(b.positions[2]).toBe(10)
  })

  it('rejects inconsistent buffers', () => {
    expect(() => buildTerrainBuffers({ ...flat, z: [1, 2, 3] })).toThrow()
  })
})
