/**
 * Heightmap → flat buffers in Three.js coordinates. Pure assembly
 * (CLAUDE.md rule 32): positions are the backend grid, converted once.
 */
import { mineToThree } from './coordinateTransform'
import type { TerrainPayload } from '@/types/scene'
import { normalize, terrainRamp } from '@/utils/colormap'

export interface TerrainBuffers {
  positions: Float32Array
  colors: Float32Array
  indices: Uint32Array
}

export function buildTerrainBuffers(terrain: TerrainPayload): TerrainBuffers {
  const { nx, ny, x0, y0, spacing, z, zMin, zMax } = terrain
  if (z.length !== nx * ny) throw new Error(`terrain z length ${z.length} != ${nx}×${ny}`)
  const positions = new Float32Array(nx * ny * 3)
  const colors = new Float32Array(nx * ny * 3)
  for (let i = 0; i < nx; i++) {
    for (let j = 0; j < ny; j++) {
      const k = i * ny + j
      const zz = z[k] as number
      const [tx, ty, tz] = mineToThree(x0 + i * spacing, y0 + j * spacing, zz)
      positions[k * 3] = tx
      positions[k * 3 + 1] = ty
      positions[k * 3 + 2] = tz
      const [r, g, b] = terrainRamp(normalize(zz, zMin, zMax))
      colors[k * 3] = r
      colors[k * 3 + 1] = g
      colors[k * 3 + 2] = b
    }
  }
  const indices = new Uint32Array((nx - 1) * (ny - 1) * 6)
  let t = 0
  for (let i = 0; i < nx - 1; i++) {
    for (let j = 0; j < ny - 1; j++) {
      const a = i * ny + j
      const b = (i + 1) * ny + j
      const c = (i + 1) * ny + j + 1
      const d = i * ny + j + 1
      // CCW seen from +Z (mine) = +Y (three); rotation preserves orientation
      indices[t++] = a
      indices[t++] = b
      indices[t++] = c
      indices[t++] = a
      indices[t++] = c
      indices[t++] = d
    }
  }
  return { positions, colors, indices }
}

/** Normal of triangle (i0,i1,i2) from a flat position buffer (Three coords). */
export function triangleNormal(
  p: Float32Array,
  i0: number,
  i1: number,
  i2: number,
): [number, number, number] {
  const ax = (p[i1 * 3] as number) - (p[i0 * 3] as number)
  const ay = (p[i1 * 3 + 1] as number) - (p[i0 * 3 + 1] as number)
  const az = (p[i1 * 3 + 2] as number) - (p[i0 * 3 + 2] as number)
  const bx = (p[i2 * 3] as number) - (p[i0 * 3] as number)
  const by = (p[i2 * 3 + 1] as number) - (p[i0 * 3 + 1] as number)
  const bz = (p[i2 * 3 + 2] as number) - (p[i0 * 3 + 2] as number)
  return [ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx]
}
