// Mirrors backend/src/minegen/core/enums.py. Add values, never rename.

export const OREBODY_TYPES = ['TABULAR', 'ELLIPSOID', 'PIPE', 'LENS'] as const
export type OrebodyType = (typeof OREBODY_TYPES)[number]

export const NODE_TYPES = [
  'PORTAL',
  'JUNCTION',
  'LEVEL_ENTRY',
  'STOPE_ACCESS',
  'SHAFT_STATION',
  'CRUSHER',
  'REFUGE',
  'FAN',
  'ROUTER',
  'SENSOR',
] as const
export type NodeType = (typeof NODE_TYPES)[number]

export const EDGE_TYPES = ['RAMP', 'DRIFT', 'CROSSCUT', 'RAISE', 'SHAFT'] as const
export type EdgeType = (typeof EDGE_TYPES)[number]

export const OBJECT_STATES = [
  'NOT_BUILT',
  'PLANNED',
  'DEVELOPING',
  'ACTIVE',
  'MINED',
  'VOID',
  'BACKFILLED',
  'CLOSED',
] as const
export type ObjectState = (typeof OBJECT_STATES)[number]

export const MINING_METHODS = [
  'LONGHOLE_OPEN_STOPING',
  'CUT_AND_FILL',
  'ROOM_AND_PILLAR',
  'SUBLEVEL_CAVING',
  'SHRINKAGE_STOPING',
] as const
export type MiningMethodType = (typeof MINING_METHODS)[number]

export const APP_MODES = ['DESIGN', 'INFRASTRUCTURE', '4D', 'WALKTHROUGH', 'ANALYSIS'] as const
export type AppMode = (typeof APP_MODES)[number]

/** Viewer layers (SRS §42). Only the first two exist before Phase 02. */
export const LAYER_IDS = [
  'terrain',
  'orebody',
  'gradeBlocks',
  'rockQuality',
  'faults',
  'accessTargets',
  'joints',
  'ramp',
  'levels',
  'crosscuts',
  'raises',
  'stopes',
  'backfill',
  'routers',
  'sensors',
  'coverage',
  'hazards',
  'equipment',
  'networkGraph',
  'rawSearchPath',
  'smoothedDecline',
  'tunnelMesh',
] as const
export type LayerId = (typeof LAYER_IDS)[number]
