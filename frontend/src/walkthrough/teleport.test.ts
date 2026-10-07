import { describe, expect, it } from 'vitest'
import type { WorldScene } from '@/types/scene'
import { buildMinimapModel } from './minimap'
import { chainageExtent, resolveTeleportAuthority, resolveTeleportTargets } from './teleport'

// straight north ramp: segment A 0..50 m, segment B 50..90 m (chainage = y)
const SEG_A = [0, 0, 0, 0, 50, -6]
const SEG_B = [0, 50, -6, 0, 90, -11]
const len = (pts: number[]) => chainageExtent(pts)

/** layout-v2 shape: segments end at RAMP JUNCTIONS; level entries sit 30 m
 * off the ramp at the end of their access branches (≥ 6 × tunnel width) */
function parametricScene(over: Partial<WorldScene> = {}, activeIds: string[] | null = null) {
  const chA = len(SEG_A)
  const chB = chA + len(SEG_B)
  const scene = {
    smoothedDecline: {
      sourceKind: 'PARAMETRIC_V2',
      segments: [
        {
          segmentId: 'RAMP_JUNCTION:L01',
          levelId: 'L01',
          terminalKind: 'RAMP_JUNCTION',
          rampJunction: { levelId: 'L01', chainage: chA, position: [0, 50, -6] },
          effectiveSource: 'PARAMETRIC_V2',
          effectiveCenterline: { points: SEG_A, pointCount: 2 },
        },
        {
          segmentId: 'RAMP_JUNCTION:L02',
          levelId: 'L02',
          terminalKind: 'RAMP_JUNCTION',
          rampJunction: { levelId: 'L02', chainage: chB, position: [0, 90, -11] },
          effectiveSource: 'PARAMETRIC_V2',
          effectiveCenterline: { points: SEG_B, pointCount: 2 },
        },
      ],
    },
    levelAccesses: {
      status: 'SUCCESS',
      accesses: [
        { levelId: 'L01', status: 'OK', rampJunctionChainage: chA },
        { levelId: 'L02', status: 'OK', rampJunctionChainage: chB },
      ],
    },
    network: {
      status: 'SUCCESS',
      nodes: [
        { id: 'N:PORTAL', type: 'PORTAL', position: [0, 0, 0], levelId: null },
        {
          id: 'N:RJ:L01',
          type: 'RAMP_JUNCTION',
          position: [0, 50, -6],
          levelId: 'L01',
          chainage: chA,
        },
        {
          id: 'N:RJ:L02',
          type: 'RAMP_JUNCTION',
          position: [0, 90, -11],
          levelId: 'L02',
          chainage: chB,
        },
        // level entries 30 m off the ramp (the old 15 m proximity test dropped them)
        { id: 'N:LE:L01', type: 'LEVEL_ENTRY', position: [30, 55, -6], levelId: 'L01' },
        { id: 'N:LE:L02', type: 'LEVEL_ENTRY', position: [30, 95, -11], levelId: 'L02' },
        { id: 'N:J', type: 'JUNCTION', position: [0, 30, -3.6], levelId: null },
      ],
    },
    ...over,
  } as unknown as WorldScene
  const model = buildMinimapModel(scene.smoothedDecline, activeIds)
  return { scene, chainagePoints: model.chainagePoints, chA, chB }
}

/** legacy shape: a segment ends AT the level entry, on the ramp */
function legacyScene(activeIds: string[] | null = null) {
  const seg = (levelId: string, pts: number[]) => ({
    levelId,
    candidateId: `${levelId}-C01`,
    effectiveSource: 'SMOOTHED',
    effectiveCenterline: { points: pts, pointCount: pts.length / 3 },
  })
  const scene = {
    smoothedDecline: { segments: [seg('L01', SEG_A), seg('L02', SEG_B)] },
    network: {
      status: 'SUCCESS',
      nodes: [
        { id: 'N:PORTAL', type: 'PORTAL', position: [0, 0, 0], levelId: null },
        { id: 'N:L01', type: 'LEVEL_ENTRY', position: [0, 50, -6], levelId: 'L01' },
        { id: 'N:L02', type: 'LEVEL_ENTRY', position: [0, 90, -11], levelId: 'L02' },
      ],
    },
  } as unknown as WorldScene
  const model = buildMinimapModel(scene.smoothedDecline, activeIds)
  return { scene, chainagePoints: model.chainagePoints }
}

