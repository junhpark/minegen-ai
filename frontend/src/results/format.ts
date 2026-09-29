/**
 * Phase 23C — display vocabulary of the Simulation Results workspace. Pure
 * formatting: no request, no engineering, no simulation quantity.
 */
import type {
  OperationsEdgeMetric,
  ResultCompatibility,
  ResultSummary,
  TimeAxisKind,
  VentilationMetric,
} from '@/types/results'

export const STALE_TEXT = 'STALE — this result was generated from an older mine snapshot'

export const COMPATIBILITY_LABEL: Record<ResultCompatibility, string> = {
  COMPATIBLE: 'Compatible',
  STALE: 'Stale',
}

export const VENTILATION_METRIC_LABEL: Record<VentilationMetric, string> = {
  airflowM3s: 'Airflow',
  velocityMs: 'Air velocity',
  pressurePa: 'Pressure',
  pressureLossPa: 'Pressure loss',
  temperatureDryC: 'Dry-bulb temperature',
  temperatureWetC: 'Wet-bulb temperature',
  airDensityKgM3: 'Air density',
}

export const VENTILATION_METRIC_UNIT: Record<VentilationMetric, string> = {
  airflowM3s: 'm3/s',
  velocityMs: 'm/s',
  pressurePa: 'Pa',
  pressureLossPa: 'Pa',
  temperatureDryC: 'degC',
  temperatureWetC: 'degC',
  airDensityKgM3: 'kg/m3',
}

export const OPERATIONS_METRIC_LABEL: Record<OperationsEdgeMetric, string> = {
  utilization: 'Utilization',
  queueCount: 'Queue count',
  haulageTonnesPerHour: 'Haulage rate',
  travelTimeSeconds: 'Travel time',
}

export const OPERATIONS_METRIC_UNIT: Record<OperationsEdgeMetric, string> = {
  utilization: 'fraction',
  queueCount: 'count',
  haulageTonnesPerHour: 't/h',
  travelTimeSeconds: 's',
}

export const APPLICATION_LABEL: Record<string, string> = {
  VENTSIM: 'Ventsim',
  ANYLOGIC: 'AnyLogic',
}

export const DOMAIN_LABEL: Record<string, string> = {
  VENTILATION: 'Ventilation',
  OPERATIONS: 'Operations',
}

/** The result clock readout: MINE_DAY reads "Mine day 123.4", seconds read
 * "t = 123 s", a STATIC result has no clock. */
export function formatResultTime(kind: TimeAxisKind, t: number | null): string {
  if (kind === 'STATIC' || t === null) return 'static (no time axis)'
  if (kind === 'MINE_DAY') return `Mine day ${t.toFixed(1)}`
  return `t = ${t.toFixed(0)} s`
}

export function timeAxisLabel(kind: TimeAxisKind): string {
  if (kind === 'STATIC') return 'Static'
  if (kind === 'MINE_DAY') return 'Mine day'
  return 'Elapsed seconds'
}

export function fmtValue(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—'
  return Math.abs(v) >= 1000 ? v.toFixed(0) : v.toFixed(digits)
}

export function resultTitle(r: ResultSummary): string {
  const label = r.runLabel.trim()
  return label ? label : `${APPLICATION_LABEL[r.sourceApplication] ?? r.sourceApplication} result`
}

export function snapshotShort(r: ResultSummary): string {
  return `${r.sourceSnapshot.scenarioRevision.slice(0, 8)} · ${r.sourceSnapshot.activeRampSource}`
}
