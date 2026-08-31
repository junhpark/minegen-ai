import { Matrix4, Quaternion, Vector3 } from 'three'
import { describe, expect, it } from 'vitest'
import type { SmoothedSegmentPayload } from '@/types/scene'
import {
  FRONTIER_HALF_DEPTH_M,
  FRONTIER_MARGIN_M,
  frontierColliderId,
  resolveFrontierPose,
} from './frontier'

const RAMP = { tunnelWidth: 5, tunnelHeight: 5.5 }

function segment(points: number[], end: [number, number, number]): SmoothedSegmentPayload {
  return {
    levelId: 'SEG:B',
    effectiveCenterline: { points, pointCount: points.length / 3 },
    boundaryTangents: { start: [0, 1, 0], end },
  } as unknown as SmoothedSegmentPayload
}

describe('temporal frontier pose (rule 115, §30)', () => {
  // north-heading segment ending at (0, 40, -4), 10% down tangent
  const seg = segment([0, 0, 0, 0, 20, -2, 0, 40, -4], [0, 1, -0.1])

  it('sits at the exact active segment endpoint with the persisted tangent', () => {
    const p = resolveFrontierPose(seg, 'SEG:B', RAMP)!
    expect(p.floorPositionMine).toEqual([0, 40, -4]) // exact endpoint
    // forward = normalized persisted boundary tangent (never camera-derived)
    const l = Math.hypot(0, 1, -0.1)
    expect(p.forwardMine[1]).toBeCloseTo(1 / l, 12)
    expect(p.forwardMine[2]).toBeCloseTo(-0.1 / l, 12)
  })

  it('builds a gravity-aligned frame: up ⊥ forward, closest to mine +Z', () => {
    const p = resolveFrontierPose(seg, 'SEG:B', RAMP)!
    const dot =
      p.upMine[0] * p.forwardMine[0] +
      p.upMine[1] * p.forwardMine[1] +
      p.upMine[2] * p.forwardMine[2]
    expect(dot).toBeCloseTo(0, 12)
    expect(p.upMine[2]).toBeGreaterThan(0.9) // gravity-up dominant
    expect(Math.hypot(...p.upMine)).toBeCloseTo(1, 12)
  })

  it('centers the gate at floor + up·height/2 through the canonical rotation', () => {
    const p = resolveFrontierPose(seg, 'SEG:B', RAMP)!
    const h = RAMP.tunnelHeight / 2
    const centerMine = [0 + p.upMine[0] * h, 40 + p.upMine[1] * h, -4 + p.upMine[2] * h] as const
    // mineToThree: (x,y,z) -> (x,z,-y)
    expect(p.positionThree[0]).toBeCloseTo(centerMine[0], 12)
    expect(p.positionThree[1]).toBeCloseTo(centerMine[2], 12)
    expect(p.positionThree[2]).toBeCloseTo(-centerMine[1], 12)
  })

  it('uses scenario ramp dimensions plus the conservative margin', () => {
    const p = resolveFrontierPose(seg, 'SEG:B', RAMP)!
    expect(p.halfExtents).toEqual([
      RAMP.tunnelWidth / 2 + FRONTIER_MARGIN_M,
      RAMP.tunnelHeight / 2 + FRONTIER_MARGIN_M,
      FRONTIER_HALF_DEPTH_M,
    ])
  })

  it('emits a finite quaternion and the stable collider identity', () => {
    const p = resolveFrontierPose(seg, 'SEG:B', RAMP)!
    p.quaternion.forEach((v) => expect(Number.isFinite(v)).toBe(true))
    expect(p.colliderId).toBe('WALK:TEMPORAL:FRONTIER:SEG:B')
    expect(frontierColliderId('SEG:B')).toBe(p.colliderId)
  })

  it('is a proper RIGHT-HANDED rotation whose local Z is the gate normal (PR #12 blocker 1)', () => {
    // east-heading horizontal, north-heading horizontal, graded oblique
    const tangents: [number, number, number][] = [
      [1, 0, 0],
      [0, 1, 0],
      [0.6, 0.75, -0.12],
    ]
    for (const end of tangents) {
      const p = resolveFrontierPose(segment([0, 0, 0, 5, 5, -1], end), 'SEG:B', RAMP)!
      const q = new Quaternion(...p.quaternion)
      expect(Math.hypot(q.x, q.y, q.z, q.w)).toBeCloseTo(1, 9) // unit quaternion
      const m = new Matrix4().makeRotationFromQuaternion(q)
      expect(m.determinant()).toBeCloseTo(1, 9) // proper rotation, no reflection
      // rotated local +Z must align with the mine->Three forward (gate normal)
      const localZ = new Vector3(0, 0, 1).applyQuaternion(q)
      const f = p.forwardMine
      const fT = new Vector3(f[0], f[2], -f[1]) // mineToThree
      expect(Math.abs(localZ.dot(fT))).toBeCloseTo(1, 9)
      // and rotated local +Y must align with gravity-aligned up
      const localY = new Vector3(0, 1, 0).applyQuaternion(q)
      const u = p.upMine
      expect(Math.abs(localY.dot(new Vector3(u[0], u[2], -u[1])))).toBeCloseTo(1, 9)
    }
  })

  it('is deterministic and rejects degenerate input instead of guessing', () => {
    const a = resolveFrontierPose(seg, 'SEG:B', RAMP)
    const b = resolveFrontierPose(seg, 'SEG:B', RAMP)
    expect(a).toEqual(b)
    expect(resolveFrontierPose(segment([], [0, 1, 0]), 'X', RAMP)).toBeNull()
    // vertical tangent cannot host a gravity-aligned gate
    expect(resolveFrontierPose(segment([0, 0, 0, 0, 0, -9], [0, 0, -1]), 'X', RAMP)).toBeNull()
  })
})
