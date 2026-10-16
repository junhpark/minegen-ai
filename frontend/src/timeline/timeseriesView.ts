/**
 * Hardening PR-2 H3 §7 — view helpers over the BACKEND analysis time series
 * (pure, no React). The series is the authority: nothing here re-sums
 * timeline tasks, and a `null` backend cell stays `null` (never a silent
 * zero) so a chart shows a gap and a readout shows "—".
 */
import type { TimeseriesBucket, TimeseriesPayload, TimeseriesQuantities } from '@/types/analysis'

/** the bucket whose [startDay, endDay) contains `day`; the last bucket for
 * `day >= endDay`, null before the first bucket or without buckets */
export function bucketAtDay(payload: TimeseriesPayload, day: number): TimeseriesBucket | null {
  const buckets = payload.buckets
  if (buckets.length === 0 || !Number.isFinite(day)) return null
  const first = buckets[0]!
  if (day < first.startDay) return null
  const last = buckets[buckets.length - 1]!
  if (day >= last.endDay) return last
  // buckets are chronological and contiguous: index = floor((day − start) / width)
  const index = Math.min(
    buckets.length - 1,
    Math.max(0, Math.floor((day - first.startDay) / payload.bucketDays)),
  )
  const b = buckets[index]!
  return day >= b.startDay && day < b.endDay
    ? b
    : (buckets.find((x) => day >= x.startDay && day < x.endDay) ?? null)
}

/**
 * The cumulative quantities "as of" `day`: the running total at the END of
 * the last bucket that is COMPLETE at `day` (conservative — a partially
 * elapsed bucket is not counted, exactly as a DEVELOPING excavation is cut
 * at its last completed ring). Before the first complete bucket every
 * quantity is zero and every money cell keeps the backend's configured /
 * not-configured meaning.
 */
export function cumulativeAtDay(
  payload: TimeseriesPayload,
  day: number,
): TimeseriesQuantities | null {
  if (payload.buckets.length === 0) return null
  let complete: TimeseriesBucket | null = null
  for (const b of payload.buckets) {
    if (b.endDay <= day) complete = b
    else break
  }
  if (complete) return complete.cumulative
  const probe = payload.buckets[0]!.cumulative
  return {
    developmentLengthM: 0,
    developmentExcavationM3: 0,
    developmentTonnes: probe.developmentTonnes === null ? null : 0,
    productionTonnes: 0,
    backfillM3: 0,
    cementedBackfillM3: 0,
    cost: probe.cost === null ? null : 0,
    revenue: probe.revenue === null ? null : 0,
    netCashflow: probe.netCashflow === null ? null : 0,
  }
}

/** one chart row per bucket; `day` is the bucket END (the value is complete
 * there); nulls are preserved for the money series */
export interface ChartRow {
  day: number
  developmentExcavationM3: number
  productionTonnes: number
  backfillM3: number
  cost: number | null
  revenue: number | null
  netCashflow: number | null
  cumulativeCashflow: number | null
}

export function chartRows(payload: TimeseriesPayload): ChartRow[] {
  return payload.buckets.map((b) => ({
    day: b.endDay,
    developmentExcavationM3: b.bucket.developmentExcavationM3,
    productionTonnes: b.bucket.productionTonnes,
    backfillM3: b.bucket.backfillM3,
    cost: b.bucket.cost,
    revenue: b.bucket.revenue,
    netCashflow: b.bucket.netCashflow,
    cumulativeCashflow: b.cumulativeCashflow,
  }))
}

/** true when at least one row carries a non-null value for `key` — a series
 * with no value at all is not drawn (never flattened to zero) */
export function seriesHasValues(rows: readonly ChartRow[], key: keyof ChartRow): boolean {
  return rows.some((r) => r[key] !== null)
}
