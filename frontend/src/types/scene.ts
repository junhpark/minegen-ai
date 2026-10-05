import type { MethodParameters } from '@/types/api'
import type { AssetType, Capability, MiningMethodType } from '@/types/enums'

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
  /** Phase 20B.2-A one-turn CS connector observability (reported, never
   * gated): terminal heading vs the drift AXIS (0–90°), turnout arc and
   * final straight lengths, delivered plan length / junction→entry plan
   * separation */
  terminalHeadingMismatchDeg?: number | null
  turnoutArcLength?: number | null
  straightLength?: number | null
  pathToChordRatio?: number | null
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
  /** Phase 20B.2-A one-turn CS observability aggregates */
  maxTerminalHeadingMismatchDeg?: number | null
  maxTurnoutArcLength?: number | null
  maxPathToChordRatio?: number | null
  connectorWords?: Record<string, number>
}

/** derived/shafts.json (Phase 20C.2B, rules 182–184): the ONLY owner of
 * shaft geometry — collar, axis segments, bottom, stations, station drives.
 * Rendered as delivered; nothing is reconstructed on the client. */
export interface ShaftCenterline {
  id: string
  shaftId: string
  kind: 'SHAFT_SEGMENT' | 'STATION_ACCESS'
  levelId: string | null
  centerline: { points: number[] }
  length3d: number
  fieldCost: number
}

export interface ShaftStation {
  stationId: string
  levelId: string
  elevation: number
  point: [number, number, number]
  connectionTarget: {
    nodeKind: 'LEVEL_ENTRY' | 'JUNCTION'
    levelId: string
    stationU: number
    position: [number, number, number]
    planDistanceToAxis: number
  } | null
  accessCenterlineIndex: number | null
  status: 'OK' | 'FAILED'
  failureCode?: string | null
  failureReason?: string | null
}

export interface Shaft {
  shaftId: string
  role: 'PRODUCTION' | 'SERVICE' | 'VENTILATION'
  capabilities: Capability[]
  profile: { shape: 'CIRCULAR'; diameter: number; analyticArea: number }
  collar: [number, number, number]
  collarSource: 'EXPLICIT' | 'DEFAULT_DERIVED'
  bottom: [number, number, number]
  stations: ShaftStation[]
  segmentIndices: number[]
  validation: { valid: boolean; rejectionCounts: Record<string, number> } | null
  metrics: {
    depth: number
    stationCount: number
    totalShaftLength3d: number
    totalStationAccessLength3d: number
    nominalExcavationVolume: number
  } | null
  status: 'OK' | 'FAILED'
  failureCode?: string | null
  failureReason?: string | null
}

export interface ShaftsPayload {
  status: 'SUCCESS' | 'FAILED'
  failureReason: string | null
  sourceRevision: string
  levelsRevision: string
  shafts: Shaft[]
  centerlines: ShaftCenterline[]
  metrics: {
    shaftCount: number
    stationCount: number
    totalShaftLength3d: number
    totalStationAccessLength3d: number
    planningSeconds: number
  } | null
}

/** derived/capability_graph.json (Phase 20C.2B, rule 185): capability
 * semantics over MineNetwork ids — no geometry, no topology of its own.
 * Capability ≠ capacity. */
