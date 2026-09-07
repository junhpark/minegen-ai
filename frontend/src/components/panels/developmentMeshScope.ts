import type { DevelopmentMeshReport, LevelsPayload } from '@/types/scene'

/**
 * Which owning artifacts actually CONTRIBUTED geometry to a development
 * mesh (closeout v4 §1.1).
 *
 * The backend already reports contribution rather than mere existence:
 * `sources.levels` is true only for a levels artifact whose status is
 * SUCCESS, so a persisted but FAILED levels artifact reads as false,
 * exactly like no levels artifact at all. Both produce an access-only
 * sweep, which the panel must say out loud — otherwise the mesh reads as
 * "the level meshes are missing".
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
  //
  // Phase 20C.2A removed the old LEVEL_DEVELOPMENT_UNSUPPORTED_FOR_
  // IMPLICIT_OREBODY "normal boundary": an implicit orebody now develops
  // real drifts / crosscuts along its curved section-trace backbone, so a
  // FAILED levels artifact is always a real failure to say out loud.
  if (!report || report.status !== 'SUCCESS' || !report.sources) return NONE
  if (report.sources.levels) return NONE
  const failed = levels?.status === 'FAILED'
  return {
    accessOnly: true,
    headline: ACCESS_ONLY_HEADLINE,
    detail: failed
      ? 'level development failed; the mesh contains level-access geometry only'
      : 'generate level development to add drift / crosscut geometry',
  }
}
