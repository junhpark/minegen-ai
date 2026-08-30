// Scene / world payloads mirroring backend/src/minegen/export/scene_manifest.py.
// Coordinates ENU Z-up meters. Converted only in scene/ components.

export type SliceAxis = 'x' | 'y' | 'z'
export type SliceField = 'rockQuality' | 'grade' | 'faultInfluence' | 'faultZone' | 'oreFraction'

export interface SliceAxisSpec {
  axis: SliceAxis
  origin: number
  spacing: number
  n: number
}

export interface SlicePayload {
  field: SliceField
  axis: SliceAxis
  index: number
  count: number
  /** coordinate of the slice plane along `axis` */
  coordinate: number
  rows: SliceAxisSpec
  cols: SliceAxisSpec
  /** row-major rows × cols */
  values: number[]
  min: number
  max: number
}

export interface TerrainPayload {
  x0: number
  y0: number
  spacing: number
  nx: number
  ny: number
  /** row-major (i over x, j over y) */
  z: number[]
  zMin: number
  zMax: number
}

export interface OrebodyPayload {
  type: string
  center: [number, number, number]
  u: [number, number, number]
  v: [number, number, number]
  w: [number, number, number]
  halfExtents: [number, number, number]
  volumeM3: number
  tonnes: number
  bboxMin: [number, number, number]
  bboxMax: [number, number, number]
  positions: number[]
  indices: number[]
}

export interface FaultPayload {
  id: string
  strikeDeg: number
  dipDeg: number
  coreHalfWidth: number
  influenceHalfWidth: number
  origin: [number, number, number]
  normal: [number, number, number]
  /** flat ordered convex polygon, vertexCount × 3 */
  polygon: number[]
  vertexCount: number
}

export interface OreBlocksPayload {
  count: number
  spacing: [number, number, number]
  centers: number[]
  grade: number[]
  gradeMin: number
  gradeMax: number
}

export interface BlockGridPayload {
  origin: [number, number, number]
  spacing: [number, number, number]
  shape: [number, number, number]
}

export interface ArrayStat {
  dtype: string
  bytes: number
}

export interface BlockModelStats {
  shape: [number, number, number]
  nBlocks: number
  spacing: [number, number, number]
  origin: [number, number, number]
  nOreBlocks: number
  nAirBlocks: number
  nRockBlocks: number
  oreVolumeM3: number
  oreTonnes: number
  meanOreGrade: number
  rockQualityMean: number
  faultCoreBlocks: number
  faultDamageBlocks: number
  arrays: Record<string, ArrayStat>
  totalBytes: number
  totalMB: number
}

export interface WorldStats {
  terrain: { nx: number; ny: number; spacing: number; zMin: number; zMax: number }
  orebody: Omit<OrebodyPayload, 'positions' | 'indices'>
  faults: number
  blockModel: BlockModelStats
}

export interface AccessCandidatePayload {
  id: string
  levelId: string
  position: [number, number, number]
  uCoord: number
  vCoord: number
  footwallOffset: number
  valid: boolean
  rejectionReasons: string[]
  rockQuality: number | null
  faultPenalty: number | null
  pointCostPerM: number | null
  nextLevelAccessibility: number | null
}

export interface LevelTargetsPayload {
  levelId: string
  index: number
  elevation: number
  nValid: number
  nRejected: number
  candidates: AccessCandidatePayload[]
}

export interface AccessTargetsPayload {
  portal: [number, number, number]
  portalGenerated: boolean
  nLevels: number
  nCandidates: number
  nValid: number
  nRejected: number
  levels: LevelTargetsPayload[]
}

export interface CostEvaluationRow {
  point: [number, number, number]
  valid: boolean
  totalCostPerM: number | null
  baseCost: number | null
  rockPenalty: number | null
  faultPenalty: number | null
  orebodyPenalty: number | null
  rockQuality: number | null
  nearestFaultDistance: number | null
  orebodyDistance: number | null
  rejectionReasons: string[]
}

export interface SearchDiagnostics {
  expandedStates: number
  generatedStates: number
  closedStates: number
  peakOpenSize: number
  prunedOvershoot: number
  rejectedPrimitives: number
  goalShotAttempts: number
  goalShotFailures: Record<string, number>
  elapsedMs: number
  termination: string
  tieBreakBucket: number
  heuristicWeight: number
  admissibleBound: number
  bestApproach: { horizontal: number | null; dz: number | null; depth: number }
}