export interface CapabilityGraphPayload {
  status: 'SUCCESS' | 'FAILED'
  failureReason: string | null
  sourceRevision: string
  networkRevision: string
  networkSourceRevision: string
  capabilities: Capability[]
  nodes: {
    nodeId: string
    nodeType: string
    supports: Capability[]
    source: string
    surface: boolean
    levelId: string | null
  }[]
  edges: {
    edgeId: string
    edgeType: string
    capabilities: Capability[]
    restrictions: Capability[]
    source: string
    shaftId: string | null
  }[]
  surfaceNodeIds: string[]
  requiredPaths: {
    id: string
    capability: Capability
    sourceNodeId: string
    targetNodeId: string
    rule: string
    physicalReachable: boolean
    capabilityReachable: boolean
    pathEdgeIds: string[] | null
    satisfied: boolean
  }[]
  egressAdvisory: {
    capability: 'EMERGENCY_EGRESS'
    criterion: string
    requiredRoutes: number
    advisoryOnly: boolean
    surfaceNodeIds: string[]
    perNode: {
      nodeId: string
      levelId: string | null
      independentEgressRoutes: number
      meetsCriterion: boolean
    }[]
  } | null
  validation: {
    referencedNodesExist: boolean
    referencedEdgesExist: boolean
    noDuplicateNodeIds: boolean
    noDuplicateEdgeIds: boolean
    networkRevisionMatches: boolean
    requiredPathsSatisfied: boolean
    valid: boolean
    failureReason: string | null
  } | null
  metrics: {
    nodeCount: number
    edgeCount: number
    surfaceNodeCount: number
    edgesPerCapability: Record<string, number>
    requiredPathCount: number
    requiredPathsSatisfiedCount: number
    buildSeconds: number
  } | null
}

