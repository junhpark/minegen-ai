import { describe, expect, it } from 'vitest'
import type { SmoothedDeclinePayload, TimelinePayload } from '@/types/scene'
import type { TunnelRuntimeGeometry } from './tunnelRuntimeGeometry'
import { resolveActiveRampIndices, resolveTemporalWalkthroughPlan } from './temporalPlan'

/** 3-segment decline: ramps complete at days 100 / 200 / 300. */
function timeline(over: Partial<Record<number, unknown>> = {}): TimelinePayload {
  const dev = (i: number, end: number) => ({
    edgeId: `E:RAMP${i}`,
    edgeType: 'RAMP',
    geometryRef: { artifact: 'decline_smoothed.json', segmentIndex: i },
    taskId: `T${i}`,
    initialState: 'NOT_BUILT',
    transitions: [
      { day: end - 100, state: 'DEVELOPING' },
      { day: end, state: 'ACTIVE' },
    ],
    progressStartDay: end - 100,
    progressEndDay: end,
    pointChainageFractions: [],
    ...(over[i] as object | undefined),
  })
  return {
    status: 'SUCCESS',
    developments: [dev(0, 100), dev(1, 200), dev(2, 300)],
  } as unknown as TimelinePayload
}

function smoothed(): SmoothedDeclinePayload {
  return {
    status: 'SUCCESS',
    segments: ['SEG:A', 'SEG:B', 'SEG:C'].map((levelId) => ({
      levelId,
      effectiveCenterline: { points: [0, 0, 0, 10, 0, -1], pointCount: 2 },
      boundaryTangents: { start: [1, 0, -0.1], end: [1, 0, -0.1] },
    })),
  } as unknown as SmoothedDeclinePayload
}

function runtime(ids = ['SEG:A', 'SEG:B', 'SEG:C']): TunnelRuntimeGeometry {
  const prim = () => ({ positions: new Float32Array(9), indices: new Uint32Array(3) })
  return {
    segments: ids.map((segmentId) => ({ segmentId, ...prim() })),
    portalCap: prim(),
    terminalCap: prim(),
    primitiveCount: ids.length + 2,
  }
}

const plan = (day: number, tl = timeline(), sm = smoothed(), rt = runtime()) =>
  resolveTemporalWalkthroughPlan(tl, sm, rt, day)

describe('temporal RAMP resolver (rules 113/114/117, §29)', () => {
  it('A/B: before first completion — DEVELOPING is never walkable', () => {
    expect(plan(-5).activeSegmentIds).toEqual([]) // before first start
    const during = plan(50) // segment 0 DEVELOPING
    expect(during.status).toBe('VALID')
    expect(during.activeSegmentIds).toEqual([])
    expect(during.frontier).toBeNull()
  })

  it('C: exact first ACTIVE transition day opens segment 0 (stateAt boundary)', () => {
    expect(plan(99.999).activeSegmentIds).toEqual([])
    const p = plan(100)
    expect(p.activeSegmentIds).toEqual(['SEG:A'])
    expect(p.lastActiveSegmentIndex).toBe(0)
    expect(p.frontier).toEqual({ segmentId: 'SEG:A', segmentIndex: 0 })
  })

  it('D: middle snapshot yields the ACTIVE prefix with a frontier', () => {
    const p = plan(250)
    expect(p.status).toBe('VALID')
    expect(p.activeSegmentIndices).toEqual([0, 1])
    expect(p.activeSegmentIds).toEqual(['SEG:A', 'SEG:B'])
    expect(p.allSegmentsActive).toBe(false)
    expect(p.frontier!.segmentId).toBe('SEG:B')
  })

  it('E: all complete — every segment active, no frontier', () => {
    const p = plan(300)
    expect(p.activeSegmentIds).toEqual(['SEG:A', 'SEG:B', 'SEG:C'])
    expect(p.allSegmentsActive).toBe(true)
    expect(p.frontier).toBeNull()
  })

  it('F/G: duplicate or missing segmentIndex fails closed', () => {
    const dup = plan(
      250,
      timeline({ 2: { geometryRef: { artifact: 'decline_smoothed.json', segmentIndex: 1 } } }),
    )
    expect(dup.status).toBe('INVALID')
    expect(dup.reason).toContain('duplicate segmentIndex')
    expect(dup.activeSegmentIds).toEqual([])
  })

  it('H: RAMP owning a foreign artifact fails closed', () => {
    const p = plan(
      250,
      timeline({ 1: { geometryRef: { artifact: 'network.json', segmentIndex: 1 } } }),
    )
    expect(p.status).toBe('INVALID')
    expect(p.reason).toContain('network.json')
  })

  it('I: runtime segmentId != smoothed levelId fails closed', () => {
    const p = plan(250, timeline(), smoothed(), runtime(['SEG:A', 'SEG:X', 'SEG:C']))
    expect(p.status).toBe('INVALID')
    expect(p.reason).toContain('SEG:X')
  })

  it('J: a non-prefix ACTIVE set fails closed', () => {
    // segment 1 completes before segment 0 -> at day 150 active = [1] only
    const tl = timeline({
      0: {
        transitions: [
          { day: 200, state: 'DEVELOPING' },
          { day: 400, state: 'ACTIVE' },
        ],
      },
      1: {
        transitions: [
          { day: 50, state: 'DEVELOPING' },
          { day: 150, state: 'ACTIVE' },
        ],
      },
    })
    const p = plan(150, tl)
    expect(p.status).toBe('INVALID')
    expect(p.reason).toContain('not a portal-prefix')
  })

  it('K: non-finite snapshot day fails closed', () => {
    expect(plan(Number.NaN).status).toBe('INVALID')
    expect(plan(Number.POSITIVE_INFINITY).status).toBe('INVALID')
  })

  it('L: RAMP development count mismatch fails closed (no silent skip)', () => {
    const tl = timeline()
    ;(tl.developments as unknown[]).pop()
    const p = plan(250, tl)
    expect(p.status).toBe('INVALID')
    expect(p.reason).toContain('count')
  })

  it('shared index resolver reports identical mapping for readiness use', () => {
    const r = resolveActiveRampIndices(timeline(), smoothed(), 250)
    expect(r).toEqual({ indices: [0, 1], total: 3 })
  })
})
