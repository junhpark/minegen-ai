import type { CashflowBucket } from '@/types/analysis'
import { fmt0 } from './analysisFormat'

/**
 * Phase 22B — the Planning Cashflow buckets as the backend emitted them
 * (chronological, one row per bucket) plus a plain inline SVG of the net
 * cashflow per bucket. No chart dependency, no client-side aggregation: the
 * cumulative column is the backend's.
 */
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
      <NetBars buckets={buckets} />
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

function NetBars({ buckets }: { buckets: CashflowBucket[] }) {
  const width = 280
  const height = 48
  const peak = Math.max(1e-9, ...buckets.map((b) => Math.abs(b.netCashflow)))
  const bar = width / buckets.length
  const mid = height / 2
  return (
    <svg
      viewBox={`0 0 ${String(width)} ${String(height)}`}
      className="mb-1 h-12 w-full"
      role="img"
      aria-label="net cashflow per bucket"
    >
      <line x1={0} y1={mid} x2={width} y2={mid} stroke="currentColor" strokeOpacity={0.3} />
      {buckets.map((b, i) => {
        const h = (Math.abs(b.netCashflow) / peak) * (mid - 2)
        const y = b.netCashflow >= 0 ? mid - h : mid
        return (
          <rect
            key={b.index}
            x={i * bar + 1}
            y={y}
            width={Math.max(1, bar - 2)}
            height={h}
            className={b.netCashflow >= 0 ? 'fill-lamp' : 'fill-danger'}
          />
        )
      })}
    </svg>
  )
}
