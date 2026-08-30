/**
 * Canonical selected-object resolver (rule 109): selectedObjectId remains
 * the single global selection identity; this helper only RESOLVES an id
 * against backend-authored scene payloads — access candidates (existing
 * behaviour preserved), MESH_ROUTER and GAS_SENSOR assets. Unknown or
 * stale ids resolve to null; identity never derives from instance order.
 */
import type {
  AccessCandidatePayload,
  CommunicationAsset,
  CommunicationModelSummary,
  SensorAsset,
  SensorModelSummary,
  WorldScene,
} from '@/types/scene'

export type ResolvedSelection =
  | { kind: 'ACCESS_CANDIDATE'; candidate: AccessCandidatePayload }
  | { kind: 'MESH_ROUTER'; asset: CommunicationAsset; model: CommunicationModelSummary | null }
  | { kind: 'GAS_SENSOR'; asset: SensorAsset; model: SensorModelSummary | null }

export function resolveSelectedObject(
  scene: WorldScene | null | undefined,
  selectedObjectId: string | null | undefined,
): ResolvedSelection | null {
  if (!scene || !selectedObjectId) return null
  const candidate = scene.accessTargets?.levels
    .flatMap((l) => l.candidates)
    .find((c) => c.id === selectedObjectId)
  if (candidate) return { kind: 'ACCESS_CANDIDATE', candidate }
  const communication = scene.communication
  if (communication?.status === 'SUCCESS') {
    const asset = communication.selectedAssets.find(
      (a) => a.id === selectedObjectId && a.assetType === 'MESH_ROUTER',
    )
    if (asset) return { kind: 'MESH_ROUTER', asset, model: communication.model }
  }
  const sensors = scene.sensors
  if (sensors?.status === 'SUCCESS') {
    const asset = sensors.selectedSensors.find(
      (s) => s.id === selectedObjectId && s.assetType === 'GAS_SENSOR',
    )
    if (asset) return { kind: 'GAS_SENSOR', asset, model: sensors.model }
  }
  return null
}

/** Phase 12 semantic disclaimer, reused verbatim wherever sensors appear. */
export const SENSOR_PROXY_DISCLAIMER =
  'Network-distance monitoring-layout proxy. Not a gas-dispersion or physical detection model.'

/** Phase 14 static-layout semantics (rule 108). */
export const PLANNED_LAYOUT_LABEL = 'Planned static layout'
export const INSTALLATION_TIMING_NOTE = 'Installation timing is not modeled.'
