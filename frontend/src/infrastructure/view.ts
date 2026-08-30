import type { AppMode } from '@/types/enums'
import type { CommunicationPayload } from '@/types/scene'

/**
 * Phase 11 view assembly (rules 88/91/92): the frontend only maps
 * backend-computed placement/coverage results to render data. It performs
 * NO communication engineering — no distance computation, no coverage
 * prediction, no Euclidean range spheres (the model is network-geodesic,
 * and an XYZ sphere would misrepresent the contract).
 */

/** Communication layers render only in INFRASTRUCTURE mode with a SUCCESS
 * payload; DESIGN and 4D rendering stay untouched. */
export function communicationLayersActive(
  mode: AppMode,
  communication: CommunicationPayload | null,
): boolean {
  return mode === 'INFRASTRUCTURE' && communication?.status === 'SUCCESS'
}

/** Rule 91: router installation timing is not modeled, so 4D mode never
 * presents Phase 11 routers as time-valid installed assets. */
export function communicationVisibleIn4D(): false {
  return false
}

/** Backend router positions, passed through untransformed (ENU Z-up). */
export function routerMarkers(
  communication: CommunicationPayload,
): { id: string; position: [number, number, number]; hopCount: number }[] {
  return communication.selectedAssets.map((a) => ({
    id: a.id,
    position: a.position,
    hopCount: a.hopCount,
  }))
}

/** Split demand points into covered/uncovered using ONLY the backend
 * demandCoverage assignments (no frontend distance calculation). */
export function demandRenderData(communication: CommunicationPayload): {
  covered: [number, number, number][]
  uncovered: [number, number, number][]
} {
  const positionById = new Map(communication.demands.map((d) => [d.id, d.position]))
  const covered: [number, number, number][] = []
  const uncovered: [number, number, number][] = []
  for (const row of communication.demandCoverage) {
    const p = positionById.get(row.demandId)
    if (!p) continue
    ;(row.covered ? covered : uncovered).push(p)
  }
  return { covered, uncovered }
}
