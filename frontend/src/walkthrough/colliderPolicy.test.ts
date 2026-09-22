import { describe, expect, it } from 'vitest'
import {
  resolveColliderPolicy,
  resolveDevelopmentPhysics,
  resolveWalkthroughComposition,
} from './colliderPolicy'
import { walkthroughAuthorityLayers } from './readiness'
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

describe('development physics per walkthrough context (Phase 20D.2, rule 187)', () => {
  const ok = { status: 'SUCCESS', meshUrl: '/api/v1/scenarios/x/design/development-mesh/mesh.glb' }

  it('STATIC_FINAL mounts the advertised SUCCESS development mesh (Case B)', () => {
    expect(resolveDevelopmentPhysics('STATIC_FINAL', ok)).toEqual({
      mount: true,
      meshUrl: ok.meshUrl,
    })
  })

  it('STATIC_FINAL without a development mesh keeps the ramp-only walkthrough (Case A)', () => {
    expect(resolveDevelopmentPhysics('STATIC_FINAL', null)).toEqual({ mount: false, meshUrl: null })
    expect(resolveDevelopmentPhysics('STATIC_FINAL', undefined)).toEqual({
      mount: false,
      meshUrl: null,
    })
    expect(resolveDevelopmentPhysics('STATIC_FINAL', { status: 'FAILED', meshUrl: null })).toEqual({
      mount: false,
      meshUrl: null,
    })
    expect(resolveDevelopmentPhysics('STATIC_FINAL', { status: 'SUCCESS', meshUrl: null })).toEqual(
      {
        mount: false,
        meshUrl: null,
      },
    )
  })

  it('TIMELINE_SNAPSHOT never mounts the final development mesh, even when advertised', () => {
    expect(resolveDevelopmentPhysics('TIMELINE_SNAPSHOT', ok)).toEqual({
      mount: false,
      meshUrl: null,
    })
  })
})

describe('STATIC_FINAL physics-world composition (Phase 20D.2, T4 / M6)', () => {
  const ok = { status: 'SUCCESS', meshUrl: '/api/v1/scenarios/x/design/development-mesh/mesh.glb' }

  it('Case B: advertised + valid runtime geometry → tunnel AND development colliders', () => {
    expect(resolveWalkthroughComposition('STATIC_FINAL', ok, 'VALID')).toEqual({
      tunnelCollider: true,
      developmentCollider: true,
      failClosed: false,
    })
  })

  it('Case A: no development artifact → tunnel colliders only, never fail-closed', () => {
    for (const dev of [null, undefined, { status: 'FAILED', meshUrl: null }]) {
      for (const runtime of ['NOT_MOUNTED', 'VALID', 'MALFORMED'] as const) {
        expect(resolveWalkthroughComposition('STATIC_FINAL', dev, runtime)).toEqual({
          tunnelCollider: true,
          developmentCollider: false,
          failClosed: false,
        })
      }
    }
  })

  it('Case C (M6): advertised but malformed → fail closed, NOT a silent ramp-only walkthrough', () => {
    const c = resolveWalkthroughComposition('STATIC_FINAL', ok, 'MALFORMED')
    expect(c.failClosed).toBe(true)
    expect(c.developmentCollider).toBe(false)
    // an advertised mesh that was simply never mounted is the same defect
    expect(resolveWalkthroughComposition('STATIC_FINAL', ok, 'NOT_MOUNTED').failClosed).toBe(true)
  })

  it('TIMELINE_SNAPSHOT never composes development colliders', () => {
    expect(resolveWalkthroughComposition('TIMELINE_SNAPSHOT', ok, 'VALID')).toEqual({
      tunnelCollider: true,
      developmentCollider: false,
      failClosed: false,
    })
  })

  it('T6 invariant: development collider mounted ⇔ development mesh visible (every context / artifact state)', () => {
    for (const context of ['STATIC_FINAL', 'TIMELINE_SNAPSHOT'] as const) {
      for (const dev of [
        null,
        { status: 'FAILED', meshUrl: null },
        { status: 'SUCCESS', meshUrl: null },
        ok,
      ]) {
        const mount = resolveDevelopmentPhysics(context, dev).mount
        const visible = walkthroughAuthorityLayers(context, mount).has('developmentMesh')
        expect(visible).toBe(mount)
        // and the ramp tunnel is always both collidable and visible
        expect(walkthroughAuthorityLayers(context, mount).has('tunnelMesh')).toBe(true)
      }
    }
  })
})
