import type { DevelopmentMeshReport, LevelsPayload } from '@/types/scene'

/**
 * Which owning artifacts actually CONTRIBUTED geometry to a development
 * mesh (closeout v4 §1.1).
 *
 * The backend already reports contribution rather than mere existence:
 * `sources.levels` is true only for a levels artifact whose status is
 * SUCCESS, so a persisted but typed-FAILED levels artifact (the implicit
 * orebody Phase 20B boundary) reads as false, exactly like no levels
 * artifact at all. Both produce an access-only sweep, which the panel must
 * say out loud — otherwise the mesh reads as "the level meshes are missing".
 *
 * This is NOT a staleness signal and there is no stale state to model:
 * regenerating levels deletes `development_mesh.{json,glb}` in
 * `DesignService._delete_levels_artifact` / `generate_levels`, and
 * `afterLevelsRegen` nulls `scene.developmentMesh` in the same step, so a
 * report can never describe a superseded levels artifact.
 */
export interface DevelopmentMeshScope {
  /** the sweep carried level accesses only — no drift / crosscut geometry */
  accessOnly: boolean
  headline: string | null
  detail: string | null
}

const NONE: DevelopmentMeshScope = { accessOnly: false, headline: null, detail: null }

export const ACCESS_ONLY_HEADLINE = 'ACCESS-ONLY · no level development geometry'

/**
 * The ONE levels failure that is a normal Phase 20B boundary rather than a
 * defect. `LevelDevelopmentBuilder` also emits LEVEL_ACCESSES_REQUIRED, "no
 * level entries to develop", "smoothed artifact has no effective segments",
 * "orebody strike vector is not horizontal" and others — every one of those
 * is a real failure and must never be worded as normal.
 *
 * The literal is pinned on both sides: `IMPLICIT_OREBODY_BOUNDARY` in
 * backend/tests/test_layout_v2_api.py asserts the backend reason STARTS with
 * it, so a backend rename breaks CI instead of silently degrading this panel
 * to the generic wording (closeout v5 §2).
 */
export const IMPLICIT_OREBODY_BOUNDARY = 'LEVEL_DEVELOPMENT_UNSUPPORTED_FOR_IMPLICIT_OREBODY'

export function developmentMeshScope(
  report: DevelopmentMeshReport | null,
  levels: LevelsPayload | null,
): DevelopmentMeshScope {
  // a failed sweep reports its own failureReason; scope only qualifies a
  // successful one. An older report without `sources` claims nothing.
  if (!report || report.status !== 'SUCCESS' || !report.sources) return NONE
  if (report.sources.levels) return NONE
  // `accessOnly` and the headline hold for EVERY non-contributing levels
  // artifact — the sweep really does carry no drift / crosscut geometry.
  // Only the explanation distinguishes the typed boundary from a failure.
  const failed = levels?.status === 'FAILED'
  const typedBoundary = failed && (levels.failureReason ?? '').startsWith(IMPLICIT_OREBODY_BOUNDARY)
  return {
    accessOnly: true,
    headline: ACCESS_ONLY_HEADLINE,
    detail: typedBoundary
      ? 'level development contributed nothing (typed boundary) — a normal state; ' +
        'drift / crosscut geometry for this orebody is Phase 20D'
      : failed
        ? 'level development failed; the mesh contains level-access geometry only'
        : 'generate level development to add drift / crosscut geometry',
  }
}
