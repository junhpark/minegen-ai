import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { TimeseriesPayload } from '@/types/analysis'
import { FourDResultsBody } from './FourDResults'

function payload(money: boolean): TimeseriesPayload {
  const q = (n: number) => ({
    developmentLengthM: n * 10,
    developmentExcavationM3: n * 200,
    developmentTonnes: null,
    productionTonnes: n * 1000,
    backfillM3: n * 50,
    cementedBackfillM3: n * 5,
    cost: money ? n * 500 : null,
    revenue: money ? n * 800 : null,
    netCashflow: money ? n * 300 : null,
  })
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
    bucketCount: 2,
    startDay: 0,
    endDay: 60,
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
    totals: q(2),
    buckets: [0, 1].map((i) => ({
      index: i,
      startDay: i * 30,
      endDay: (i + 1) * 30,
      bucket: q(1),
      cumulative: q(i + 1),
      cumulativeCashflow: money ? (i + 1) * 300 : null,
    })),
    developmentRockVocabulary: 'Excavated development rock',
    allocation: 'LINEAR_OVER_TASK_WINDOW',
    disclaimer: 'Synthetic planning economics. Not a resource/reserve estimate or feasibility study.',
  }
}

const render = (p: TimeseriesPayload | null, day: number, error: string | null = null) =>
  renderToStaticMarkup(<FourDResultsBody payload={p} currentDay={day} loading={false} error={error} />)

describe('4D results card (PR-2 H3 §7)', () => {
  it('shows the current day and the backend cumulative quantities as of the last complete bucket', () => {
    const html = render(payload(true), 45)
    expect(html).toContain('Current day')
    expect(html).toContain('>45<')
    // bucket 0 is complete at day 45 → cumulative n = 1
    expect(html).toContain('10 m')
    expect(html).toContain('Excavated development rock'.toLowerCase())
    expect(html).toContain('cemented')
    expect(html).not.toContain('waste')
    // four charts: development, production, cost/revenue, net/cumulative
    expect(html.match(/data-testid="fourd-chart"/g)).toHaveLength(4)
    expect(html).toContain(payload(true).disclaimer)
  })
  it('never shows a missing money value as zero: NOT_CONFIGURED readout, no money charts', () => {
    const html = render(payload(false), 45)
    expect(html).toContain('NOT_CONFIGURED (no host-rock density)')
    expect(html).toContain('Net cashflow')
    expect(html).toContain('>NOT_CONFIGURED<')
    expect(html.match(/data-testid="fourd-chart"/g)).toHaveLength(2)
    expect(html).toContain('need planning economics')
  })
  it('renders a typed error and a NOT_AVAILABLE reason verbatim', () => {
    expect(render(null, 0, 'READ_SNAPSHOT_CHANGED: moved')).toContain('READ_SNAPSHOT_CHANGED: moved')
    const partial = { ...payload(true), availability: 'NOT_AVAILABLE' as const, reason: 'requires schedule' }
    expect(render(partial, 0)).toContain('requires schedule')
  })
})
