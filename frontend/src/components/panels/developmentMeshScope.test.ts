/**
 * Closeout v4 §1.1: an access-only development mesh must say so.
 *
 * The two ways `sources.levels` becomes false — no levels artifact at all,
 * and a persisted levels artifact that contributed nothing — carry the SAME
 * headline: the sweep really does hold no drift / crosscut geometry either
 * way. Phase 20C.2A removed the old implicit-orebody "normal boundary"
 * (LEVEL_DEVELOPMENT_UNSUPPORTED_FOR_IMPLICIT_OREBODY): an implicit body
 * now develops real drifts / crosscuts along its curved section-trace
 * backbone, so EVERY failed levels artifact must read as a failure. There
 * is deliberately no stale state: the last test pins one of the two
 * mechanisms that make a stale report impossible.
 */
import { describe, expect, it } from 'vitest'
import type { DevelopmentMeshReport, LevelsPayload, WorldScene } from '@/types/scene'
import { afterLevelsRegen } from '@/scene/invalidation'
import { ACCESS_ONLY_HEADLINE, developmentMeshScope } from './developmentMeshScope'

function report(over: Partial<DevelopmentMeshReport> = {}): DevelopmentMeshReport {
  return {
    status: 'SUCCESS',
    failureReason: null,
    developmentCount: 14,
    triangleCount: 11704,
    sources: { levelAccesses: true, levels: true, rampSource: 'LAYOUT_V2' },
    artifactRevision: 'abc',
    meshUrl: '/mesh.glb',
    ...over,
  }
}

function levels(over: Partial<LevelsPayload> = {}): LevelsPayload {
  return {
    status: 'SUCCESS',
    failureReason: null,
    sourceRevision: 'rev',
    entrySource: 'LEVEL_ACCESS',
    levels: [],
    ...over,
  } as LevelsPayload
}

describe('developmentMeshScope', () => {
  it('says nothing when level development contributed geometry', () => {
    expect(developmentMeshScope(report(), levels())).toEqual({
      accessOnly: false,
      headline: null,
      detail: null,
    })
  })

  it('marks an access-only sweep when no levels artifact contributed', () => {
    const scope = developmentMeshScope(
      report({ sources: { levelAccesses: true, levels: false, rampSource: 'LAYOUT_V2' } }),
      null,
    )
    expect(scope.accessOnly).toBe(true)
    expect(scope.headline).toBe(ACCESS_ONLY_HEADLINE)
    expect(scope.detail).toContain('generate level development')
  })

  it('reads EVERY levels failure as a failure — no boundary is worded as normal', () => {
    for (const failureReason of [
      'SECTION_TRACE_ANCHORS_REQUIRED: a non-TABULAR orebody is developed along its ' +
        'curved section-trace anchors (Phase 20C.2A)',
      'SECTION_FOOTWALL_AMBIGUOUS: level L03: no footwall-side contour run',
      'SECTION_TRACE_OFFSET_INVALID: level L05: offset trace self-intersects',
      'LEVEL_ACCESSES_REQUIRED: a parametric main ramp ends its segments at ramp junctions',
      'no level entries to develop',
      'smoothed artifact has no effective segments',
      'orebody strike vector is not horizontal',
    ]) {
      const scope = developmentMeshScope(
        report({ sources: { levelAccesses: true, levels: false, rampSource: 'LAYOUT_V2' } }),
        levels({ status: 'FAILED', failureReason }),
      )
      // the sweep genuinely carries no drift / crosscut geometry either way
      expect(scope.accessOnly).toBe(true)
      expect(scope.headline).toBe(ACCESS_ONLY_HEADLINE)
      expect(scope.detail).toContain('level development failed')
      expect(scope.detail).not.toContain('normal state')
    }
  })

  it('qualifies nothing for a failed sweep or a report without sources', () => {
    expect(
      developmentMeshScope(report({ status: 'FAILED', failureReason: 'boom' }), null).accessOnly,
    ).toBe(false)
    const withoutSources: DevelopmentMeshReport = { ...report() }
    delete (withoutSources as { sources?: unknown }).sources
    expect(developmentMeshScope(withoutSources, null).accessOnly).toBe(false)
    expect(developmentMeshScope(null, levels()).accessOnly).toBe(false)
  })

  it('needs no stale state: regenerating levels drops the mesh from the scene', () => {
    const scene = { levels: null, developmentMesh: report() } as unknown as WorldScene
    expect(afterLevelsRegen(scene, levels()).developmentMesh).toBeNull()
  })
})
