/**
 * Closeout v4 §1.1: an access-only development mesh must say so.
 *
 * The two ways `sources.levels` becomes false — no levels artifact at all,
 * and a persisted levels artifact that contributed nothing — carry the SAME
 * headline: the sweep really does hold no drift / crosscut geometry either
 * way. Only the EXPLANATION differs, and only the implicit-orebody boundary
 * (closeout v5 §1) may be worded as a normal state; every other levels
 * failure must read as a failure. There is deliberately no stale state: the
 * last test pins one of the two mechanisms that make a stale report
 * impossible.
 */
import { describe, expect, it } from 'vitest'
import type { DevelopmentMeshReport, LevelsPayload, WorldScene } from '@/types/scene'
import { afterLevelsRegen } from '@/scene/invalidation'
import {
  ACCESS_ONLY_HEADLINE,
  IMPLICIT_OREBODY_BOUNDARY,
  developmentMeshScope,
} from './developmentMeshScope'

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

  it('calls the implicit-orebody boundary a normal state and names Phase 20D', () => {
    const scope = developmentMeshScope(
      report({ sources: { levelAccesses: true, levels: false, rampSource: 'LAYOUT_V2' } }),
      levels({
        status: 'FAILED',
        // the real backend text: CODE, then a colon and prose
        failureReason:
          `${IMPLICIT_OREBODY_BOUNDARY}: level drifts / crosscuts for a non-TABULAR ` +
          'orebody are not implemented (Phase 20B boundary); ramp junctions and level ' +
          'accesses are available',
      }),
    )
    expect(scope.accessOnly).toBe(true)
    expect(scope.headline).toBe(ACCESS_ONLY_HEADLINE)
    expect(scope.detail).toContain('normal state')
    expect(scope.detail).toContain('Phase 20D')
  })

  it('never calls ANOTHER levels failure normal — it is still access-only, but a failure', () => {
    for (const failureReason of [
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
      expect(scope.detail).not.toContain('Phase 20D')
    }
  })

  it('does not treat a mere substring match as the typed boundary', () => {
    const scope = developmentMeshScope(
      report({ sources: { levelAccesses: true, levels: false, rampSource: 'LAYOUT_V2' } }),
      levels({
        status: 'FAILED',
        failureReason: `wrapped ${IMPLICIT_OREBODY_BOUNDARY} in other prose`,
      }),
    )
    expect(scope.detail).toContain('level development failed')
    expect(scope.detail).not.toContain('Phase 20D')
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
