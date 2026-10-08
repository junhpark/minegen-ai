import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { CashflowBucket, EconomicsSummary } from '@/types/analysis'
import { fmt0 } from './analysisFormat'

/**
 * Phase 22B — the Planning Cashflow buckets as the backend emitted them
 * (chronological, one row per bucket). Hardening PR-2 H3 §8.1: the inline
 * SVG bars became two Recharts charts (net + cumulative cashflow per bucket,
 * cost breakdown) — presentation only, every number is the backend's and the
 * cumulative column is never re-summed here.
 */
export function CashflowCharts({
  buckets,
  summary,
  code,
  width = 640,
}: {
  buckets: CashflowBucket[]
  summary: EconomicsSummary | null
  code: string
  width?: number
}) {
  if (buckets.length === 0) return null
  const rows = buckets.map((b) => ({
    day: b.endDay,
    net: b.netCashflow,
    cumulative: b.cumulativeCashflow,
    revenue: b.revenue,
    cost:
      b.developmentCost +
      b.productionMiningCost +
      b.processingCost +
      b.backfillCost +
      b.fixedOperatingCost +
      b.initialCapitalCost,
  }))
  const breakdown = summary
    ? [
        { name: 'Development', value: summary.developmentCost },
        { name: 'Mining', value: summary.productionMiningCost },
        { name: 'Processing', value: summary.processingCost },
        { name: 'Backfill', value: summary.backfillCost },
        { name: 'Fixed opex', value: summary.fixedOperatingCost },
        { name: 'Capital', value: summary.initialCapitalCost },
      ]
    : []
  const tick = { fontSize: 10, fill: '#8f99a3' }
  const tooltip = {
    contentStyle: { background: '#1f2328', border: '1px solid #3a3f46', fontSize: 11 },
    formatter: (v: unknown) => (typeof v === 'number' ? `${fmt0(v)} ${code}` : '—'),
  }
  return (
    <div className="flex flex-col gap-3" data-testid="cashflow-charts">
      <figure>
        <figcaption className="text-[11px] text-mute">
          Planning Cashflow per bucket — net (bars) and cumulative (line), {code}
        </figcaption>
        <ComposedChart width={width} height={220} data={rows} margin={{ top: 8, right: 16 }}>
          <CartesianGrid stroke="#3a3f46" strokeDasharray="2 4" />
          <XAxis dataKey="day" tick={tick} tickLine={false} />
          <YAxis tick={tick} tickLine={false} width={64} />
          <Tooltip {...tooltip} />
          <ReferenceLine y={0} stroke="#8f99a3" />
          <Bar dataKey="net" fill="#f2c14e" isAnimationActive={false} />
          <Line dataKey="cumulative" stroke="#e9d8ff" dot={false} isAnimationActive={false} />
        </ComposedChart>
      </figure>
      <figure>
        <figcaption className="text-[11px] text-mute">Cost and revenue per bucket, {code}</figcaption>
        <ComposedChart width={width} height={160} data={rows} margin={{ top: 8, right: 16 }}>
          <CartesianGrid stroke="#3a3f46" strokeDasharray="2 4" />
          <XAxis dataKey="day" tick={tick} tickLine={false} />
          <YAxis tick={tick} tickLine={false} width={64} />
          <Tooltip {...tooltip} />
          <Line dataKey="cost" stroke="#d9655a" dot={false} isAnimationActive={false} />
          <Line dataKey="revenue" stroke="#7fc97f" dot={false} isAnimationActive={false} />
        </ComposedChart>
      </figure>
      {breakdown.length > 0 ? (
        <figure>
          <figcaption className="text-[11px] text-mute">Cost breakdown (whole mine), {code}</figcaption>
          <BarChart width={width} height={160} data={breakdown} margin={{ top: 8, right: 16 }}>
            <CartesianGrid stroke="#3a3f46" strokeDasharray="2 4" />
            <XAxis dataKey="name" tick={tick} tickLine={false} />
            <YAxis tick={tick} tickLine={false} width={64} />
            <Tooltip {...tooltip} />
            <Bar dataKey="value" fill="#8f99a3" isAnimationActive={false} />
          </BarChart>
        </figure>
      ) : null}
    </div>
  )
}

export function CashflowTable({ buckets, code }: { buckets: CashflowBucket[]; code: string }) {
  if (buckets.length === 0) return null
  const cost = (b: CashflowBucket) =>
    b.developmentCost +
    b.productionMiningCost +
    b.processingCost +
    b.backfillCost +
    b.fixedOperatingCost +
    b.initialCapitalCost
  return (
    <div className="readout text-[10px]" data-testid="cashflow-table">
      <div className="max-h-72 overflow-y-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr className="text-mute">
              <th className="text-left font-normal">Days</th>
              <th className="text-right font-normal">Cost</th>
              <th className="text-right font-normal">Revenue</th>
              <th className="text-right font-normal">Net</th>
              <th className="text-right font-normal">Cumulative</th>
            </tr>
          </thead>
          <tbody>
            {buckets.map((b) => (
              <tr key={b.index} className="border-t border-rock-800 text-chalk-dim">
                <td className="py-0.5">
                  {fmt0(b.startDay)}–{fmt0(b.endDay)}
                </td>
                <td className="text-right">{fmt0(cost(b))}</td>
                <td className="text-right">{fmt0(b.revenue)}</td>
                <td className={`text-right ${b.netCashflow < 0 ? 'text-danger' : 'text-lamp'}`}>
                  {fmt0(b.netCashflow)}
                </td>
                <td className="text-right">{fmt0(b.cumulativeCashflow)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-1 text-mute">Amounts in {code}; bucket totals are the backend&apos;s.</p>
    </div>
  )
}