export interface SegmentPathPayload {
  points: number[]
  pointCount: number
  primitives: {
    steering: string
    grade: number
    curvature: number
    horizontalLength: number
    length3d: number
    endHeadingDeg: number
  }[]
  length: number
  maxGrade: number
  minRadius: number | null
  startHeadingDeg: number
  endHeadingDeg: number
}

export interface CandidateSearchPayload {
  candidateId: string
  initialHeadingDeg: number
  selectionScore: number | null
  selected: boolean
  status: 'SUCCESS' | 'INFEASIBLE' | 'EXPANSION_LIMIT' | 'TIME_LIMIT'
  generalizedCost: number | null
  rawPathLength: number | null
  maxGrade: number | null
  minimumRadius: number | null
  endHeadingDeg: number | null
  diagnostics: SearchDiagnostics
  path: SegmentPathPayload | null
}

export interface LevelDeclinePayload {
  levelId: string
  elevation: number
  status: 'SUCCESS' | 'INFEASIBLE' | 'NO_VALID_CANDIDATES' | 'SKIPPED'
  selectedCandidateId: string | null
  candidateResults: CandidateSearchPayload[]
}

export interface DeclinePayload {
  status: 'SUCCESS' | 'PARTIAL' | 'NO_LEVELS'
  portal: [number, number, number]
  nLevels: number
  completedLevels: number
  elapsedMs: number
  totals: {
    rawLength: number
    generalizedCost: number
    expandedStates: number
    searches: number
    maxGrade: number
    minimumRadius: number | null
  }
  searchConfig: Record<string, unknown>
  levels: LevelDeclinePayload[]
  centerline: { points: number[]; pointCount: number }
}

export interface SmoothedSegmentReport {
  rawLength: number
  smoothedLength: number | null
  fieldCostRaw: number
  fieldCostSmoothed: number | null
  fieldCostDeltaPct: number | null
  maxGradient: number
  minPlanRadius: number | null
  maxDeviationFromRaw: number
  endpointPositionError: number
  startHeadingErrorDeg: number
  endHeadingErrorDeg: number
  invalidSampleCount: number
  rejectionReasonCounts: Record<string, number>
  monotonicityViolations: number
  gradeViolations: number
  radiusViolations: number
  corridorViolations: number
  repairs: number
  valid: boolean
  effectiveSource: 'SMOOTHED' | 'RAW_FALLBACK'
  fallbackReason: string | null
}

export interface SmoothedSegmentPayload {
  levelId: string
  candidateId: string
  smoothed: { points: number[]; pointCount: number } | null
  effectiveSource: 'SMOOTHED' | 'RAW_FALLBACK'
  effectiveCenterline: { points: number[]; pointCount: number }
  boundaryTangents: { start: [number, number, number]; end: [number, number, number] }
  report: SmoothedSegmentReport
}

export interface SmoothedDeclinePayload {
  status: 'SUCCESS' | 'SUCCESS_WITH_FALLBACK' | 'FAILED'
  failureReason: string | null
  segments: SmoothedSegmentPayload[]
  totals: {
    segments: number
    smoothedSegments: number
    fallbackSegments: number
    rawLength: number
    effectiveLength: number
    fieldCostRaw: number
    fieldCostEffective: number
    fieldCostDeltaPct: number | null
    maxGradient: number
    minimumPlanRadius: number | null
    maxDeviation: number
  }
}

export interface TunnelSegmentSummary {
  segmentId: string
  effectiveSource: 'SMOOTHED' | 'RAW_FALLBACK'
  ringIntervals: number
}

export interface NetworkNode {
  id: string
  type: 'PORTAL' | 'LEVEL_ENTRY' | 'JUNCTION' | 'STOPE_ACCESS'
  position: [number, number, number]
  levelId?: string | null
  candidateId?: string | null
  elevation?: number | null
  stationIndex?: number | null
  stationU?: number | null
}

export type TaskTypeId =
  | 'DEVELOP_RAMP'
  | 'DEVELOP_LEVEL'
  | 'DEVELOP_CROSSCUT'
  | 'DEVELOP_RAISE'
  | 'STOPE_PREPARATION'
  | 'STOPING'
  | 'MUCKING'
  | 'BACKFILL'
  | 'CURE_BACKFILL'

