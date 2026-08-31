import { describe, expect, it } from 'vitest'
import { resolveColliderPolicy } from './colliderPolicy'
import type { TemporalWalkthroughPlan } from './temporalPlan'

const ALL = ['SEG:A', 'SEG:B', 'SEG:C']

function plan(over: Partial<TemporalWalkthroughPlan>): TemporalWalkthroughPlan {
  return {
    status: 'VALID',
    reason: null,
    snapshotDay: 250,
    activeSegmentIds: ['SEG:A', 'SEG:B'],
    activeSegmentIndices: [0, 1],
    allSegmentsActive: false,
    lastActiveSegmentIndex: 1,
    frontier: { segmentId: 'SEG:B', segmentIndex: 1 },
    ...over,
  }
}

describe('collider policy per walkthrough context (§31)', () => {
  it('STATIC_FINAL: all segments + both caps + no frontier (Phase 13 exact)', () => {
    const p = resolveColliderPolicy('STATIC_FINAL', ALL, null)
    expect(p).toEqual({
      segmentIds: ALL,
      includePortalCap: true,
      includeTerminalCap: true,
      frontierSegmentId: null,
    })
  })

  it('TIMELINE partial: active prefix only, portal yes, terminal no, frontier yes', () => {
    const p = resolveColliderPolicy('TIMELINE_SNAPSHOT', ALL, plan({}))
    expect(p.segmentIds).toEqual(['SEG:A', 'SEG:B'])
    expect(p.includePortalCap).toBe(true)
    expect(p.includeTerminalCap).toBe(false)
    expect(p.frontierSegmentId).toBe('SEG:B')
  })

  it('TIMELINE complete: all segments, both caps, no frontier', () => {
    const p = resolveColliderPolicy(
      'TIMELINE_SNAPSHOT',
      ALL,
      plan({
        activeSegmentIds: ALL,
        activeSegmentIndices: [0, 1, 2],
        allSegmentsActive: true,
        lastActiveSegmentIndex: 2,
        frontier: null,
      }),
    )
    expect(p.segmentIds).toEqual(ALL)
    expect(p.includeTerminalCap).toBe(true)
    expect(p.frontierSegmentId).toBeNull()
  })

  it('TIMELINE invalid/missing plan fails closed: nothing walkable', () => {
    expect(resolveColliderPolicy('TIMELINE_SNAPSHOT', ALL, null).segmentIds).toEqual([])
    const p = resolveColliderPolicy('TIMELINE_SNAPSHOT', ALL, plan({ status: 'INVALID' }))
    expect(p.segmentIds).toEqual([])
    expect(p.frontierSegmentId).toBeNull()
  })
})
