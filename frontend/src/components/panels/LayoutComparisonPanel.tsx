import type { LayoutComparisonPayload, LayoutDevelopmentComparisonRow } from '@/types/analysis'
import { Disclosure } from '@/components/ui/Disclosure'
import { Metrics } from '@/components/ui/MetricRow'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { WorkflowCard } from '@/components/ui/WorkflowCard'
import { AVAILABILITY_LABEL, availabilityTone, fmt0, metres, money } from './analysisFormat'

/**
 * Phase 22C — Layout comparison (rules 204–206): pure presentation of
 * `GET …/analysis/layout-comparison`. Every length, cost, delta, rank and
 * score is a backend field; rows are shown in the backend order (the
 * persisted engineering ranking) and are never re-sorted by cost. The
 * engineering rank and the comparable development cost are two separate
 * readouts: this view names no "economic winner", "best option" or
 * "recommended" candidate.
 */

export const INCLUDED_BASIS_TEXT = 'Included cost basis: Main ramp + level access only'
export const INACTIVE_LAYOUT_TEXT =
  'These are inactive Layout-v2 alternatives; the active design uses the Legacy ramp.'
export const COST_NOT_CONFIGURED_TEXT =
  'Cost: NOT CONFIGURED — set planning economics in the Economics tab.'

export interface LayoutComparisonBodyProps {
  payload: LayoutComparisonPayload | null
  error: string | null
  loading: boolean
}

function shortId(row: LayoutDevelopmentComparisonRow): string {
  return row.candidateId.startsWith(`${row.family}-`)
    ? row.candidateId.slice(row.family.length + 1)
    : row.candidateId
}

function signedMoney(v: number | null, code: string | null): string {
  if (v === null) return '—'
  const sign = v > 0 ? '+' : v < 0 ? '−' : '±'
  return `${sign}${money(Math.abs(v), code)}`
}

function signedScore(v: number): string {
  return `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(3)}`
}