export type ObjectStateId =
  'NOT_BUILT' | 'PLANNED' | 'DEVELOPING' | 'ACTIVE' | 'MINED' | 'VOID' | 'BACKFILLED' | 'CLOSED'

export interface StateTransition {
  day: number
  state: ObjectStateId
}

export interface TimelineTask {
  id: string
  taskType: TaskTypeId
  targetKind: 'DEVELOPMENT' | 'STOPE'
  targetId: string
  durationDays: number
  startDay: number
  endDay: number
  dependencies: string[]
  basis: { quantity: number; quantityUnit: string; rate: number; rateUnit: string }
}

export interface DevelopmentTimeline {
  edgeId: string
  edgeType: string
  geometryRef: { artifact: string; segmentIndex: number }
  taskId: string
  initialState: ObjectStateId
  transitions: StateTransition[]
  progressStartDay: number
  progressEndDay: number
  pointChainageFractions: number[]
}

export interface StopeTimeline {
  stopeId: string
  initialState: ObjectStateId
  transitions: StateTransition[]
}

export interface TimelineMetrics {
  taskCount: number
  developmentTaskCount: number
  stopeTaskCount: number
  developmentObjectCount: number
  stopeObjectCount: number
  totalDevelopmentLength3d: number
  totalScheduledTonnes: number
  rampCompletionDay: number
  firstStopingDay: number | null
  endDay: number
}

export interface TimelinePayload {
  status: 'SUCCESS' | 'FAILED'
  failureReason: string | null
  sourceRevision: string
  startDay: number
  endDay: number
  tasks: TimelineTask[]
  developments: DevelopmentTimeline[]
  stopes: StopeTimeline[]
  metrics: TimelineMetrics | null
}

export interface StopeReport {
  upperAnchorError: number
  lowerAnchorError: number
  hardInvalidSamples: number
  strikePillarClearance?: number | null
  finite: boolean
  valid: boolean
  failureReason: string | null
}

export interface Stope {
  id: string
  method: 'LONGHOLE_OPEN_STOPING'
  stationIndex: number
  stationU: number
  upperLevelId: string
  lowerLevelId: string
  upperAccessNodeId: string
  lowerAccessNodeId: string
  localBounds: {
    uMin: number
    uMax: number
    vMin: number
    vMax: number
    wMin: number
    wMax: number
  }
  geometry: { vertices: number[]; triangleIndices: number[] }
  strikeLength: number
  downDipSpan: number
  verticalHeight: number
  thickness: number
  geometricVolumeM3: number
  tonnes: number
  meanGradeProxy: number | null
  report: StopeReport
  plannedState: 'PLANNED'
}

export interface StopesPayload {
  status: 'SUCCESS' | 'FAILED'
  failureReason: string | null
  sourceRevision: string
  method: string
  stopes: Stope[]
  metrics: {
    stopeCount: number
    levelIntervalCount: number
    stationsPerInterval: number
    totalGeometricVolumeM3: number
    totalTonnes: number
    geometricExtractionFractionOfOrebody: number
    weightedMeanGradeProxy: number | null
  } | null
}

export interface LevelDevelopmentReport {
  startWeldError: number
  envelopeHardViolations: number
  envelopeAboveTerrain: number
  terminalSdf?: number | null
  interiorBreachSamples: number
  fieldCost: number
  valid: boolean
  failureReason: string | null
}

export interface LevelDevelopment {
  id: string
  kind: 'DRIFT' | 'CROSSCUT'
  levelId: string
  stationIndex?: number | null
  stationU?: number | null
  fromU: number
  toU: number
  centerline: { points: number[] }
  length3d: number
  meanGradientSigned: number
  maxAbsGradient: number
  report: LevelDevelopmentReport
}

export interface LevelsPayload {
  status: 'SUCCESS' | 'FAILED'
  failureReason: string | null
  sourceRevision: string
  developments: LevelDevelopment[]
  levels: {
    levelId: string
    candidateId: string
    entry: [number, number, number]
    entryU: number
    driftPieceCount: number
    crosscutCount: number
    valid: boolean
  }[]
  metrics: {
    levelCount: number
    developmentCount: number
    driftPieceCount: number
    crosscutCount: number
    stationPitch: number
    stationsPerLevel: number
    totalDriftLength3d: number
    totalCrosscutLength3d: number
  } | null
}

/** Typed RESERVED simulation attributes: later phases fill these; until
 * then the only legal value per slot is null. */
export interface SimulationSlots {
  haulage: null
  ventilation: null
  communication: null
  rockRisk: null
}

