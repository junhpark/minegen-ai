/**
 * Phase 22A/B — display formatting of backend analysis numbers. Pure
 * presentation: rounding for the readout only, never a computation.
 */
import type { Availability, PlanningIrr } from '@/types/analysis'
import type { StatusTone } from '@/components/ui/presentation'

const F0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const F1 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 })
const F2 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 })

export function fmt0(v: number | null | undefined): string {
  return v === null || v === undefined ? '—' : F0.format(v)
}
export function fmt1(v: number | null | undefined): string {
  return v === null || v === undefined ? '—' : F1.format(v)
}
export function fmt2(v: number | null | undefined): string {
  return v === null || v === undefined ? '—' : F2.format(v)
}
export function metres(v: number | null | undefined): string {
  return v === null || v === undefined ? '—' : `${F0.format(v)} m`
}
export function cubic(v: number | null | undefined): string {
  return v === null || v === undefined ? '—' : `${F0.format(v)} m³`
}
export function tonnes(v: number | null | undefined): string {
  return v === null || v === undefined ? '—' : `${F0.format(v)} t`
}
export function days(v: number | null | undefined): string {
  return v === null || v === undefined ? '—' : `${F1.format(v)} d`
}
/** currency readout: `USD 1,234,567` (no conversion, no symbol lookup) */
export function money(v: number | null | undefined, code: string | null): string {
  if (v === null || v === undefined) return '—'
  return `${code ?? ''} ${F0.format(v)}`.trim()
}

/** presentation mapping of a section availability to the shared badge */
export function availabilityTone(a: Availability): StatusTone {
  if (a === 'AVAILABLE') return 'READY'
  if (a === 'NOT_CONFIGURED') return 'INACTIVE'
  return 'NOT_GENERATED'
}

export const AVAILABILITY_LABEL: Record<Availability, string> = {
  AVAILABLE: 'Available',
  NOT_AVAILABLE: 'Not available',
  NOT_CONFIGURED: 'Not configured',
}

export const EDGE_TYPE_LABEL: Record<string, string> = {
  RAMP: 'Ramp',
  LEVEL_ACCESS: 'Level access',
  DRIFT: 'Drift',
  CROSSCUT: 'Crosscut',
  RAISE: 'Raise',
  SHAFT: 'Shaft',
  SHAFT_STATION_ACCESS: 'Shaft station access',
}

export const METHOD_LABEL: Record<string, string> = {
  LONGHOLE_OPEN_STOPING: 'Longhole Open Stoping',
  CUT_AND_FILL: 'Cut & Fill',
  ROOM_AND_PILLAR: 'Room & Pillar',
  SUBLEVEL_CAVING: 'Sublevel Caving',
  SHRINKAGE_STOPING: 'Shrinkage Stoping',
}

/** hardening PR-2 H3 §8.2 — the Planning IRR readout: a percentage when
 * DEFINED, the typed reason otherwise (never NaN, never a blank) */
export function irrText(irr: PlanningIrr | null | undefined): string {
  if (!irr) return '—'
  if (irr.status === 'DEFINED' && irr.annualRate !== null) {
    return `${(irr.annualRate * 100).toFixed(1)} %`
  }
  if (irr.status === 'NOT_DEFINED') return `NOT_DEFINED · ${irr.reason ?? ''}`.trim()
  return 'NOT_CONFIGURED'
}

/** signed currency delta in the layout-comparison convention: `+USD 5,700`,
 * `−USD 5,700`, `±USD 0` — the sign is the backend's, never recomputed */
export function signedMoney(v: number | null | undefined, code: string | null): string {
  if (v === null || v === undefined) return '—'
  const sign = v > 0 ? '+' : v < 0 ? '−' : '±'
  return `${sign}${money(Math.abs(v), code)}`
}
