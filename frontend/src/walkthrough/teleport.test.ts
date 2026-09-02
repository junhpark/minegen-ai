import { describe, expect, it } from 'vitest'
import type { WorldScene } from '@/types/scene'
import { buildMinimapModel } from './minimap'
import { resolveTeleportTargets } from './teleport'

// straight north decline: SEG:A 0..50 m, SEG:B 50..90 m (chainage = y here)
function smoothedScene(activeIds: string[] | null) {
  const seg = (levelId: string, pts: number[]) => ({
    levelId,
    effectiveCenterline: { points: pts, pointCount: pts.length / 3 },
  })
  const scene = {
    smoothedDecline: {
      segments: [seg('SEG:A', [0, 0, 0, 0, 50, -6]), seg('SEG:B', [0, 50, -6, 0, 90, -11])],
    },
    network: {
      status: 'SUCCESS',
      nodes: [
        { id: 'N:PORTAL', type: 'PORTAL', position: [0, 0, 0], levelId: null },
        { id: 'N:L1', type: 'LEVEL_ENTRY', position: [0.5, 50, -6], levelId: 'L1' },
        { id: 'N:L2', type: 'LEVEL_ENTRY', position: [-0.4, 88, -10.7], levelId: 'L2' },
        // a junction node must never become a teleport target
        { id: 'N:J', type: 'JUNCTION', position: [0, 30, -3.6], levelId: null },
      ],
    },
  } as unknown as WorldScene
  const model = buildMinimapModel(scene.smoothedDecline, activeIds)
  return { scene, chainagePoints: model.chainagePoints }
}

describe('level teleport targets (hotfix 2, item 9)', () => {
  it('offers Portal + on-decline LEVEL_ENTRY stations sorted by chainage', () => {
    const { scene, chainagePoints } = smoothedScene(null)
    const t = resolveTeleportTargets(scene, chainagePoints)
    expect(t.map((x) => x.id)).toEqual(['PORTAL', 'N:L1', 'N:L2'])
    expect(t[0]!.chainageM).toBe(0)
    expect(t[1]!.chainageM).toBeGreaterThan(45)
    expect(t[1]!.chainageM).toBeLessThan(55)
    expect(t[1]!.label).toBe('Level L1')
  })

  it('temporal ACTIVE prefix: beyond-frontier level entries are NOT offered', () => {
    // only SEG:A active -> chainage points stop at y=50; the L2 entry at
    // y=88 is ~38 m from the emitted centerline end and fails the
    // on-decline tolerance — the future decline can never be a target
    const { scene, chainagePoints } = smoothedScene(['SEG:A'])
    const t = resolveTeleportTargets(scene, chainagePoints)
    expect(t.map((x) => x.id)).toEqual(['PORTAL', 'N:L1'])
  })

  it('fails closed without a network or centerline', () => {
    const { scene } = smoothedScene(null)
    expect(resolveTeleportTargets(scene, [])).toEqual([])
    expect(resolveTeleportTargets(null, [0, 0, 0, 1, 1, 1])).toEqual([])
  })
})