describe('ramp teleport targets (hardening H0 §3.2)', () => {
  it('layout v2: Portal + every RAMP_JUNCTION at its backend chainage; level entries 30 m off the ramp are never targets', () => {
    const { scene, chainagePoints, chA, chB } = parametricScene()
    const t = resolveTeleportTargets(scene, chainagePoints)
    expect(t.map((x) => x.id)).toEqual(['PORTAL', 'N:RJ:L01', 'N:RJ:L02'])
    expect(t.map((x) => x.chainageM)).toEqual([0, chA, chB])
    expect(t[1]!.label).toBe('Turnout L01')
    expect(resolveTeleportAuthority(scene).authority).toBe('NETWORK_RAMP_JUNCTION')
  })

  it('levels FAILED / no network: the same turnouts come from the level accesses', () => {
    const { scene, chainagePoints, chA, chB } = parametricScene({ network: null })
    const t = resolveTeleportTargets(scene, chainagePoints)
    expect(t.map((x) => x.id)).toEqual(['PORTAL', 'RAMP_JUNCTION:L01', 'RAMP_JUNCTION:L02'])
    expect(t.map((x) => x.chainageM)).toEqual([0, chA, chB])
    expect(resolveTeleportAuthority(scene).authority).toBe('LEVEL_ACCESS_JUNCTION')
    // a FAILED network is the same as none
    const failed = parametricScene({
      network: { status: 'FAILED', nodes: [] } as unknown as WorldScene['network'],
    })
    expect(resolveTeleportTargets(failed.scene, failed.chainagePoints).map((x) => x.id)).toEqual([
      'PORTAL',
      'RAMP_JUNCTION:L01',
      'RAMP_JUNCTION:L02',
    ])
  })

  it('no network and no level accesses: the Effective Ramp segment boundaries (rule 155) are the turnouts', () => {
    const { scene, chainagePoints, chA, chB } = parametricScene({
      network: null,
      levelAccesses: null,
    })
    const t = resolveTeleportTargets(scene, chainagePoints)
    expect(t.map((x) => x.id)).toEqual(['PORTAL', 'RAMP_JUNCTION:L01', 'RAMP_JUNCTION:L02'])
    expect(t.map((x) => x.chainageM)).toEqual([0, chA, chB])
    expect(resolveTeleportAuthority(scene).authority).toBe('RAMP_SEGMENT_BOUNDARY')
    // an access that is not OK carries no junction
    const partial = parametricScene({
      network: null,
      levelAccesses: {
        status: 'FAILED',
        accesses: [
          { levelId: 'L01', status: 'OK', rampJunctionChainage: chA },
          { levelId: 'L02', status: 'INFEASIBLE', rampJunctionChainage: null },
        ],
      } as unknown as WorldScene['levelAccesses'],
    })
    expect(resolveTeleportTargets(partial.scene, partial.chainagePoints).map((x) => x.id)).toEqual([
      'PORTAL',
      'RAMP_JUNCTION:L01',
    ])
  })

  it('legacy: a segment ends at its level entry on the ramp — the boundary chainage is the target', () => {
    const { scene, chainagePoints } = legacyScene()
    const t = resolveTeleportTargets(scene, chainagePoints)
    expect(t.map((x) => x.id)).toEqual(['PORTAL', 'LEVEL_ENTRY:L01', 'LEVEL_ENTRY:L02'])
    expect(t[1]!.chainageM).toBeCloseTo(len(SEG_A), 9)
    expect(t[2]!.chainageM).toBeCloseTo(len(SEG_A) + len(SEG_B), 9)
    expect(t[1]!.label).toBe('Level L01')
    expect(resolveTeleportAuthority(scene).authority).toBe('RAMP_SEGMENT_BOUNDARY')
  })

  it('temporal ACTIVE prefix: turnouts beyond the emitted centerline are NOT offered', () => {
    const { scene, chainagePoints } = parametricScene({}, ['RAMP_JUNCTION:L01'])
    const t = resolveTeleportTargets(scene, chainagePoints)
    expect(t.map((x) => x.id)).toEqual(['PORTAL', 'N:RJ:L01'])
    const legacy = legacyScene(['L01'])
    expect(resolveTeleportTargets(legacy.scene, legacy.chainagePoints).map((x) => x.id)).toEqual([
      'PORTAL',
      'LEVEL_ENTRY:L01',
    ])
  })

  it('fails closed without a ramp or an emitted centerline', () => {
    const { scene } = parametricScene()
    expect(resolveTeleportTargets(scene, [])).toEqual([])
    expect(resolveTeleportTargets(null, [0, 0, 0, 1, 1, 1])).toEqual([])
    expect(resolveTeleportAuthority(null).authority).toBe('NONE')
    expect(
      resolveTeleportTargets(
        { smoothedDecline: { segments: [] }, network: null } as unknown as WorldScene,
        [0, 0, 0, 1, 1, 1],
      ),
    ).toEqual([{ id: 'PORTAL', label: 'Portal', chainageM: 0 }])
  })

  it('never offers a target whose backend chainage is missing, negative or duplicated', () => {
    const chA = len(SEG_A)
    const { scene, chainagePoints } = parametricScene({
      network: {
        status: 'SUCCESS',
        nodes: [
          {
            id: 'N:RJ:L01',
            type: 'RAMP_JUNCTION',
            position: [0, 50, -6],
            levelId: 'L01',
            chainage: chA,
          },
          {
            id: 'N:RJ:DUP',
            type: 'RAMP_JUNCTION',
            position: [0, 50, -6],
            levelId: 'L01',
            chainage: chA,
          },
          {
            id: 'N:RJ:NONE',
            type: 'RAMP_JUNCTION',
            position: [0, 60, -7],
            levelId: 'L03',
            chainage: null,
          },
          {
            id: 'N:RJ:NEG',
            type: 'RAMP_JUNCTION',
            position: [0, 60, -7],
            levelId: 'L04',
            chainage: -1,
          },
        ],
      } as unknown as WorldScene['network'],
    })
    const t = resolveTeleportTargets(scene, chainagePoints)
    // distinct ids at the same chainage are both offered (deterministic by id); null / negative never
    expect(t.map((x) => x.id)).toEqual(['PORTAL', 'N:RJ:DUP', 'N:RJ:L01'])
  })
})
