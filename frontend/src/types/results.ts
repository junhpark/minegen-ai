/**
 * Phase 23C — MineResult 1.0 DTOs (backend `results/models.py`), mirrored
 * for the Simulation Results workspace. A MineResult is an external
 * OBSERVATION bound to a MineExchange sourceSnapshot: the frontend renders
 * what the backend imported and computes no simulation quantity.
 */

export type ResultDomain = 'VENTILATION' | 'OPERATIONS'
export type SourceApplication = 'VENTSIM' | 'ANYLOGIC'
export type TimeAxisKind = 'STATIC' | 'ELAPSED_SECONDS' | 'MINE_DAY'
export type ResultCompatibility = 'COMPATIBLE' | 'STALE'

export const VENTILATION_METRICS = [
  'airflowM3s',
  'velocityMs',
  'pressurePa',
  'pressureLossPa',
  'temperatureDryC',
  'temperatureWetC',
  'airDensityKgM3',
] as const
export type VentilationMetric = (typeof VENTILATION_METRICS)[number]

export const OPERATIONS_EDGE_METRICS = [
  'utilization',
  'queueCount',
  'haulageTonnesPerHour',
  'travelTimeSeconds',
] as const
export type OperationsEdgeMetric = (typeof OPERATIONS_EDGE_METRICS)[number]

export interface SourceSnapshot {
  scenarioRevision: string
  arraysRevision: string
  activeRampSource: 'LEGACY' | 'LAYOUT_V2'
  artifactRevisions: Record<string, string>
}

export interface ResultTimeAxis {
  kind: TimeAxisKind
  unit: string | null
  sampleCount: number
  start: number | null
  end: number | null
}

export interface ResultMetricAvailability {
  name: string
  unit: string
  available: boolean
  sampleCount: number
  min: number | null
  max: number | null
}

export interface ResultCounts {
  edgeCount: number
  timeCount: number
  sampleCount: number
  vehicleCount: number
  edgeMetricSampleCount: number
}

export interface ResultSummary {
  resultId: string
  domain: ResultDomain
  sourceApplication: SourceApplication
  runLabel: string
  description: string
  compatibility: ResultCompatibility
  sourceSnapshot: SourceSnapshot
  timeAxis: ResultTimeAxis
  metrics: ResultMetricAvailability[]
  counts: ResultCounts
  mineResultVersion: string
}

export interface ResultProvenance {
  sourceApplication: SourceApplication
  sourceApplicationVersion: string
  sourceAdapterName: string
  sourceAdapterVersion: string
  sourceMineExchangeVersion: string
  sourceScenarioId: string
  originalFileSha256: string
  importedFileNames: string[]
}

export interface ResultSummaryMetric {
  name: string
  value: number
  unit: string
}

export interface ResultFile {
  path: string
  sha256: string
  mediaType: string
  semantic: string
}

export interface ResultDetail extends ResultSummary {
  provenance: ResultProvenance
  summaryMetrics: ResultSummaryMetric[]
  files: ResultFile[]
  signConvention: string | null
  notes: string[]
  importSourceSha256: string
  normalizedSha256: string
}

export interface ResultListPayload {
  scenarioId: string
  results: ResultSummary[]
}

export interface ResultImportPayload {
  created: boolean
  result: ResultDetail
}

export interface ResultEdgeGeometry {
  edgeId: string
  edgeType: string
  sourceNodeId: string
  targetNodeId: string
  /** LOCAL_ENU_Z_UP metres, chainage 0 at sourceNodeId → 1 at targetNodeId */
  points: number[][]
}

export interface ResultGeometryPayload {
  resultId: string
  coordinateFrame: 'LOCAL_ENU_Z_UP'
  edges: ResultEdgeGeometry[]
}

export interface EdgeValue {
  edgeId: string
  value: number
}

export interface VentilationFrame {
  resultId: string
  metric: string
  unit: string
  timeAxisKind: TimeAxisKind
  time: number | null
  sampleTime: number | null
  values: EdgeValue[]
  missingEdgeIds: string[]
  min: number | null
  max: number | null
  signConvention: string | null
}

export interface OperationsVehicle {
  agentId: string
  agentKind: string | null
  x: number
  y: number
  z: number
  edgeId: string
  chainageFraction: number
  status: string | null
  loadTonnes: number | null
  placement: 'SAMPLE' | 'INTERPOLATED'
}

export interface OperationsEdgeMetricRow {
  edgeId: string
  sampleTime: number
  utilization: number | null
  queueCount: number | null
  haulageTonnesPerHour: number | null
  travelTimeSeconds: number | null
}

export interface OperationsFrame {
  resultId: string
  timeAxisKind: TimeAxisKind
  time: number
  vehicles: OperationsVehicle[]
  edgeMetrics: OperationsEdgeMetricRow[]
}
