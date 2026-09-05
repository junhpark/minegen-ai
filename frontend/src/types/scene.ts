import type { AssetType } from '@/types/enums'

// Scene / world payloads mirroring backend/src/minegen/export/scene_manifest.py.
// Coordinates ENU Z-up meters. Converted only in scene/ components.

export type SliceAxis = 'x' | 'y' | 'z'
export type SliceField = 'rockQuality' | 'grade' | 'faultInfluence' | 'faultZone'

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
  /** row-major display mask, 1 = shown, 0 = hidden (backend-derived) */
  mask: number[]
  /**
   * How the mask was derived: BELOW_TERRAIN, or for the grade field
   * OREBODY_INTERSECTION_BELOW_TERRAIN — display cells that intersect the
   * analytic orebody solid. An intersection is never a membership claim
   * about the sampled point (rule 129).
   */
  maskSemantics: string
  /** display range over the SHOWN cells */
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

/** Backend-authored morphology readout of a WARPED_VEIN (Phase 19):
 * resolved controls plus 2-D diagnostics of the implicit solid. Display
 * only — the frontend never derives any of it. */
export interface OrebodyMorphologyPayload {
  warpAmplitude: number
  centerlineDeviation: number
  outlineIrregularity: number
  thicknessVariability: number
  pinchFloorRatio: number
  edgeTaper: number
  geometryResolution: number
  planformConnectedComponents: number
  minInteriorThickness: number | null
  maxInteriorThickness: number | null
  [key: string]: number | null
}

