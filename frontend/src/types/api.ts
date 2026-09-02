// Wire types mirroring backend/src/minegen/core/models.py (camelCase).
// Coordinates are ENU Z-up meters. Never store Three.js coordinates in these.

import type { AssetType } from '@/types/enums'
import type { MiningMethodType, OrebodyType } from './enums'

export interface Point3D {
  x: number
  y: number
  z: number
}

export interface WorldConfig {
  sizeX: number
  sizeY: number
  /** model depth below TerrainConfig.baseElevation (rule 35) */
  depth: number
}

export interface TerrainConfig {
  gridSpacing: number
  baseElevation: number
  relief: number
  octaves: number
}

export interface OrebodyConfig {
  orebodyType: OrebodyType
  center: Point3D
  strikeDeg: number
  dipDeg: number
  length: number
  /** down-dip length, not vertical extent */
  height: number
  thickness: number
  meanGrade: number
  gradeVariability: number
  gradeCorrelationLengthXy: number
  gradeCorrelationLengthZ: number
  density: number
}

/** Widths are perpendicular half-widths measured from the fault plane (rule 36). */
export interface FaultConfig {
  origin: Point3D
  strikeDeg: number
  dipDeg: number
  coreHalfWidth: number
  influenceHalfWidth: number
  corePenalty: number
  damageZonePenalty: number
}

export interface RockQualityConfig {
  mean: number
  std: number
  correlationLengthXy: number
  correlationLengthZ: number
  minimum: number
  maximum: number
}

export interface GeologyConfig {
  rockQuality: RockQualityConfig
  faults: FaultConfig[]
}

/**
 * NUMERICAL sampling resolution of the synthetic spatial fields (Phase 18,
 * rule 127). Sampling support only — never a block size, SMU or mining unit.
 */
export interface FieldSamplingConfig {
  spacingX: number
  spacingY: number
  spacingZ: number
}

export interface RampConstraints {
  /** vertical / horizontal, 0.12 = 12 % */
  maxGradient: number
  minTurnRadius: number
  tunnelWidth: number
  tunnelHeight: number
  clearance: number
  footwallAccessOffset: number
  levelDriftGradient: number
}

export interface TunnelProfile {
  width: number
  wallHeight: number
  crownRadius: number
}

export interface RestrictedZone {
  name: string
  min: Point3D
  max: Point3D
}

export interface DesignConfig {
  baseCostPerM: number
  rockPenaltyWeight: number
  orebodyExclusionBuffer: number
  orebodySterilizationWeight: number
  orebodySterilizationRange: number
  minimumSurfaceCover: number
  restrictedZones: RestrictedZone[]
  topMiningMargin: number
  bottomMiningMargin: number
  candidateCount: number
  candidateAlongStrikeSpan: number
  portalFootwallDistance: number
}

export interface MiningConfig {
  method: MiningMethodType
  sublevelInterval: number
  stopeLength: number
  minimumPillar: number
}

/** Phase 10 temporal planning parameters (rules 81–86): transparent
 * synthetic baseline rates/durations — not calibrated productivity claims. */
export interface ScheduleConfig {
  rampAdvanceMPerDay: number
  driftAdvanceMPerDay: number
  crosscutAdvanceMPerDay: number
  stopePreparationDays: number
  stopingTonnesPerDay: number
  muckingTonnesPerDay: number
  backfillM3PerDay: number
  backfillCureDays: number
}

/** Phase 11 communication planning parameters (rules 87–92): SYNTHETIC
 * planning/demo assumptions — network-geodesic ranges, not RF parameters. */
export interface CommunicationConfig {
  assetType: AssetType
  candidateSpacingM: number
  demandSpacingM: number
  coverageRangeM: number
  backhaulRangeM: number
  requiredCoverageFraction: number
}

/** Phase 12 sensor placement parameters (rules 93–98): SYNTHETIC planning
 * assumptions — monitoringRangeM is a network-geodesic layout proxy, not a
 * detection range or gas model. */
export interface SensorConfig {
  assetType: AssetType
  candidateSpacingM: number
  demandSpacingM: number
  monitoringRangeM: number
  requiredCoverageFraction: number
}

export interface InfrastructureConfig {
  communication: CommunicationConfig
  sensors: SensorConfig
}

/** Phase 17 scenario-realization presets (backend ScenarioPreset). */
export type ScenarioPreset = 'BASELINE' | 'RANDOM_TABULAR' | 'RANDOM_ELLIPSOID'
export const SCENARIO_PRESETS: readonly ScenarioPreset[] = [
  'BASELINE',
  'RANDOM_TABULAR',
  'RANDOM_ELLIPSOID',
]

/** Body of the non-persistent POST /scenarios/realize. */
export interface ScenarioRealizeRequest {
  preset: ScenarioPreset
  seed: number
  faultCount?: number | null
}

export interface ScenarioCreate {
  name: string
  seed: number
  world: WorldConfig
  terrain: TerrainConfig
  orebody: OrebodyConfig
  geology: GeologyConfig
  fieldSampling: FieldSamplingConfig
  portal: Point3D | null
  ramp: RampConstraints
  design: DesignConfig
  tunnelProfile: TunnelProfile
  mining: MiningConfig
  schedule: ScheduleConfig
  infrastructure: InfrastructureConfig
}

export interface Scenario extends ScenarioCreate {
  id: string
  schemaVersion: number
}

export interface ScenarioSummary {
  id: string
  name: string
  seed: number
}

export interface HealthResponse {
  status: string
  app: string
  version: string
  coordinateSystem: string
}

export interface ApiErrorDetail {
  code: string
  message: string
}
