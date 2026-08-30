import type { AppMode } from '@/types/enums'
import type { CommunicationPayload, SensorPayload } from '@/types/scene'

/**
 * Phase 11 view assembly (rules 88/91/92): the frontend only maps
 * backend-computed placement/coverage results to render data. It performs
 * NO communication engineering — no distance computation, no coverage
 * prediction, no Euclidean range spheres (the model is network-geodesic,
 * and an XYZ sphere would misrepresent the contract).
 */

/** §27 enable contract: communication generation requires a SUCCESS
 * MineNetwork. Pure so the panel gate is directly testable. */
export function canGenerateCommunication(network: { status: string } | null): boolean {
  return network?.status === 'SUCCESS'
}

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

/** §30 enable contract: sensor generation requires a SUCCESS MineNetwork
 * (never communication — siblings, rule 97). Pure for direct testability. */
export function canGenerateSensors(network: { status: string } | null): boolean {
  return network?.status === 'SUCCESS'
}

/** Sensor layers render only in INFRASTRUCTURE mode with a SUCCESS payload;
 * DESIGN and 4D rendering stay untouched (rule 98). */
export function sensorLayersActive(mode: AppMode, sensors: SensorPayload | null): boolean {
  return mode === 'INFRASTRUCTURE' && sensors?.status === 'SUCCESS'
}

/** Rule 97: sensor installation timing is not modeled, so 4D mode never
 * presents Phase 12 sensors as time-valid installed assets. */
export function sensorsVisibleIn4D(): false {
  return false
}

/** Backend sensor positions, passed through untransformed (ENU Z-up). */
export function sensorMarkers(
  sensors: SensorPayload,
): { id: string; position: [number, number, number] }[] {
  return sensors.selectedSensors.map((a) => ({ id: a.id, position: a.position }))
}

/** Split monitoring demand points into covered/uncovered using ONLY the
 * backend demandCoverage assignments (no frontend distance calculation). */
export function sensorDemandRenderData(sensors: SensorPayload): {
  covered: [number, number, number][]
  uncovered: [number, number, number][]
} {
  const positionById = new Map(sensors.demands.map((d) => [d.id, d.position]))
  const covered: [number, number, number][] = []
  const uncovered: [number, number, number][] = []
  for (const row of sensors.demandCoverage) {
    const p = positionById.get(row.demandId)
    if (!p) continue
    ;(row.covered ? covered : uncovered).push(p)
  }
  return { covered, uncovered }
}
