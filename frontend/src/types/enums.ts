// Mirrors backend/src/minegen/core/enums.py. Add values, never rename.

/** WARPED_VEIN (Phase 19) is the deterministic synthetic irregular implicit
 * body; PIPE and LENS stay reserved for their own future semantics. */
export const OREBODY_TYPES = ['TABULAR', 'ELLIPSOID', 'PIPE', 'LENS', 'WARPED_VEIN'] as const
export type OrebodyType = (typeof OREBODY_TYPES)[number]

export const NODE_TYPES = [
  'PORTAL',
  'JUNCTION',
  'LEVEL_ENTRY',
  'STOPE_ACCESS',
  'RAMP_JUNCTION',
  'RAMP_END',
  // Phase 20C.2B shaft infrastructure (rules 182–184)
  'SHAFT_COLLAR',
  'SHAFT_STATION',
  'SHAFT_BOTTOM',
  'CRUSHER',
  'REFUGE',
  'FAN',
  'ROUTER',
  'SENSOR',
] as const
export type NodeType = (typeof NODE_TYPES)[number]

export const EDGE_TYPES = [
  'RAMP',
  'LEVEL_ACCESS',
  'DRIFT',
  'CROSSCUT',
  'RAISE',
  'SHAFT',
  // Phase 20C.2B: station drive from a SHAFT_STATION to a level node
  'SHAFT_STATION_ACCESS',
] as const
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

export const ASSET_TYPES = [
  'WIFI_AP',
  'MESH_ROUTER',
  'UWB_ANCHOR',
  'LORA_GATEWAY',
  'REPEATER',
  'GAS_SENSOR',
  'TEMPERATURE_SENSOR',
  'HUMIDITY_SENSOR',
  'AIR_VELOCITY_SENSOR',
  'CONVERGENCE_SENSOR',
  'SEISMIC_SENSOR',
  'DUST_SENSOR',
  'CAMERA',
  'RTLS_ANCHOR',
] as const
export type AssetType = (typeof ASSET_TYPES)[number]

export const APP_MODES = ['DESIGN', 'INFRASTRUCTURE', '4D', 'WALKTHROUGH', 'ANALYSIS'] as const
export type AppMode = (typeof APP_MODES)[number]

/** Viewer layers (SRS §42). Only the first two exist before Phase 02. */
export const LAYER_IDS = [
  'terrain',
  'orebody',
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
  'sensorCoverage',
  'network',
  'coverage',
  'hazards',
  'equipment',
  'networkGraph',
  'rawSearchPath',
  'smoothedDecline',
  'layoutV2',
  'levelAccesses',
  'tunnelMesh',
  'developmentMesh',
  // Phase 20C.2B: shaft axes, stations and station drives (backend geometry)
  'shafts',
] as const
export type LayerId = (typeof LAYER_IDS)[number]

/** Phase 20C.2B capability taxonomy (rule 185): a may / may-not tag, never
 * a capacity. Mirrors backend Capability. */
export const CAPABILITIES = [
  'PERSONNEL_ACCESS',
  'MATERIAL_HAULAGE',
  'VENTILATION_PATH',
  'UTILITY_SERVICE',
  'EMERGENCY_EGRESS',
] as const
export type Capability = (typeof CAPABILITIES)[number]
