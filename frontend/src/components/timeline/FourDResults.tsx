import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api, ApiError } from '@/api/client'
import { cubic, fmt0, fmt1, money, tonnes } from '@/components/panels/analysisFormat'
import { Metrics } from '@/components/ui/MetricRow'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useTimelineStore } from '@/stores/timelineStore'
import { chartRows, cumulativeAtDay, seriesHasValues, type ChartRow } from '@/timeline/timeseriesView'
import type { TimeseriesPayload } from '@/types/analysis'

/**
 * Hardening PR-2 H3 §7 — the 4D STATUS & RESULTS card: the current day, the
 * cumulative Development / Production / Backfill quantities as of that day
 * and the quantitative charts, ALL from the backend analysis time series
 * (`GET …/analysis/timeseries`). The frontend never re-sums timeline tasks;
 * a `null` backend cell is a gap in the chart and a "—" readout, never zero.
 *
 * Recharts (explicit dependency, PR-2 C5): the hardening plan requires
 * several substantial charts here and in the Analysis workspace, so a
 * maintained charting library replaces the inline SVG primitives.
 */
export function FourDResults() {
  const scene = useScenarioStore((s) => s.scene)
  const epoch = useScenarioStore((s) => s.epoch)
  const currentDay = useTimelineStore((s) => s.currentDay)
  const scenarioId = scene?.scenarioId ?? null
  const timelineRevision = scene?.timeline?.sourceRevision ?? null
  const ready = scene?.timeline?.status === 'SUCCESS'
  const series = useQuery({
    queryKey: ['analysis-timeseries', epoch, scenarioId, timelineRevision],
    queryFn: () => api.getTimeseries(scenarioId ?? ''),
    enabled: scenarioId !== null && ready,
    retry: false,
  })
  const err = series.error
  const errorText =
    err instanceof ApiError ? `${err.code}: ${err.message}` : err instanceof Error ? err.message : null
  return (
    <section
      className="flex flex-col gap-2 border-b border-rock-700 px-4 py-3"
      data-testid="fourd-results"
    >
      <h3 className="plate text-[12px] text-chalk-dim">4D results</h3>
      <FourDResultsBody
        payload={series.data ?? null}
        currentDay={currentDay}
        loading={series.isPending && ready}
        error={errorText}
      />
    </section>
  )
}

export function FourDResultsBody({
  payload,
  currentDay,
  loading,
  error,
}: {
  payload: TimeseriesPayload | null
  currentDay: number
  loading: boolean
  error: string | null
}) {
  const rows = useMemo(() => (payload ? chartRows(payload) : []), [payload])
  const asOf = payload ? cumulativeAtDay(payload, currentDay) : null
  const code = payload?.economics.currencyCode ?? null
  if (error) {
    return (
      <p role="alert" className="text-[11px] text-danger">
        {error}
      </p>
    )
  }
  if (!payload) {
    return <p className="text-[11px] text-mute">{loading ? 'Reading the time series…' : '—'}</p>
  }
  if (payload.availability !== 'AVAILABLE') {
    return <p className="text-[11px] text-mute">{payload.reason}</p>
  }
  return (
    <>
      <Metrics
        rows={[
          { label: 'Current day', value: fmt1(currentDay) },
          {
            label: 'Development',
            value: asOf
              ? `${fmt0(asOf.developmentLengthM)} m · ${cubic(asOf.developmentExcavationM3)} ${payload.developmentRockVocabulary.toLowerCase()}`
              : null,
          },
          {
            label: 'Development tonnes',
            value:
              asOf && asOf.developmentTonnes !== null
                ? tonnes(asOf.developmentTonnes)
                : payload.developmentTonnes.status === 'NOT_CONFIGURED'
                  ? 'NOT_CONFIGURED (no host-rock density)'
                  : null,
          },
          { label: 'Production', value: asOf ? tonnes(asOf.productionTonnes) : null },
          {
            label: 'Backfill',
            value: asOf
              ? asOf.cementedBackfillM3 > 0
                ? `${cubic(asOf.backfillM3)} (${cubic(asOf.cementedBackfillM3)} cemented)`
                : cubic(asOf.backfillM3)
              : null,
          },
          {
            label: 'Net cashflow',
            value:
              asOf && asOf.netCashflow !== null
                ? money(asOf.netCashflow, code)
                : payload.economics.availability === 'NOT_CONFIGURED'
                  ? 'NOT_CONFIGURED'
                  : null,
          },
        ]}
      />
      <p className="text-[10px] text-mute">
        Cumulative at the end of the last complete {fmt0(payload.bucketDays)}-day bucket; backend
        series, linear over each task window.
      </p>
      <Chart title="Development excavation (m³ per bucket)" rows={rows} day={currentDay}>
        <Bar dataKey="developmentExcavationM3" fill="#8f99a3" isAnimationActive={false} />
      </Chart>
      <Chart title="Production (t per bucket)" rows={rows} day={currentDay}>
        <Bar dataKey="productionTonnes" fill="#f2c14e" isAnimationActive={false} />
      </Chart>
      {seriesHasValues(rows, 'cost') ? (
        <>
          <Chart title={`Cost and revenue per bucket (${code ?? ''})`} rows={rows} day={currentDay}>
            <Line
              dataKey="cost"
              stroke="#d9655a"
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
            <Line
              dataKey="revenue"
              stroke="#7fc97f"
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
          </Chart>
          <Chart title={`Net and cumulative cashflow (${code ?? ''})`} rows={rows} day={currentDay}>
            <Line
              dataKey="netCashflow"
              stroke="#e9d8ff"
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
            <Line
              dataKey="cumulativeCashflow"
              stroke="#f2c14e"
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
          </Chart>
        </>
      ) : (
        <p className="text-[10px] text-mute">
          Cost, revenue and cashflow charts need planning economics (Analysis › Economics).
        </p>
      )}
      <p className="text-[10px] text-mute">{payload.disclaimer}</p>
    </>
  )
}

const CHART_WIDTH = 300
const CHART_HEIGHT = 110

function Chart({
  title,
  rows,
  day,
  children,
}: {
  title: string
  rows: ChartRow[]
  day: number
  children: React.ReactNode
}) {
  const bars = Array.isArray(children)
    ? children.some((c) => (c as { type?: unknown }).type === Bar)
    : (children as { type?: unknown }).type === Bar
  const common = {
    width: CHART_WIDTH,
    height: CHART_HEIGHT,
    data: rows,
    margin: { top: 4, right: 8, bottom: 0, left: 0 },
  }
  const axes = (
    <>
      <CartesianGrid stroke="#3a3f46" strokeDasharray="2 4" />
      <XAxis dataKey="day" tick={{ fontSize: 9, fill: '#8f99a3' }} tickLine={false} />
      <YAxis tick={{ fontSize: 9, fill: '#8f99a3' }} tickLine={false} width={44} />
      <Tooltip
        contentStyle={{ background: '#1f2328', border: '1px solid #3a3f46', fontSize: 10 }}
        formatter={(v: unknown) => (typeof v === 'number' ? fmt0(v) : '—')}
      />
      <ReferenceLine x={day} stroke="#f2c14e" strokeDasharray="3 3" ifOverflow="extendDomain" />
    </>
  )
  return (
    <figure className="readout" data-testid="fourd-chart">
      <figcaption className="text-[10px] text-mute">{title}</figcaption>
      {bars ? (
        <BarChart {...common}>
          {axes}
          {children}
        </BarChart>
      ) : (
        <LineChart {...common}>
          {axes}
          {children}
        </LineChart>
      )}
    </figure>
  )
}
