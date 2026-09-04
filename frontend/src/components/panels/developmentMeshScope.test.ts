/**
 * Closeout v4 §1.1: an access-only development mesh must say so.
 *
 * The two ways `sources.levels` becomes false — no levels artifact at all,
 * and a persisted levels artifact whose status is FAILED (the implicit
 * orebody Phase 20B boundary) — carry the SAME headline; only the
 * explanation differs. There is deliberately no stale state here: the tests
 * at the bottom pin the two mechanisms that make a stale report impossible.
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

  it('uses the same headline for a typed-FAILED levels artifact, with the Phase 20D note', () => {
    const scope = developmentMeshScope(
      report({ sources: { levelAccesses: true, levels: false, rampSource: 'LAYOUT_V2' } }),
      levels({
        status: 'FAILED',
        failureReason: 'LEVEL_DEVELOPMENT_UNSUPPORTED_FOR_IMPLICIT_OREBODY',
      }),
    )
    expect(scope.accessOnly).toBe(true)
    expect(scope.headline).toBe(ACCESS_ONLY_HEADLINE)
    expect(scope.detail).toContain('normal state')
    expect(scope.detail).toContain('Phase 20D')
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