export interface OrebodyPayload {
  type: string
  center: [number, number, number]
  u: [number, number, number]
  v: [number, number, number]
  w: [number, number, number]
  /** TABULAR only */
  halfExtents?: [number, number, number]
  /** ELLIPSOID only */
  semiAxes?: [number, number, number]
  /** WARPED_VEIN only: nominal L/2, H/2, T/2 (the morphology modulates them) */
  nominalHalfExtents?: [number, number, number]
  /** geometric solid volume — never a resource or reserve figure */
  volumeM3: number
  /** EXACT_METRIC_SDF (analytic) or DERIVED_APPROXIMATE_CLEARANCE (implicit) */
  distanceContract: string
  shapeModelVersion?: number
  morphology?: OrebodyMorphologyPayload
  bboxMin: [number, number, number]
  bboxMax: [number, number, number]
  /** backend-authored DERIVED render mesh — consumed as-is, never membership */
  meshVertices: number
  meshTriangles: number
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

/** Numerical field lattice description (Phase 18, rule 127): origin /
 * spacing / shape so slices can be addressed. Cells are sampling support,
 * never blocks. */
export interface FieldGridPayload {
  origin: [number, number, number]
  spacing: [number, number, number]
  shape: [number, number, number]
}

export interface ArrayStat {
  dtype: string
  bytes: number
}

export interface FieldStatistics {
  min: number
  max: number
  mean: number
  std: number
}

/** Neutral field diagnostics (rule 131): no block counts, no ore tonnes. */
export interface FieldSetStats {
  grid: FieldGridPayload
  cellCount: number
  terrainSupportedFraction: number
  rockQuality: FieldStatistics
  rockQualitySemantics: string
  boundaryPolicy: string | null
  arrays: Record<string, ArrayStat>
  totalBytes: number
  totalMB: number
}

export interface WorldStats {
  terrain: { nx: number; ny: number; spacing: number; zMin: number; zMax: number }
  orebody: Omit<OrebodyPayload, 'positions' | 'indices'>
  faults: number
  fields: FieldSetStats
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
  effectiveSource: EffectiveSource
  fallbackReason: string | null
}

/** Per-segment provenance of an Effective Ramp segment (Phase 20A, rule 149):
 * the two legacy Phase 05 outcomes plus the parametric layout-v2 source. */
export type EffectiveSource = 'SMOOTHED' | 'RAW_FALLBACK' | 'PARAMETRIC_V2'
export type RampSourceKind = 'LEGACY_SMOOTHED' | 'LEGACY_RAW_FALLBACK' | 'PARAMETRIC_V2'
export type RampSource = 'LEGACY' | 'LAYOUT_V2'

/** Phase 20B: turnout on the main ramp where a level access leaves it. */
export interface RampJunction {
  levelId: string
  chainage: number
  position: [number, number, number]
}

/** Phase 20B: the main ramp's RL crossing of a required level — a search /
 * diagnostics reference only, never a level entry (rule 153). */
export interface RampLevelReference {
  levelId: string
  elevation: number
  position: [number, number, number] | null
  chainage: number | null
  footprintDistance: number | null
}

export interface LevelDevelopmentAnchorPayload {
  levelId: string
  elevation: number
  position: [number, number, number]
  headingDeg: number
  backboneDirection: [number, number]
  backboneExtent: [number, number]
  role: string
  orebodySide: string
  miningMethod: string
  standoff: number
  rampLevelReference: [number, number, number] | null
  diagnostics: Record<string, unknown>
}

/** Phase 20B level access (rule 157): RAMP_JUNCTION → LEVEL_ENTRY branch. */
export interface LevelAccessPayload {
  levelId: string
  elevation: number
  status: 'OK' | 'INFEASIBLE'
  anchor: LevelDevelopmentAnchorPayload | null
  rampJunction: [number, number, number] | null
  rampJunctionChainage: number | null
  rampJunctionHeadingDeg: number | null
  rampJunctionEdgeIndex: number | null
  levelEntry: [number, number, number] | null
  terminalHeadingDeg: number | null
  connector: string | null
  pieces: Record<string, unknown>[]
  length3d: number
  horizontalLength: number
  maxGradient: number
  minPlanRadius: number | null
  fieldCost: number | null
  validation: Record<string, number>
  candidatesTried: number
  candidatesValid: number
  rejectionCounts: Record<string, number>
  failureReason: string | null
  failureDetail: string | null
  centerline: { points: number[]; pointCount: number } | null
  /** closeout v3 §2.G: why this branch was selected (backend planning
   * default max(min, 6 × tunnel width) or the explicit scenario value) */
  effectivePreferredAccessLength?: number | null
  lengthDeviationFromPreferred?: number | null
  selectionCost?: number | null
}

export interface LevelAccessSummary {
  feasible: boolean
  levelCount: number
  accessibleLevelCount: number
  totalAccessLength: number
  worstAccessLength: number
  maxAccessGradient: number
  minAccessPlanRadius: number | null
  perLevelLength: Record<string, number | null>
  failures: Record<string, string | null>
  maxGradientLimit: number
  minTurnRadiusLimit: number
  requiredClearance: number
  effectivePreferredAccessLength?: number | null
  preferredAccessSource?: 'DEFAULT_6X_TUNNEL_WIDTH' | 'EXPLICIT' | null
  longAccessCoefficient?: number
  meanAbsDeviationFromPreferred?: number | null
  maxAbsDeviationFromPreferred?: number | null
}

/** derived/level_accesses.json (rule 157) */
export interface LevelAccessesPayload {
  status: 'SUCCESS' | 'FAILED'
  failureReason: string | null
  sourceRevision: string
  layoutRevision?: string
  rampSource: 'LAYOUT_V2'
  rampArtifact: string
  candidateId: string
  family: RampFamily
  miningMethod: string
  clearanceBasis: 'EXACT' | 'CONSERVATIVE'
  requiredClearance: number
  anchors: (LevelDevelopmentAnchorPayload | null)[]
  accesses: LevelAccessPayload[]
  summary: LevelAccessSummary
}

export interface SmoothedSegmentPayload {
  /** LEGACY: the level whose entry ends this segment; PARAMETRIC_V2: the level
   * whose RAMP JUNCTION ends it (null for the RAMP_END tail) */
  levelId: string | null
  /** stable segment identity (PARAMETRIC_V2: RAMP_JUNCTION:Lxx | RAMP_END) */
  segmentId?: string
  terminalKind?: 'RAMP_JUNCTION' | 'RAMP_END'
  rampJunction?: RampJunction | null
  candidateId: string
  smoothed: { points: number[]; pointCount: number } | null
  effectiveSource: EffectiveSource
  effectiveCenterline: { points: number[]; pointCount: number }
  boundaryTangents: { start: [number, number, number]; end: [number, number, number] }
  report: SmoothedSegmentReport
}

/** Stable identity of an effective-ramp segment (matches the tunnel mesh
 * segmentId): explicit for PARAMETRIC_V2, the level id for LEGACY. */
export function rampSegmentId(s: Pick<SmoothedSegmentPayload, 'segmentId' | 'levelId'>): string {
  return s.segmentId ?? s.levelId ?? ''
}

/**
 * Effective Ramp contract (Phase 20A, rules 149–150). The Phase 05 shape is
 * the payload body; the provenance fields say which source produced it. The
 * scene's `smoothedDecline` is always the ACTIVE effective ramp.
 */
export interface SmoothedDeclinePayload {
  status: 'SUCCESS' | 'SUCCESS_WITH_FALLBACK' | 'FAILED'
  failureReason: string | null
  sourceKind?: RampSourceKind
  owningArtifact?: string
  sourceRevision?: string | null
  activeSource?: RampSource
  candidateId?: string | null
  family?: RampFamily | null
  rampJunctions?: RampJunction[]
  rampLevelReferences?: RampLevelReference[]
  levelAccessArtifact?: string
  layoutRevision?: string
  clearance?: LayoutClearanceReport | null
  scores?: LayoutScores | null
  access?: LevelAccessSummary | null
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
  effectiveSource: EffectiveSource
  ringIntervals: number
}

// --------------------------------------------------------------------------- //
// Phase 20A — layout-v2 catalogue (display-only mirrors of the backend contract)
// --------------------------------------------------------------------------- //

export type RampFamily = 'SPIRAL' | 'LONGITUDINAL' | 'SWITCHBACK'
export type LayoutCandidateStatus = 'FEASIBLE' | 'INFEASIBLE' | 'NOT_VALIDATED'

/** Cheap access-potential screen of one level against the main ramp
 * (Phase 20A semantics kept as a stage-2 screen): NOT "served". */
export interface LayoutLevelServiceRecord {
  levelId: string
  elevation: number
  withinReach: boolean
  referencePosition: [number, number, number] | null
  referenceChainage: number | null
  footprintDistance: number | null
  screenReason: string | null
}

export interface LayoutClearanceReport {
  clearanceBasis: 'EXACT' | 'CONSERVATIVE'
  requiredClearance: number
  conservativeMinimumClearance: number
  approximateMinimumClearance: number | null
  clearanceErrorBound: number | null
  satisfied: boolean
}

export interface LayoutScores {
  development: number
  geology: number
  geometry: number
  total: number
  components: Record<string, number>
}

export interface LayoutCandidateDiagnostics {
  pointCount: number
  length3d: number
  horizontalLength: number
  verticalDrop: number
  maxAbsGradient: number
  meanAbsGradient: number
  minPlanRadius: number | null
  turningLength: number
  cumulativeHeadingChangeDeg: number
  signedHeadingChangeDeg: number
  headingReversalCount: number
  hairpinRunCount: number
  dominantAzimuthsDeg: number[]
  turnDirectionConsistency: number
  maxLocalTurnDeg: number
  monotonicDescent: boolean
}

export interface LayoutCandidateSummary {
  candidateId: string
  family: RampFamily
  parameters: Record<string, unknown>
  status: LayoutCandidateStatus
  stageReached: string
  failureReasons: string[]
  failureDetail: string | null
  shortlisted: boolean
  rank: number | null
  /** levels passing the cheap access-potential screen */
  screenedLevels: number
  /** levels with a validated level access (null before detailed validation) */
  accessibleLevels: number | null
  requiredLevels: number
  rampLevelReferences: LayoutLevelServiceRecord[]
  access: LevelAccessSummary | null
  /** level accesses (geometry only for shortlisted candidates) */
  levelAccesses: LevelAccessPayload[] | null
  diagnostics: LayoutCandidateDiagnostics | null
  scores: LayoutScores | null
  clearance: LayoutClearanceReport | null
  cheapProxy: number | null
  /** shipped only by GET …/design/layout-v2 for shortlisted candidates */
  centerline?: { points: number[]; pointCount: number } | null
}

export interface LayoutV2Catalogue {
  layoutVersion: number
  status: 'SUCCESS' | 'NO_FEASIBLE_CANDIDATE'
  portal: [number, number, number]
  portalGenerated: boolean
  requiredLevels: {
    levelId: string
    index: number
    elevation: number
    hasOrebodySection: boolean
  }[]
  serviceableLevelCount: number
  candidateCount: number
  feasibleCount: number
  shortlist: string[]
  ranking: string[]
  winnerId: string | null
  clearanceBasis: 'EXACT' | 'CONSERVATIVE'
  clearanceErrorBound: number
  requiredClearance: number
  accessReach: number
  footwallStandoff: number
  performance: Record<string, number>
  searchConfig: Record<string, unknown>
  candidates: LayoutCandidateSummary[]
}

/** GET …/design/ramp-source (rule 150): the explicit backend-owned source. */
export interface RampSourceSummary {
  activeSource: RampSource
  owningArtifact: string
  available: boolean
  legacyAvailable: boolean
  layoutV2Available: boolean
  layoutV2Selected: boolean
  sourceKind: RampSourceKind | null
  sourceRevision: string | null
  candidateId: string | null
  family: RampFamily | null
  status: string | null
  segmentCount: number
}

export interface NetworkNode {
  id: string
  type: 'PORTAL' | 'LEVEL_ENTRY' | 'JUNCTION' | 'STOPE_ACCESS' | 'RAMP_JUNCTION' | 'RAMP_END'
  position: [number, number, number]
  levelId?: string | null
  candidateId?: string | null
  elevation?: number | null
  stationIndex?: number | null
  /** Phase 20B RAMP_JUNCTION: chainage along the main ramp */
  chainage?: number | null
  stationU?: number | null
}

export type CommunicationLocationKind = 'NODE' | 'EDGE'

export interface CandidateSite {
  id: string
  locationKind: CommunicationLocationKind
  nodeId: string | null
  edgeId: string | null
  chainageM: number | null
  position: [number, number, number]
  eligible: boolean
}

export interface DemandPoint {
  id: string
  locationKind: CommunicationLocationKind
  nodeId: string | null
  edgeId: string | null
  chainageM: number | null
  position: [number, number, number]
  weight: number
}

export interface CommunicationAsset {
  id: string
  assetType: AssetType
  candidateId: string
  position: [number, number, number]
  backhaulParentAssetId: string | null
  hopCount: number
}

export interface DemandCoverage {
  demandId: string
  covered: boolean
  servingAssetId: string | null
  networkDistanceM: number | null
}

export interface CommunicationModelSummary {
  assetType: AssetType
  coverageModel: string
  solver: string
  optimalityClaim: boolean
  coverageRangeM: number
  backhaulRangeM: number
  requiredCoverageFraction: number
}

export interface CommunicationMetrics {
  candidateCount: number
  demandCount: number
  selectedAssetCount: number
  coveredDemandCount: number
  uncoveredDemandCount: number
  coverageFraction: number
  meanServingDistanceM: number | null
  maxServingDistanceM: number | null
  backhaulLinkCount: number
  maxBackhaulHopCount: number
  totalNetworkLength3d: number
}

export interface CommunicationPayload {
  status: 'SUCCESS' | 'FAILED'
  failureReason: string | null
  sourceRevision: string
  model: CommunicationModelSummary | null
  candidates: CandidateSite[]
  demands: DemandPoint[]
  selectedAssets: CommunicationAsset[]
  demandCoverage: DemandCoverage[]
  metrics: CommunicationMetrics | null
}

export interface SensorAsset {
  id: string
  assetType: AssetType
  candidateId: string
  position: [number, number, number]
}

export interface SensorDemandCoverage {
  demandId: string
  covered: boolean
  servingSensorId: string | null
  networkDistanceM: number | null
}

export interface SensorModelSummary {
  assetType: AssetType
  coverageModel: string
  solver: string
  optimalityClaim: boolean
  monitoringRangeM: number
  requiredCoverageFraction: number
}

export interface SensorMetrics {
  candidateCount: number
  demandCount: number
  selectedSensorCount: number
  coveredDemandCount: number
  uncoveredDemandCount: number
  coverageFraction: number
  meanMonitoringDistanceM: number | null
  maxMonitoringDistanceM: number | null
  totalNetworkLength3d: number
}

export interface SensorPayload {
  status: 'SUCCESS' | 'FAILED'
  failureReason: string | null
  sourceRevision: string
  model: SensorModelSummary | null
  candidates: CandidateSite[]
  demands: DemandPoint[]
  selectedSensors: SensorAsset[]
  demandCoverage: SensorDemandCoverage[]
  metrics: SensorMetrics | null
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
  /** Phase 20B: where the LEVEL_ENTRY positions came from (rule 157) */
  entrySource?: 'LEGACY_RAMP_SEGMENT' | 'LEVEL_ACCESS'
  /** Phase 20B: method-specific production development status (rule 159) */
  productionDevelopment?: {
    method: string
    status: 'IMPLEMENTED' | 'UNSUPPORTED_METHOD'
    reason: string | null
  } | null
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
  type: 'RAMP' | 'LEVEL_ACCESS' | 'DRIFT' | 'CROSSCUT' | 'RAISE' | 'SHAFT'
  fromNode: string
  toNode: string
  length3d: number
  meanGradientSigned: number
  maxAbsGradient: number
  crossSection: { width: number; height: number; analyticArea: number }
  effectiveSource: EffectiveSource | 'ANALYTIC'
  fieldCost: number
  geometryRef: { artifact: string; segmentIndex: number }
  simulation: SimulationSlots
}

export interface NetworkMetrics {
  rampJunctionCount?: number
  levelAccessEdgeCount?: number
  totalLevelAccessLength3d?: number
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

/** derived/development_mesh.json (Phase 20B closeout v3 §4): LEVEL_ACCESS /
 * DRIFT / CROSSCUT excavation meshes swept on their owning centerlines with
 * an explicit CAP / OPEN endpoint policy. Presentation only. */
export interface DevelopmentMeshKindSummary {
  developmentCount: number
  ringCount: number
  triangleCount: number
  length3d: number
  nominalExcavationVolume: number
  surfaceArea: number
  endpointPolicies: string[]
}

export interface DevelopmentMeshReport {
  status: 'SUCCESS' | 'FAILED'
  failureReason: string | null
  developmentCount?: number
  ringCount?: number
  triangleCount?: number
  renderVertexCount?: number
  primitiveCount?: number
  length3d?: number
  nominalExcavationVolume?: number
  byKind?: Record<'LEVEL_ACCESS' | 'DRIFT' | 'CROSSCUT', DevelopmentMeshKindSummary>
  profile?: {
    archSegments: number
    mainRampArchSegments: number
    ringMaxSpacing: number
    mainRampRingMaxSpacing: number
    analyticProfileArea: number
  }
  developments?: {
    developmentId: string
    kind: 'LEVEL_ACCESS' | 'DRIFT' | 'CROSSCUT'
    levelId: string
    endpointPolicy: { start: 'CAP' | 'OPEN'; end: 'CAP' | 'OPEN' }
    length3d: number
    triangleCount: number
    topology: { valid: boolean; boundaryEdges: number; expectedBoundaryEdges: number }
  }[]
  booleanUnion?: string
  generationSeconds?: number
  sources?: { levelAccesses: boolean; levels: boolean; rampSource: string }
  glbBytes?: number
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
  result?:
    | DeclinePayload
    | SmoothedDeclinePayload
    | TunnelMeshReport
    | DevelopmentMeshReport
    | LayoutV2Catalogue
    | null
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
  fieldGrid: FieldGridPayload
  rockQuality: { min: number; max: number; defaultSlice: SlicePayload }
  stats: WorldStats
  accessTargets: AccessTargetsPayload | null
  decline: DeclinePayload | null
  /** the ACTIVE Effective Ramp (rules 149–150): the legacy Phase 05 artifact
   * (adapter view) or the selected layout-v2 candidate, never both */
  smoothedDecline: SmoothedDeclinePayload | null
  /** the raw legacy Phase 05 artifact, for the legacy pipeline readout */
  legacySmoothedDecline: SmoothedDeclinePayload | null
  rampSource: RampSourceSummary
  /** layout-v2 catalogue without candidate geometry */
  layoutV2: LayoutV2Catalogue | null
  /** the selected (materialized) layout-v2 effective ramp, active or not */
  layoutV2Selected: SmoothedDeclinePayload | null
  /** Phase 20B: ramp junctions + level accesses of the selection (rule 157) */
  levelAccesses: LevelAccessesPayload | null
  tunnelMesh: TunnelMeshReport | null
  /** closeout v3 §4: level access / drift / crosscut excavation meshes */
  developmentMesh: DevelopmentMeshReport | null
  levels: LevelsPayload | null
  network: NetworkPayload | null
  stopes: StopesPayload | null
  timeline: TimelinePayload | null
  communication: CommunicationPayload | null
  sensors: SensorPayload | null
}
