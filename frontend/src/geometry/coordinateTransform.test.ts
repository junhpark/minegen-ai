import { describe, expect, it } from 'vitest'
import {
  mineToThree,
  pointToThree,
  positionsToThree,
  threeToMine,
  threeToPoint,
} from './coordinateTransform'

const cross = (a: readonly number[], b: readonly number[]) => [
  (a[1] ?? 0) * (b[2] ?? 0) - (a[2] ?? 0) * (b[1] ?? 0),
  (a[2] ?? 0) * (b[0] ?? 0) - (a[0] ?? 0) * (b[2] ?? 0),
  (a[0] ?? 0) * (b[1] ?? 0) - (a[1] ?? 0) * (b[0] ?? 0),
]

describe('mine <-> three coordinate transform', () => {
  it('maps East to +X, Up to +Y, North to -Z', () => {
    expect(mineToThree(1, 0, 0)).toEqual([1, 0, -0])
    expect(mineToThree(0, 0, 1)).toEqual([0, 1, -0])
    expect(mineToThree(0, 1, 0)).toEqual([0, 0, -1])
  })

  it('round-trips', () => {
    const samples: [number, number, number][] = [
      [0, 0, 0],
      [200, 100, 0],
      [-600, 600, -300],
      [12.5, -7.25, 281.3],
    ]
    for (const [x, y, z] of samples) {
      const [tx, ty, tz] = mineToThree(x, y, z)
      expect(threeToMine(tx, ty, tz)).toEqual([x, y, z])
    }
  })

  it('preserves handedness: image(East) x image(North) = image(Up)', () => {
    const e = mineToThree(1, 0, 0)
    const n = mineToThree(0, 1, 0)
    const u = mineToThree(0, 0, 1)
    const c = cross(e, n)
    expect(c[0]).toBeCloseTo(u[0])
    expect(c[1]).toBeCloseTo(u[1])
    expect(c[2]).toBeCloseTo(u[2])
  })

  it('converts Point3D objects', () => {
    expect(pointToThree({ x: 1, y: 2, z: 3 })).toEqual([1, 3, -2])
    expect(threeToPoint([1, 3, -2])).toEqual({ x: 1, y: 2, z: 3 })
  })

  it('converts flat position buffers', () => {
    const out = positionsToThree([1, 2, 3, 4, 5, 6])
    expect(Array.from(out)).toEqual([1, 3, -2, 4, 6, -5])
    expect(() => positionsToThree([1, 2])).toThrow()
  })
})