export interface NetworkEdge {
  id: string
  type: 'RAMP' | 'DRIFT' | 'CROSSCUT' | 'RAISE' | 'SHAFT'
  fromNode: string
  toNode: string
  length3d: number
  meanGradientSigned: number
  maxAbsGradient: number
  crossSection: { width: number; height: number; analyticArea: number }
  effectiveSource: 'SMOOTHED' | 'RAW_FALLBACK' | 'ANALYTIC'
  fieldCost: number
  geometryRef: { artifact: string; segmentIndex: number }
  simulation: SimulationSlots
}

export interface NetworkMetrics {
  nodeCount: number
  edgeCount: number
  levelCount: number
  junctionCount: number
  stopeAccessCount: number
  driftEdgeCount: number
  crosscutEdgeCount: number
  totalRampLength3d: number
  totalDriftLength3d: number
  totalCrosscutLength3d: number
  minimumElevation: number
  verticalDropFromPortal: number
}

export interface NetworkValidation {
  maxNodeSyncError: number
  syncTolerance: number
  synchronized: boolean
  connected: boolean
  connectedComponents: number
}

export interface NetworkPayload {
  status: 'SUCCESS' | 'FAILED'
  failureReason: string | null
  sourceRevision: string
  nodes: NetworkNode[]
  edges: NetworkEdge[]
  metrics: NetworkMetrics | null
  validation: NetworkValidation | null
  surfacePathAdvisory: {
    criterion: string
    requiredPaths: number
    advisoryOnly: boolean
    perNode: {
      nodeId: string
      levelId: string
      independentSurfacePaths: number
      meetsCriterion: boolean
    }[]
  }[]
}

export interface TunnelMeshReport {
  status: 'SUCCESS' | 'FAILED'
  failureReason: string | null
  length3d?: number
  analyticProfileArea?: number
  meshProfileArea?: number
  tessellationBiasPct?: number
  crownRadius?: number
  profileEnvelopeReach?: number
  nominalExcavationVolume?: number
  meshEnclosedVolume?: number
  volumeDifferencePct?: number | null
  excavationSurfaceArea?: number
  closedMeshSurfaceArea?: number
  ringCount?: number
  logicalVertexCount?: number
  renderVertexCount?: number
  triangleCount?: number
  watertight?: boolean
  manifold?: boolean
  geometricallyClosed?: boolean
  degenerateTriangles?: number
  outwardOrientation?: boolean
  junctionGapMax?: number
  maxLocalTurnDeg?: number
  envelopeViolations?: number
  envelopeReasonCounts?: Record<string, number>
  burialRing?: number
  selfIntersectionCheck?: string
  segments?: TunnelSegmentSummary[]
  artifactRevision: string | null
  meshUrl: string | null
}

export type JobStatus = 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED'

export interface JobProgress {
  stage: string
  phase: string
  level: number
  total_levels: number
  candidate: number
  total_candidates: number
  progress: number
  expanded_states: number
  message: string
  level_id: string
  candidate_id: string
  candidate_status: string
}

export interface JobRecord {
  jobId: string
  scenarioId: string
  kind: string
  status: JobStatus
  createdAt: number
  startedAt: number | null
  finishedAt: number | null
  progress: Partial<JobProgress>
  error: { code: string; message: string } | null
  version: number
  result?: DeclinePayload | SmoothedDeclinePayload | TunnelMeshReport | null
}

export interface JobSubmission {
  jobId: string
  status: JobStatus
  scenarioId: string
  kind: string
}

export interface WorldScene {
  scenarioId: string
  coordinateSystem: 'ENU_Z_UP'
  world: {
    sizeX: number
    sizeY: number
    depth: number
    bottomElevation: number
    referenceElevation: number
  }
  terrain: TerrainPayload
  orebody: OrebodyPayload
  faults: FaultPayload[]
  oreBlocks: OreBlocksPayload
  blockGrid: BlockGridPayload
  rockQuality: { min: number; max: number; defaultSlice: SlicePayload }
  stats: WorldStats
  accessTargets: AccessTargetsPayload | null
  decline: DeclinePayload | null
  smoothedDecline: SmoothedDeclinePayload | null
  tunnelMesh: TunnelMeshReport | null
  levels: LevelsPayload | null
  network: NetworkPayload | null
  stopes: StopesPayload | null
  timeline: TimelinePayload | null
}