export interface CapabilityPathQuery {
  sourceNodeId: string
  targetNodeId: string
  capability: Capability
  physicalReachable: boolean
  capabilityReachable: boolean
  pathNodeIds: string[]
  pathEdgeIds: string[]
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
  /** the basis the selected candidate's accesses were actually validated
   *  under (stage-4 REFINED_CONSERVATIVE when refinement applied), with its
   *  bound / refinement diagnostic (Phase 20B.1-v2 1.1) */
  clearanceBasis: ClearanceBasis
  clearanceErrorBound?: number | null
  clearanceRefinement?: Record<string, unknown> | null
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

/** Phase 20B.1 C-3: an implicit body's basis is never EXACT — the stage 2–3
 *  lattice is COARSE_CONSERVATIVE and a stage-4 locally refined window is
 *  REFINED_CONSERVATIVE (same 1.5 × ‖spacing‖ bound on a smaller spacing) */
export type ClearanceBasis = 'EXACT' | 'COARSE_CONSERVATIVE' | 'REFINED_CONSERVATIVE'

export interface LayoutClearanceReport {
  clearanceBasis: ClearanceBasis
  requiredClearance: number
  conservativeMinimumClearance: number
  approximateMinimumClearance: number | null
  clearanceErrorBound: number | null
  satisfied: boolean
  refinement?: Record<string, unknown> | null
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
  /** Phase 20C.1-Q geometric access screen (stage-3 ordering prefix, never a
   * rejection): levels no stage-4 junction candidate can serve */
  accessScreen?: {
    blockedLevelIds: string[]
    blockedCount: number
    /** closeout B: what a blocked level PROVES, decided by the clearance
     * policy — a necessary condition of stage 4 only under EXACT */
    authority?: 'NECESSARY_CONDITION' | 'HEURISTIC'
    levels: Record<string, { blocked: boolean; reason: string | null }>
  } | null
  /** shipped only by GET …/design/layout-v2 for shortlisted candidates */
  centerline?: { points: number[]; pointCount: number } | null
}

/**
 * Why a REQUIRED level is not serviceable (rule 141, hardening H0 §3.1):
 * the level plane misses the solid, or — TABULAR — its footwall contact lies
 * beyond the slab's dip extent (ore above the level, none next to it).
 * Backend-decided; the frontend only echoes it.
 */
export type LevelExclusionReason =
  'NO_FOOTWALL_CONTACT_AT_LEVEL' | 'NO_OREBODY_SECTION_AT_LEVEL' | 'NO_LEVEL_ENTRY'

export interface LayoutRequiredLevel {
  levelId: string
  index: number
  elevation: number
  /** the level plane cuts the solid (a level without footwall contact still has ore above it) */
  hasOrebodySection: boolean
  /** absent on pre-hardening catalogues (then: serviceable ⇔ hasOrebodySection) */
  serviceable?: boolean
  exclusionReason?: LevelExclusionReason | null
  /** TABULAR: down-dip metres the footwall contact lies beyond the slab's up-dip edge */
  overshootM?: number | null
  /** TABULAR hint: thickness·cos(dip) — the top margin that gives every level a contact */
  minimumTopMiningMarginM?: number | null
}

export interface LayoutV2Catalogue {
  layoutVersion: number
  status: 'SUCCESS' | 'NO_FEASIBLE_CANDIDATE'
  portal: [number, number, number]
  portalGenerated: boolean
  requiredLevels: LayoutRequiredLevel[]
  serviceableLevelCount: number
  candidateCount: number
  feasibleCount: number
  shortlist: string[]
  ranking: string[]
  winnerId: string | null
  clearanceBasis: ClearanceBasis
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

// --------------------------------------------------------------------------- //
// Phase 20D.3 — design assessment read model (rule 189; display-only mirror
// of GET …/design/assessment: nothing here is computed on the client)
// --------------------------------------------------------------------------- //

export type AssessmentStatus = 'SATISFIED' | 'NOT_SATISFIED' | 'NOT_APPLICABLE' | 'NOT_EVALUATED'
export type AssessmentAuthority =
  'HARD_DESIGN_RULE' | 'DERIVED_VALIDATION' | 'ADVISORY' | 'INFORMATIONAL'
export type AssessmentEvidenceValue = number | boolean | string | string[] | null
/** what a check describes: the ACTIVE design, or a dormant layout-v2
 * selection under a LEGACY source (never conflated) */
export type AssessmentScope = 'ACTIVE_DESIGN' | 'INACTIVE_LAYOUT_V2'
export type LayoutScope = 'ACTIVE_DESIGN' | 'INACTIVE_LAYOUT_V2' | 'NONE'

export interface AssessmentCheck {
  id: string
  title: string
  category: 'LAYOUT' | 'ACCESS' | 'CLEARANCE' | 'GEOMETRY' | 'CAPABILITY' | 'EGRESS'
  status: AssessmentStatus
  authority: AssessmentAuthority
  scope: AssessmentScope
  summary: string
  evidence: Record<string, AssessmentEvidenceValue>
  sourceArtifact: string
  sourceField: string
}

export interface ComparisonScores {
  development: number
  geology: number
  geometry: number
  total: number
}

export interface ScoreDeltas {
  totalScoreDeltaFromWinner: number
  developmentScoreDelta: number
  geologyScoreDelta: number
  geometryScoreDelta: number
}

export interface CandidateComparisonRow {
  candidateId: string
  family: RampFamily
  rank: number | null
  selected: boolean
  winner: boolean
  status: LayoutCandidateStatus
  stageReached: string
  scores: ComparisonScores | null
  deltas: ScoreDeltas | null
  accessibleLevels: number | null
  requiredLevels: number
  clearance: {
    clearanceBasis: ClearanceBasis
    requiredClearance: number
    conservativeMinimumClearance: number
    clearanceErrorBound: number | null
    satisfied: boolean
  } | null
  access: {
    levelCount: number
    accessibleLevelCount: number
    totalAccessLength: number
    worstAccessLength: number
    maxAccessGradient: number
    minAccessPlanRadius: number | null
  } | null
  failureReasons: string[]
  failureDetail: string | null
}

export interface RequiredPathProjection {
  id: string
  capability: Capability
  sourceNodeId: string
  targetNodeId: string
  rule: string
  physicalReachable: boolean
  capabilityReachable: boolean
  satisfied: boolean
}

export interface EgressAdvisoryProjection {
  criterion: string
  requiredRoutes: number
  advisoryOnly: boolean
  surfaceNodeIds: string[]
  undergroundNodeCount: number
  meetingNodeCount: number
  failingNodeCount: number
  failingNodeIds: string[]
  minimumIndependentRoutes: number | null
}

export interface DesignAssessmentSources {
  activeSource: RampSource
  layoutV2Revision: string | null
  selectedLayoutRevision: string | null
  levelAccessesRevision: string | null
  networkRevision: string | null
  capabilityGraphRevision: string | null
}

export interface DesignAssessmentPayload {
  /** generation status of the read model, never a design verdict */
  status: 'SUCCESS'
  activeSource: RampSource
  layoutScope: LayoutScope
  /** the layout-v2 candidate that IS the active ramp (LAYOUT_V2 only) */
  activeDesignCandidateId: string | null
  winnerId: string | null
  selectedCandidateId: string | null
  selectedCandidate: CandidateComparisonRow | null
  checks: AssessmentCheck[]
  /** winner + top FEASIBLE alternatives in the authoritative ranking order */
  candidateComparison: CandidateComparisonRow[]
  requiredPaths: RequiredPathProjection[]
  egressAdvisory: EgressAdvisoryProjection | null
  summary: string
  sources: DesignAssessmentSources
}

export interface NetworkNode {
  id: string
  type:
    | 'PORTAL'
    | 'LEVEL_ENTRY'
    | 'JUNCTION'
    | 'STOPE_ACCESS'
    | 'RAMP_JUNCTION'
    | 'RAMP_END'
    | 'SHAFT_COLLAR'
    | 'SHAFT_STATION'
    | 'SHAFT_BOTTOM'
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
  targetKind: 'DEVELOPMENT' | ProductionTargetKind
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
  /** Phase 20C.1-V (rule 174): the network node the excavation starts from
   * and the direction of progress along the point order (+1: fraction 0 is
   * the start, progress p reveals [0, p]; −1: the LAST point is the start,
   * progress reveals [1 − p, 1]). Optional for pre-20C.1 artifacts (+1). */
  excavationStartNode?: string
  progressDirection?: 1 | -1
}

export interface StopeTimeline {
  stopeId: string
  initialState: ObjectStateId
  transitions: StateTransition[]
}

/** Phase 21B/C: the production target kind of the ACTIVE method's units. */
export type ProductionTargetKind = 'STOPE' | 'CUT' | 'ROOM_EXTRACTION'

/** One non-Longhole production unit's temporal state machine (a cut or a
 * room extraction unit); geometry stays in the production artifact. */
export interface ProductionUnitTimeline {
  unitId: string
  initialState: ObjectStateId
  transitions: StateTransition[]
}

/** Phase 21B/C generic production block — present only for a non-Longhole
 * method; the Longhole payload keeps `stopes` unchanged. */
export interface ProductionTimeline {
  method: string
  targetKind: ProductionTargetKind
  units: ProductionUnitTimeline[]
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
  /** Phase 21B/C (non-Longhole methods only; absent for Longhole) */
  productionTaskCount?: number
  productionObjectCount?: number
  productionTargetKind?: ProductionTargetKind
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
  /** Phase 21B/C generic production block (absent for Longhole) */
  production?: ProductionTimeline | null
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
  /** the Longhole payload; reserved methods persist this shape as their
   * typed FAILED boundary (never a substitute geometry) */
  method: 'LONGHOLE_OPEN_STOPING' | 'SUBLEVEL_CAVING' | 'SHRINKAGE_STOPING'
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

// --------------------------------------------------------------------------- //
// Phase 21B/C — Cut & Fill / Room & Pillar production payloads. ONE active
// production artifact per scenario (`derived/stopes.json`, legacy path),
// typed by `method`. Geometry is backend world-space vertices assembled
// verbatim (rule 80); the frontend performs no production engineering.
// --------------------------------------------------------------------------- //

export interface LocalBounds {
  uMin: number
  uMax: number
  vMin: number
  vMax: number
  wMin: number
  wMax: number
}

export interface SolidGeometry {
  vertices: number[]
  triangleIndices: number[]
}

export interface ProductionReport {
  hardInvalidSamples: number
  meshClosedSolid: boolean
  meshVolumeM3: number
  volumeAgreement: boolean
  finite: boolean
  valid: boolean
  failureReason: string | null
}

export interface CutFillLift {
  liftIndex: number
  lowerLevelId: string
  upperLevelId: string
  vMin: number
  vMax: number
  verticalHeight: number
  cutIds: string[]
}

export interface CutFillCut {
  id: string
  method: 'CUT_AND_FILL'
  liftIndex: number
  cutIndex: number
  lowerLevelId: string
  upperLevelId: string
  accessDevelopmentId: string
  localBounds: LocalBounds
  geometry: SolidGeometry
  strikeLength: number
  downDipSpan: number
  verticalHeight: number
  thickness: number
  geometricVolumeM3: number
  tonnes: number
  meanGradeProxy: number | null
  plannedState: 'PLANNED'
  report: ProductionReport
}

export interface CutFillBackfill {
  id: string
  sourceCutId: string
  volumeM3: number
}

export interface CutFillMetrics {
  cutCount: number
  backfillCount: number
  liftCount: number
  levelIntervalCount: number
  totalGeometricVolumeM3: number
  totalTonnes: number
  geometricExtractionFractionOfOrebody: number
  weightedMeanGradeProxy: number | null
  actualMeanLiftHeight: number
  actualMeanCutLength: number
}

export interface CutFillPayload {
  status: 'SUCCESS' | 'FAILED'
  failureReason: string | null
  sourceRevision: string
  method: 'CUT_AND_FILL'
  lifts: CutFillLift[]
  cuts: CutFillCut[]
  backfills: CutFillBackfill[]
  metrics: CutFillMetrics | null
}

export interface RoomCell {
  id: string
  rowIndex: number
  columnIndex: number
  localPlanBounds: { uMin: number; uMax: number; vMin: number; vMax: number }
  accessDevelopmentId: string
  extractionUnitIds: string[]
}

export type ExtractionStage = 'HEADING' | 'BENCH_1' | 'BENCH_2'

export interface RoomExtractionUnit {
  id: string
  roomId: string
  stage: ExtractionStage
  benchIndex: number
  localBounds: LocalBounds
  geometry: SolidGeometry
  geometricVolumeM3: number
  tonnes: number
  meanGradeProxy: number | null
  plannedState: 'PLANNED'
  report: ProductionReport
}

export interface Pillar {
  id: string
  rowIndex: number
  columnIndex: number
  localBounds: LocalBounds
  geometry: SolidGeometry
  geometricVolumeM3: number
  tonnesEquivalent: number
  meanGradeProxy: number | null
  report: ProductionReport
}

export interface RoomPillarMetrics {
  roomCount: number
  extractionUnitCount: number
  pillarCount: number
  headingCount: number
  benchCount: number
  totalMinedVolumeM3: number
  totalPillarVolumeM3: number
  panelVolumeM3: number
  totalMinedTonnes: number
  geometricExtractionFraction: number
  weightedMeanGradeProxy: number | null
}

export interface RoomPillarPayload {
  status: 'SUCCESS' | 'FAILED'
  failureReason: string | null
  sourceRevision: string
  method: 'ROOM_AND_PILLAR'
  rooms: RoomCell[]
  extractionUnits: RoomExtractionUnit[]
  pillars: Pillar[]
  metrics: RoomPillarMetrics | null
}

/** The ACTIVE production payload, discriminated by `method`. `StopesPayload`
 * is the Longhole payload AND the typed FAILED boundary of reserved methods. */
export type ProductionPayload = StopesPayload | CutFillPayload | RoomPillarPayload

export type ProductionKind = 'STOPES' | 'CUT_FILL' | 'ROOM_PILLAR'

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
  /**
   * Phase 20C.2A: which backbone geometry contract developed the levels —
   * the exact TABULAR strike line, or the curved section-trace backbone of
   * an implicit orebody. Absent on pre-20C.2A artifacts.
   */
  developmentGeometry?: 'TABULAR_RULE_43' | 'SECTION_FOOTWALL_OFFSET_TRACE' | null
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
  /**
   * Hardening H0 §3.1: every REQUIRED level without a development, with its
   * typed reason, and the production intervals that go with it (absent on
   * pre-hardening artifacts; empty when every level is developed).
   */
  excludedLevels?: ExcludedLevel[]
  unservedIntervals?: UnservedInterval[]
}

export interface ExcludedLevel {
  levelId: string
  index: number
  elevation: number
  reason: LevelExclusionReason
  overshootM: number | null
  minimumTopMiningMarginM: number | null
}

/** an adjacent required-level pair with no production between them (rules 76 / 195) */
export interface UnservedInterval {
  upperLevelId: string
  lowerLevelId: string
  upperElevation: number
  lowerElevation: number
  reason: LevelExclusionReason
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
  type: 'RAMP' | 'LEVEL_ACCESS' | 'DRIFT' | 'CROSSCUT' | 'RAISE' | 'SHAFT' | 'SHAFT_STATION_ACCESS'
  fromNode: string
  toNode: string
  length3d: number
  /** null for a VERTICAL (shaft axis) edge — no horizontal length (Phase 20C.2B) */
  meanGradientSigned: number | null
  maxAbsGradient: number | null
  orientation?: 'DEVELOPMENT' | 'VERTICAL'
  verticalDrop?: number | null
  crossSection: {
    width: number
    height: number
    analyticArea: number
    shape?: 'HORSESHOE' | 'CIRCULAR'
  }
  effectiveSource: EffectiveSource | 'ANALYTIC'
  fieldCost: number
  geometryRef: { artifact: string; segmentIndex: number }
  simulation: SimulationSlots
}

export interface NetworkMetrics {
  rampJunctionCount?: number
  levelAccessEdgeCount?: number
  totalLevelAccessLength3d?: number
  /** Phase 20C.2B shaft counters (zero without a shaft) */
  shaftCount?: number
  shaftStationCount?: number
  shaftEdgeCount?: number
  shaftStationAccessEdgeCount?: number
  totalShaftLength3d?: number
  totalShaftStationAccessLength3d?: number
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

export interface TunnelJunctionSummary {
  count: number
  byType: Record<string, number>
  openedEndpointCount: number
  removedTriangles: number
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
  /** closedness of the EMITTED render mesh (false once a typed junction
   * aperture exists — Phase 20D.1) */
  geometricallyClosed?: boolean
  /** weld QA of the sweep before the junction apertures (Phase 20D.1) */
  baseSweepGeometricallyClosed?: boolean
  /** Phase 20D.1 typed junction apertures cut into the ramp tube */
  junctions?: TunnelJunctionSummary
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

/**
 * Phase 21A — read-only mining-method presentation. The backend registry is
 * the single authority for `implementationStatus`; the frontend renders it
 * and never maps a method to a status or offers a method selector.
 */
export interface MiningMethodSummary {
  method: string
  displayName: string
  implementationStatus: 'IMPLEMENTED' | 'UNSUPPORTED_METHOD'
  sublevelInterval: number
  stopeLength: number
  minimumPillar: number
  /** Phase 21B/C: the persisted method-specific parameters (null for Longhole
   * and reserved methods) */
  methodParameters: MethodParameters | null
  /** the production semantics kind of the ACTIVE method — null for a method
   * the registry does not implement (no production geometry exists for it) */
  productionKind: ProductionKind | null
  /** the registry's whole method table with canonical default parameters —
   * the ONLY source of selector options, statuses and defaults (rule 124) */
  availableMethods: AvailableMethod[]
}

export interface AvailableMethod {
  method: MiningMethodType
  displayName: string
  implementationStatus: 'IMPLEMENTED' | 'UNSUPPORTED_METHOD'
  /** null for a reserved (not implemented) method */
  productionKind: ProductionKind | null
  defaultParameters: MethodParameters | null
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
  /** Phase 21A read-only method card data (registry authority, rule 192) */
  miningMethod: MiningMethodSummary
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
  /** Phase 20C.2B optional shaft infrastructure (levels → shafts → network) */
  shafts?: ShaftsPayload | null
  network: NetworkPayload | null
  /** Phase 20C.2B capability semantics over the network (network → capability) */
  capabilityGraph?: CapabilityGraphPayload | null
  /** the ACTIVE production artifact (`derived/stopes.json`), typed by method */
  stopes: ProductionPayload | null
  timeline: TimelinePayload | null
  communication: CommunicationPayload | null
  sensors: SensorPayload | null
}
