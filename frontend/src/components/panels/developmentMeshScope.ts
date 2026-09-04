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

export function developmentMeshScope(
  report: DevelopmentMeshReport | null,
  levels: LevelsPayload | null,
): DevelopmentMeshScope {
  // a failed sweep reports its own failureReason; scope only qualifies a
  // successful one. An older report without `sources` claims nothing.
  if (!report || report.status !== 'SUCCESS' || !report.sources) return NONE
  if (report.sources.levels) return NONE
  return {
    accessOnly: true,
    headline: ACCESS_ONLY_HEADLINE,
    detail:
      levels && levels.status !== 'SUCCESS'
        ? 'level development contributed nothing (typed boundary) — a normal state; ' +
          'drift / crosscut geometry for this orebody is Phase 20D'
        : 'generate level development to add drift / crosscut geometry',
  }
}
