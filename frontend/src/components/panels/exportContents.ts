/**
 * Phase 23A (PR #44 correction S3) + 21A (MineExchange 1.1): what the export will
 * contain RIGHT NOW, read from the already-loaded scene snapshot.
 *
 * This is a READ of existing status only. The panel never calls a
 * generation endpoint, never infers a layer from another, and never decides
 * the bundle: the backend manifest (`omissions[]`) stays the authority. The
 * scene payload is itself a validated snapshot — a STALE / MALFORMED
 * artifact is refused by the scene endpoint before it reaches this helper,
 * so the three states the existing API lets us distinguish are
 * included / not generated / failed.
 */
import type { ProductionKind, WorldScene } from '@/types/scene'

export type ExportLayerState = 'INCLUDED' | 'NOT_GENERATED' | 'FAILED'

export interface ExportLayer {
  key: string
  label: string
  state: ExportLayerState
}

export const EXPORT_HELPER_TEXT =
  'MineExchange exports the currently available mine state. Layers not yet generated are omitted and recorded in the manifest.'

function stateOf(payload: { status: string } | null | undefined): ExportLayerState {
  if (payload == null) return 'NOT_GENERATED'
  return payload.status === 'FAILED' ? 'FAILED' : 'INCLUDED'
}

/**
 * @param scene the loaded world scene (null → nothing can be exported yet)
 * @param shaftsDeclared whether the scenario document declares any shaft;
 *   an undeclared shaft is not a missing layer and gets no row
 */
export function describeExportContents(
  scene: WorldScene | null,
  shaftsDeclared: boolean,
): ExportLayer[] {
  if (!scene) return []
  const layers: ExportLayer[] = [
    { key: 'terrain', label: 'Terrain', state: 'INCLUDED' },
    { key: 'orebody', label: 'Orebody', state: 'INCLUDED' },
    { key: 'faults', label: `Faults (${scene.faults.length})`, state: 'INCLUDED' },
    // MineExchange 1.1: the method semantics document is always present
    // (the scenario is its first authority)
    { key: 'miningMethod', label: 'Mining method', state: 'INCLUDED' },
    { key: 'ramp', label: 'Ramp', state: stateOf(scene.smoothedDecline) },
  ]
  if (scene.rampSource.activeSource === 'LAYOUT_V2') {
    layers.push({
      key: 'levelAccesses',
      label: 'Level accesses',
      state: stateOf(scene.levelAccesses),
    })
  }
  layers.push({ key: 'levels', label: 'Levels', state: stateOf(scene.levels) })
  if (shaftsDeclared) {
    layers.push({ key: 'shafts', label: 'Shafts', state: stateOf(scene.shafts) })
  }
  layers.push(
    { key: 'tunnelMesh', label: 'Ramp render mesh', state: stateOf(scene.tunnelMesh) },
    {
      key: 'developmentMesh',
      label: 'Development render mesh',
      state: stateOf(scene.developmentMesh),
    },
    { key: 'network', label: 'Network', state: stateOf(scene.network) },
    { key: 'capability', label: 'Capability', state: stateOf(scene.capabilityGraph) },
    // MineExchange 1.1 / 1.2: the ACTIVE method's production solids
    // (stopes / cuts / rooms-benches-pillars) — one production kind per bundle
    {
      key: 'stopes',
      label: scene.miningMethod.productionKind
        ? PRODUCTION_LABEL[scene.miningMethod.productionKind]
        : 'Production (method not implemented)',
      state: stateOf(scene.stopes),
    },
  )
  return layers
}

/** the bundle group of each production kind, as MineExchange names it */
export const PRODUCTION_LABEL: Record<ProductionKind, string> = {
  STOPES: 'Stopes',
  CUT_FILL: 'Cut & Fill production',
  ROOM_PILLAR: 'Room & Pillar production',
}

export const STATE_TEXT: Record<ExportLayerState, string> = {
  INCLUDED: 'included',
  NOT_GENERATED: 'not generated',
  FAILED: 'failed',
}

/**
 * Phase 23B.1: whether the Ventsim SEED adapter can run RIGHT NOW. The seed
 * needs the excavation centerlines and the MineNetwork in the MineExchange
 * bundle (the backend refuses with REQUIRED_SOURCE_ABSENT otherwise); the
 * panel only mirrors that prerequisite from the loaded scene and never
 * decides the package contents — the adapter report is the authority.
 */
export interface VentsimSeedAvailability {
  enabled: boolean
  reason: string
}

export const VENTSIM_SEED_HELPER_TEXT =
  'Ventsim seed: one DXF polyline per network edge plus an airway attribute table (lengths, width / height). Ventilation properties are not provided.'

export function describeVentsimSeedAvailability(scene: WorldScene | null): VentsimSeedAvailability {
  if (!scene) return { enabled: false, reason: 'Generate a world first.' }
  if (scene.smoothedDecline == null || scene.smoothedDecline.status === 'FAILED') {
    return { enabled: false, reason: 'A ramp (excavation centerlines) is required.' }
  }
  if (scene.network == null || scene.network.status !== 'SUCCESS') {
    return { enabled: false, reason: 'A generated MineNetwork is required.' }
  }
  return { enabled: true, reason: 'Ready: the network and centerlines are in the bundle.' }
}