export function LayoutComparisonBody({ payload, error, loading }: LayoutComparisonBodyProps) {
  if (error) {
    return (
      <p
        className="break-words px-4 py-3 text-[11px] text-danger"
        data-testid="layout-comparison-error"
      >
        layout comparison unavailable — {error}
      </p>
    )
  }
  if (!payload) {
    return (
      <p className="px-4 py-3 text-[11px] text-mute">
        {loading ? 'Loading layout comparison…' : ''}
      </p>
    )
  }
  const code = payload.currencyCode
  const configured = payload.availability === 'AVAILABLE'
  const winner = payload.rows.find((r) => r.winner) ?? null
  const selected = payload.rows.find((r) => r.selected) ?? null
  return (
    <>
      <div
        className="mx-4 my-2 rounded-sm border border-rock-600 bg-rock-900/70 px-2 py-1.5 text-[11px] leading-relaxed text-chalk-dim"
        data-testid="layout-comparison-disclaimer"
      >
        {payload.disclaimer}
      </div>
      <WorkflowCard
        title="Layout comparison"
        tone={availabilityTone(payload.availability)}
        statusLabel={AVAILABILITY_LABEL[payload.availability]}
        info="Comparable layout development cost = persisted main-ramp length × ramp rate + persisted level-access length × level-access rate, per ranked layout-v2 candidate. It compares only the development a candidate owns in the catalogue (main ramp and level accesses) and excludes drifts, crosscuts, shafts, production, processing, backfill, fixed operating cost, capital, revenue and NPV. Ranking, winner and selection are the layout authority's and are never changed by cost."
        failure={payload.availability === 'NOT_AVAILABLE' ? payload.reason : null}
        notice={payload.scope === 'INACTIVE_LAYOUT_V2' ? INACTIVE_LAYOUT_TEXT : null}
        summary={
          payload.availability === 'NOT_AVAILABLE' ? null : (
            <Metrics
              rows={[
                {
                  label: 'Ranking winner (engineering rank #1)',
                  value: winner ? shortId(winner) : (payload.winnerId ?? '—'),
                },
                {
                  label: 'Selected candidate',
                  value: selected
                    ? `${shortId(selected)}${selected.winner ? ' (= winner)' : ` (engineering rank #${String(selected.catalogueRank ?? '—')})`}`
                    : (payload.selectedCandidateId ?? 'none'),
                },
                { label: 'Comparable feasible candidates', value: fmt0(payload.rows.length) },
                { label: 'Cost basis', value: 'Main ramp + level access only' },
                configured
                  ? {
                      label: 'Rates',
                      value: `${money(payload.rampRatePerM, code)}/m ramp · ${money(payload.levelAccessRatePerM, code)}/m access`,
                    }
                  : null,
              ]}
            />
          )
        }
      />
      {payload.availability !== 'NOT_AVAILABLE' ? (
        <section
          className="border-b border-rock-700 px-4 py-3"
          aria-label="layout comparison table"
        >
          <div className="mb-1 flex items-center justify-between text-[11px] text-chalk-dim">
            <span>{INCLUDED_BASIS_TEXT}</span>
            <StatusBadge
              tone={configured ? 'READY' : 'INACTIVE'}
              label={configured ? `Cost in ${code ?? ''}`.trim() : 'Cost not configured'}
            />
          </div>
          {!configured ? (
            <p className="mb-1.5 text-[11px] text-chalk-dim" data-testid="cost-not-configured">
              {COST_NOT_CONFIGURED_TEXT}
            </p>
          ) : null}
          <table
            className="w-full table-fixed border-collapse whitespace-nowrap text-[10px]"
            data-testid="layout-comparison-table"
          >
            <colgroup>
              <col className="w-5" />
              <col />
              <col className="w-14" />
              <col className="w-14" />
              <col className="w-20" />
              <col className="w-16" />
            </colgroup>
            <thead className="text-mute">
              <tr>
                <th className="text-left font-normal" title="engineering rank (layout authority)">
                  Rank
                </th>
                <th className="truncate text-left font-normal">Candidate · Family</th>
                <th className="text-right font-normal">Ramp</th>
                <th className="text-right font-normal">Access</th>
                <th className="text-right font-normal">Comparable cost</th>
                <th className="text-right font-normal">Δ vs winner</th>
              </tr>
            </thead>
            <tbody className="align-top">
              {payload.rows.map((r) => (
                <tr
                  key={r.candidateId}
                  data-candidate-id={r.candidateId}
                  data-winner={r.winner ? 'true' : 'false'}
                  data-selected={r.selected ? 'true' : 'false'}
                  className={`border-t border-rock-800 ${
                    r.selected ? 'text-lamp' : r.winner ? 'text-chalk' : 'text-chalk-dim'
                  }`}
                >
                  <td className="py-0.5 pr-1">
                    {r.catalogueRank === null ? '—' : `#${String(r.catalogueRank)}`}
                  </td>
                  <td className="overflow-hidden py-0.5 pr-1" title={r.candidateId}>
                    <div className="truncate">
                      {r.winner ? '● ' : ''}
                      {shortId(r)}
                      {r.selected ? ' (selected)' : ''}
                    </div>
                    <div className="text-mute">{r.family}</div>
                  </td>
                  <td className="py-0.5 pr-1 text-right">
                    <div>{metres(r.mainRampLengthM)}</div>
                    <div className="text-mute">{configured ? money(r.rampCost, code) : 'n/c'}</div>
                  </td>
                  <td className="py-0.5 pr-1 text-right">
                    <div>{metres(r.levelAccessLengthM)}</div>
                    <div className="text-mute">
                      {configured ? money(r.levelAccessCost, code) : 'n/c'}
                    </div>
                  </td>
                  <td className="py-0.5 pr-1 text-right">
                    <div>
                      {configured ? money(r.comparableDevelopmentCost, code) : 'not configured'}
                    </div>
                    <div className="text-mute">{metres(r.comparableDevelopmentLengthM)}</div>
                  </td>
                  <td className="py-0.5 text-right">
                    {configured ? signedMoney(r.costDeltaFromWinner, code) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {payload.rows.length === 0 ? (
            <p className="mt-1 text-[11px] text-mute">no feasible candidate in the catalogue</p>
          ) : null}
          <p className="mt-1 text-[10px] text-mute">
            order = persisted engineering ranking · ● ranking winner · costs = persisted length ×
            configured rate · Δ = candidate − winner (plain subtraction) · n/c = not configured
          </p>
          {configured && payload.rows.length > 0 ? <CostBars payload={payload} /> : null}
          <Disclosure label="Details" hint="engineering scores per candidate">
            <table className="w-full table-fixed border-collapse text-[10px]" aria-label="scores">
              <thead className="text-mute">
                <tr>
                  <th className="text-left font-normal">Candidate</th>
                  <th className="text-right font-normal">Total</th>
                  <th className="text-right font-normal">Δ total</th>
                  <th className="text-right font-normal">Dev</th>
                  <th className="text-right font-normal">Geol</th>
                  <th className="text-right font-normal">Geom</th>
                </tr>
              </thead>
              <tbody>
                {payload.rows.map((r) => (
                  <tr key={r.candidateId} className="border-t border-rock-800 text-chalk-dim">
                    <td className="truncate pr-1" title={r.candidateId}>
                      {shortId(r)}
                    </td>
                    <td className="text-right">{r.scores ? r.scores.total.toFixed(3) : '—'}</td>
                    <td className="text-right">
                      {r.scoreDeltaFromWinner
                        ? signedScore(r.scoreDeltaFromWinner.totalScoreDeltaFromWinner)
                        : '—'}
                    </td>
                    <td className="text-right">
                      {r.scores ? r.scores.development.toFixed(3) : '—'}
                    </td>
                    <td className="text-right">{r.scores ? r.scores.geology.toFixed(3) : '—'}</td>
                    <td className="text-right">{r.scores ? r.scores.geometry.toFixed(3) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-1 text-[10px] text-mute">
              scores are the backend Layout v2 planning comparators (rule 148) · excluded from the
              comparable cost: {payload.comparisonBasis.excluded.join(', ')}
            </p>
          </Disclosure>
        </section>
      ) : null}
    </>
  )
}

/**
 * Optional bar chart (directive §12): one horizontal bar per candidate in the
 * persisted ranking order, length proportional to the comparable development
 * cost, the ranking winner (●) and the selection (◆) marked. No "optimal",
 * "recommended" or "best" marker exists.
 */
export function CostBars({ payload }: { payload: LayoutComparisonPayload }) {
  const rows = payload.rows.filter((r) => r.comparableDevelopmentCost !== null)
  const max = Math.max(...rows.map((r) => r.comparableDevelopmentCost ?? 0), 0)
  if (rows.length === 0 || max <= 0) return null
  const rowH = 12
  const labelW = 96
  const width = 280
  const barW = width - labelW - 8
  return (
    <svg
      className="mt-1.5 w-full"
      viewBox={`0 0 ${String(width)} ${String(rows.length * rowH + 4)}`}
      role="img"
      aria-label="comparable development cost per candidate (ranking order)"
      data-testid="cost-bars"
    >
      {rows.map((r, i) => {
        const y = i * rowH + 2
        const w = ((r.comparableDevelopmentCost ?? 0) / max) * barW
        return (
          <g key={r.candidateId} data-candidate-id={r.candidateId}>
            <text x={0} y={y + 8.5} className="fill-current text-[7px]" fill="currentColor">
              {`#${String(r.catalogueRank ?? '—')} ${shortId(r).slice(0, 16)}${r.winner ? ' ●' : ''}${r.selected ? ' ◆' : ''}`}
            </text>
            <rect
              x={labelW}
              y={y + 1}
              width={Math.max(w, 0.5)}
              height={rowH - 4}
              fill={r.selected ? '#e0b45c' : r.winner ? '#d8d2c4' : '#7a7468'}
            />
          </g>
        )
      })}
    </svg>
  )
}
