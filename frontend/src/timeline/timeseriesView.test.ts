import { describe, expect, it } from 'vitest'
import type { TimeseriesBucket, TimeseriesPayload, TimeseriesQuantities } from '@/types/analysis'
import { bucketAtDay, chartRows, cumulativeAtDay, seriesHasValues } from './timeseriesView'

function q(n: number, money: boolean): TimeseriesQuantities {
  return {
    developmentLengthM: n,
    developmentExcavationM3: n * 20,
    developmentTonnes: null,
    productionTonnes: n * 100,
    backfillM3: 0,
    cementedBackfillM3: 0,
    cost: money ? n * 5 : null,
    revenue: money ? n * 7 : null,
    netCashflow: money ? n * 2 : null,
  }
}

function payload(money: boolean): TimeseriesPayload {
  const buckets: TimeseriesBucket[] = [0, 1, 2].map((i) => ({
    index: i,
    startDay: i * 30,
    endDay: (i + 1) * 30,
    bucket: q(1, money),
    cumulative: q(i + 1, money),
    cumulativeCashflow: money ? (i + 1) * 2 : null,
  }))
  return {
    status: 'SUCCESS',
    sources: {
      scenarioRevision: 's',
      networkRevision: 'n',
      productionRevision: 'p',
      timelineRevision: 't',
      economicsRevision: money ? 'e' : null,
    },
    availability: 'AVAILABLE',
    reason: null,
    bucketDays: 30,
    bucketCount: 3,
    startDay: 0,
    endDay: 90,
    developmentTonnes: { status: 'NOT_CONFIGURED', hostRockDensity: null, reason: 'no density' },
    retained: {
      availability: 'AVAILABLE',
      reason: null,
      pillarCount: 0,
      pillarVolumeM3: 0,
      pillarTonnesEquivalent: 0,
    },
    economics: {
      availability: money ? 'AVAILABLE' : 'NOT_CONFIGURED',
      reason: money ? null : 'Planning economics is not configured.',
      currencyCode: money ? 'USD' : null,
      economicsRevision: money ? 'e' : null,
    },
    totals: q(3, money),
    buckets,
    developmentRockVocabulary: 'Excavated development rock',
    allocation: 'LINEAR_OVER_TASK_WINDOW',
    disclaimer: 'Synthetic planning economics.',
  }
}

describe('time-series view helpers (PR-2 H3 §7)', () => {
  it('finds the bucket containing a day, the last bucket at or after the end', () => {
    const p = payload(true)
    expect(bucketAtDay(p, 0)?.index).toBe(0)
    expect(bucketAtDay(p, 29.99)?.index).toBe(0)
    expect(bucketAtDay(p, 30)?.index).toBe(1)
    expect(bucketAtDay(p, 89.9)?.index).toBe(2)
    expect(bucketAtDay(p, 90)?.index).toBe(2)
    expect(bucketAtDay(p, 500)?.index).toBe(2)
    expect(bucketAtDay(p, -1)).toBeNull()
    expect(bucketAtDay({ ...p, buckets: [] }, 10)).toBeNull()
  })
  it('reports the cumulative of the last COMPLETE bucket (conservative) and zero before it', () => {
    const p = payload(true)
    expect(cumulativeAtDay(p, 10)?.developmentLengthM).toBe(0)
    expect(cumulativeAtDay(p, 10)?.cost).toBe(0)
    expect(cumulativeAtDay(p, 30)?.developmentLengthM).toBe(1) // bucket 0 complete at day 30
    expect(cumulativeAtDay(p, 59.9)?.developmentLengthM).toBe(1)
    expect(cumulativeAtDay(p, 60)?.developmentLengthM).toBe(2)
    expect(cumulativeAtDay(p, 1e6)?.developmentLengthM).toBe(3)
  })
  it('never converts a missing money cell to zero', () => {
    const p = payload(false)
    expect(cumulativeAtDay(p, 10)?.cost).toBeNull()
    expect(cumulativeAtDay(p, 45)?.revenue).toBeNull()
    const rows = chartRows(p)
    expect(rows).toHaveLength(3)
    expect(rows.every((r) => r.cost === null && r.cumulativeCashflow === null)).toBe(true)
    expect(seriesHasValues(rows, 'cost')).toBe(false)
    expect(seriesHasValues(rows, 'productionTonnes')).toBe(true)
    expect(seriesHasValues(chartRows(payload(true)), 'cumulativeCashflow')).toBe(true)
  })
  it('chart rows are indexed at the bucket END day, one per bucket', () => {
    expect(chartRows(payload(true)).map((r) => r.day)).toEqual([30, 60, 90])
  })
})
