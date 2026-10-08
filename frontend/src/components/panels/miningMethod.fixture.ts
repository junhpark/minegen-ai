/** Phase 21B/C test fixture: a registry method table as the scene's
 * `miningMethod.availableMethods` block carries it (statuses and canonical
 * defaults are the backend's; this file only mirrors their shape). */
import type { MiningMethodSummary } from '@/types/scene'

/** the backend registry's canonical Cut & Fill defaults, mirrored for tests */
export const CUT_FILL_DEFAULTS = {
  kind: 'CUT_AND_FILL',
  liftHeightM: 4,
  cutLengthM: 15,
  stopingDirection: 'OVERHAND',
  blockOrder: 'SHALLOW_TO_DEEP',
  panelLengthM: 60,
  ribPillarWidthM: 0,
  maxConcurrentPanels: 2,
  sillMatCureDays: 28,
} as const

export const METHOD_TABLE: MiningMethodSummary['availableMethods'] = [
  {
    method: 'LONGHOLE_OPEN_STOPING',
    displayName: 'Longhole Open Stoping',
    implementationStatus: 'IMPLEMENTED',
    productionKind: 'STOPES',
    defaultParameters: null,
  },
  {
    method: 'CUT_AND_FILL',
    displayName: 'Cut & Fill',
    implementationStatus: 'IMPLEMENTED',
    productionKind: 'CUT_FILL',
    defaultParameters: CUT_FILL_DEFAULTS,
  },
  {
    method: 'ROOM_AND_PILLAR',
    displayName: 'Room & Pillar',
    implementationStatus: 'IMPLEMENTED',
    productionKind: 'ROOM_PILLAR',
    defaultParameters: {
      kind: 'ROOM_AND_PILLAR',
      roomWidthM: 8,
      pillarWidthM: 6,
      headingHeightM: 5,
      benchCount: 1,
      boundaryPillarM: 6,
    },
  },
  {
    method: 'SUBLEVEL_CAVING',
    displayName: 'Sublevel Caving',
    implementationStatus: 'UNSUPPORTED_METHOD',
    productionKind: null,
    defaultParameters: null,
  },
  {
    method: 'SHRINKAGE_STOPING',
    displayName: 'Shrinkage Stoping',
    implementationStatus: 'UNSUPPORTED_METHOD',
    productionKind: null,
    defaultParameters: null,
  },
]

export const LONGHOLE: MiningMethodSummary = {
  method: 'LONGHOLE_OPEN_STOPING',
  displayName: 'Longhole Open Stoping',
  implementationStatus: 'IMPLEMENTED',
  sublevelInterval: 25,
  stopeLength: 20,
  minimumPillar: 15,
  methodParameters: null,
  productionKind: 'STOPES',
  availableMethods: METHOD_TABLE,
}
