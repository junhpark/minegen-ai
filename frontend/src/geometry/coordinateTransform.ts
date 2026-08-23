/**
 * The ONLY place where mine (ENU, Z-up) and Three.js (Y-up) coordinates meet.
 *
 *   mine   : X = East, Y = North, Z = Up
 *   three  : X = right, Y = up, Z = toward viewer
 *
 *   mineToThree(x, y, z)  = [x,  z, -y]
 *   threeToMine(x, y, z)  = [x, -z,  y]
 *
 * This is a pure rotation (det = +1): handedness is preserved, so mesh winding
 * and normals from the backend need no flipping.
 *
 * See docs/coordinate-system.md. Never send Three.js coordinates to the backend.
 */

import type { Point3D } from '@/types/api'

export type Vec3 = readonly [number, number, number]

export function mineToThree(x: number, y: number, z: number): [number, number, number] {
  return [x, z, -y]
}

export function threeToMine(x: number, y: number, z: number): [number, number, number] {
  return [x, -z, y]
}

export function pointToThree(p: Point3D): [number, number, number] {
  return mineToThree(p.x, p.y, p.z)
}

export function threeToPoint(v: Vec3): Point3D {
  const [x, y, z] = threeToMine(v[0], v[1], v[2])
  return { x, y, z }
}

/**
 * Convert a flat backend position buffer [x0,y0,z0, x1,y1,z1, ...] (mine coords)
 * into a Float32Array in Three.js coords, ready for a BufferAttribute.
 */
export function positionsToThree(positions: ArrayLike<number>): Float32Array {
  const n = positions.length
  if (n % 3 !== 0) throw new Error(`position buffer length ${n} is not a multiple of 3`)
  const out = new Float32Array(n)
  for (let i = 0; i < n; i += 3) {
    const x = positions[i] as number
    const y = positions[i + 1] as number
    const z = positions[i + 2] as number
    out[i] = x
    out[i + 1] = z
    out[i + 2] = -y
  }
  return out
}
