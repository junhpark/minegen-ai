import type { LayoutComparisonPayload, LayoutDevelopmentComparisonRow } from '@/types/analysis'
import { Disclosure } from '@/components/ui/Disclosure'
import { Metrics } from '@/components/ui/MetricRow'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { WorkflowCard } from '@/components/ui/WorkflowCard'
import {
  AVAILABILITY_LABEL,
  availabilityTone,
  fmt0,
  metres,
  money,
  signedMoney,
} from './analysisFormat'
import { optionLabel } from './candidateSummary'
import { tr } from '@/i18n/t'

/**
 * Phase 22C — Layout comparison (rules 204–206): pure presentation of
 * `GET …/analysis/layout-comparison`. Every length, cost, delta, rank and
 * score is a backend field; rows are shown in the backend order (the
 * persisted engineering ranking) and are never re-sorted by cost. The
 * engineering rank and the comparable development cost are two separate
 * readouts: this view names no "economic winner", "best option" or
 * "recommended" candidate.
 *
 * PR-3 round 3 (Park: "비교표가 너무 이질적") — the rows share the Design ›
 * Layout option grammar: `Option n` · family chip · ★ ranking winner ·
 * active / selected chip, one sub-line (`engineering rank #n · comparable
 * length`), fixed-width tabular number columns (nothing overlaps whatever
 * the magnitude), and the comparable-cost BAR drawn inside the row (a
 * display fraction of the largest comparable cost) instead of a separate
 * stretched SVG. Same fields, same order, same vocabulary.
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

/** the option identity of a comparison row (the persisted catalogue rank) */
function rowOption(row: LayoutDevelopmentComparisonRow): string {
  return optionLabel({ rank: row.catalogueRank, candidateId: row.candidateId, family: row.family })
}

function signedScore(v: number): string {
  return `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(3)}`
}

/** rank · option · family · marks, then the four number columns */
const GRID = 'grid grid-cols-[minmax(0,1fr)_7.5rem_7.5rem_9rem_8rem] items-center gap-x-3'
const SCORE_GRID = 'grid grid-cols-[minmax(0,1fr)_4.5rem_4.5rem_4.5rem_4.5rem_4.5rem] gap-x-3'

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
  // the selection chip reads like the Layout card: the selected candidate IS
  // the active design under ACTIVE_DESIGN scope, a dormant selection otherwise
  const selectedState = payload.scope === 'ACTIVE_DESIGN' ? tr('active') : tr('selected')
  const maxCost = Math.max(...payload.rows.map((r) => r.comparableDevelopmentCost ?? 0), 0)
  return (
    <>
      <div
        className="mx-4 my-2 rounded-sm border border-rock-600 bg-rock-900/70 px-2 py-1.5 text-[11px] leading-relaxed text-chalk-dim"
        data-testid="layout-comparison-disclaimer"
      >
        {payload.disclaimer}
      </div>
      <WorkflowCard
        title={tr('Layout comparison')}
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
                  value: winner
                    ? `${rowOption(winner)} · ${winner.family}`
                    : (payload.winnerId ?? '—'),
                },
                {
                  label: 'Selected candidate',
                  value: selected
                    ? selected.winner
                      ? tr('{option} · {family} (= winner)', {
                          option: rowOption(selected),
                          family: selected.family,
                        })
                      : tr('{option} · {family} (engineering rank #{rank})', {
                          option: rowOption(selected),
                          family: selected.family,
                          rank: selected.catalogueRank ?? '—',
                        })
                    : (payload.selectedCandidateId ?? tr('none')),
                },
                { label: 'Comparable feasible candidates', value: fmt0(payload.rows.length) },
                { label: 'Cost basis', value: 'Main ramp + level access only' },
                configured
                  ? {
                      label: 'Rates',
                      value: tr('{ramp}/m ramp · {access}/m access', {
                        ramp: money(payload.rampRatePerM, code),
                        access: money(payload.levelAccessRatePerM, code),
                      }),
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
          aria-label={tr('layout comparison table')}
        >
          <div className="mb-1.5 flex items-center justify-between gap-2 text-[11px] text-chalk-dim">
            <span>{tr(INCLUDED_BASIS_TEXT)}</span>
            <StatusBadge
              tone={configured ? 'READY' : 'INACTIVE'}
              label={
                configured
                  ? tr('Cost in {code}', { code: code ?? '' }).trim()
                  : 'Cost not configured'
              }
            />
          </div>
          {!configured ? (
            <p className="mb-1.5 text-[11px] text-chalk-dim" data-testid="cost-not-configured">
              {COST_NOT_CONFIGURED_TEXT}
            </p>
          ) : null}
          <div
            role="table"
            aria-label={tr('comparable development cost per candidate (ranking order)')}
            data-testid="layout-comparison-table"
            className="text-[11px]"
          >
            <div
              role="row"
              className={`${GRID} plate border-b border-rock-700 pb-1 text-[9px] text-mute`}
            >
              <span role="columnheader" title={tr('engineering rank (layout authority)')}>
                {tr('Option · family')}
              </span>
              <span role="columnheader" className="text-right">
                {tr('Ramp')}
              </span>
              <span role="columnheader" className="text-right">
                {tr('Access')}
              </span>
              <span role="columnheader" className="text-right">
                {tr('Comparable cost')}
              </span>
              <span role="columnheader" className="text-right">
                {tr('Δ vs winner')}
              </span>
            </div>
            {payload.rows.map((r) => {
              const cost = r.comparableDevelopmentCost
              const pct = configured && cost !== null && maxCost > 0 ? (cost / maxCost) * 100 : null
              return (
                <div
                  key={r.candidateId}
                  role="row"
                  data-candidate-id={r.candidateId}
                  data-winner={r.winner ? 'true' : 'false'}
                  data-selected={r.selected ? 'true' : 'false'}
                  title={r.candidateId}
                  className={`${GRID} border-b border-rock-800 py-1.5 ${
                    r.selected ? 'text-chalk' : r.winner ? 'text-chalk' : 'text-chalk-dim'
                  }`}
                >
                  <div role="cell" className="min-w-0">
                    <div className="flex min-w-0 items-baseline gap-1.5">
                      <span className="text-[13px] font-semibold text-chalk">{rowOption(r)}</span>
                      <span className="plate rounded-sm border border-rock-600 px-1 text-[9px] text-mute">
                        {r.family}
                      </span>
                      {r.winner ? (
                        <span className="text-[11px] text-lamp" title={tr('ranking winner')}>
                          ★
                        </span>
                      ) : null}
                      {r.selected ? (
                        <span className="plate rounded-sm bg-lamp/15 px-1 text-[9px] text-lamp">
                          {selectedState}
                        </span>
                      ) : null}
                    </div>
                    <div className="readout mt-0.5 text-[10px] text-mute">
                      {tr('engineering rank {rank} · {length} comparable', {
                        rank: r.catalogueRank === null ? '—' : `#${String(r.catalogueRank)}`,
                        length: metres(r.comparableDevelopmentLengthM),
                      })}
                    </div>
                    {pct !== null ? (
                      <div
                        className="mt-1 h-1 w-full rounded-full bg-rock-700"
                        data-testid="cost-bars"
                        aria-hidden
                      >
                        <div
                          className={`h-1 rounded-full ${r.selected ? 'bg-lamp' : r.winner ? 'bg-chalk' : 'bg-chalk-dim/70'}`}
                          data-testid="cost-bar"
                          style={{ width: `${String(Math.max(pct, 1).toFixed(1))}%` }}
                        />
                      </div>
                    ) : null}
                  </div>
                  <div role="cell" className="readout text-right whitespace-nowrap">
                    <div>{metres(r.mainRampLengthM)}</div>
                    <div className="text-[10px] text-mute">
                      {configured ? money(r.rampCost, code) : 'n/c'}
                    </div>
                  </div>
                  <div role="cell" className="readout text-right whitespace-nowrap">
                    <div>{metres(r.levelAccessLengthM)}</div>
                    <div className="text-[10px] text-mute">
                      {configured ? money(r.levelAccessCost, code) : 'n/c'}
                    </div>
                  </div>
                  <div role="cell" className="readout text-right whitespace-nowrap">
                    <div className="text-[12px]">
                      {configured ? money(cost, code) : 'not configured'}
                    </div>
                  </div>
                  <div
                    role="cell"
                    className={`readout text-right whitespace-nowrap ${
                      configured && (r.costDeltaFromWinner ?? 0) > 0
                        ? 'text-danger'
                        : configured && (r.costDeltaFromWinner ?? 0) < 0
                          ? 'text-ore'
                          : 'text-mute'
                    }`}
                  >
                    {configured ? signedMoney(r.costDeltaFromWinner, code) : '—'}
                  </div>
                </div>
              )
            })}
          </div>
          {payload.rows.length === 0 ? (
            <p className="mt-1 text-[11px] text-mute">
              {tr('no feasible candidate in the catalogue')}
            </p>
          ) : null}
          <p className="mt-1.5 text-[10px] leading-relaxed text-mute">
            {tr(
              'order = persisted engineering ranking · ★ ranking winner · bar = comparable cost as a fraction of the largest · costs = persisted length × configured rate · Δ = candidate − winner (plain subtraction) · n/c = not configured',
            )}
          </p>
          <Disclosure label={tr('Details')} hint={tr('engineering scores per candidate')}>
            <div role="table" aria-label="scores" className="readout text-[11px]">
              <div
                role="row"
                className={`${SCORE_GRID} plate border-b border-rock-700 pb-1 text-[9px] text-mute`}
              >
                <span role="columnheader">{tr('Option')}</span>
                <span role="columnheader" className="text-right">
                  {tr('Total')}
                </span>
                <span role="columnheader" className="text-right">
                  Δ total
                </span>
                <span role="columnheader" className="text-right">
                  {tr('Dev')}
                </span>
                <span role="columnheader" className="text-right">
                  {tr('Geol')}
                </span>
                <span role="columnheader" className="text-right">
                  {tr('Geom')}
                </span>
              </div>
              {payload.rows.map((r) => (
                <div
                  key={r.candidateId}
                  role="row"
                  className={`${SCORE_GRID} border-b border-rock-800 py-0.5 text-chalk-dim`}
                  title={r.candidateId}
                >
                  <span role="cell" className="truncate">
                    {rowOption(r)} <span className="text-mute">{r.family}</span>
                  </span>
                  <span role="cell" className="text-right">
                    {r.scores ? r.scores.total.toFixed(3) : '—'}
                  </span>
                  <span role="cell" className="text-right">
                    {r.scoreDeltaFromWinner
                      ? signedScore(r.scoreDeltaFromWinner.totalScoreDeltaFromWinner)
                      : '—'}
                  </span>
                  <span role="cell" className="text-right">
                    {r.scores ? r.scores.development.toFixed(3) : '—'}
                  </span>
                  <span role="cell" className="text-right">
                    {r.scores ? r.scores.geology.toFixed(3) : '—'}
                  </span>
                  <span role="cell" className="text-right">
                    {r.scores ? r.scores.geometry.toFixed(3) : '—'}
                  </span>
                </div>
              ))}
            </div>
            <p className="mt-1 text-[10px] text-mute">
              {tr(
                'scores are the backend Layout v2 planning comparators (rule 148) · excluded from the comparable cost: {excluded}',
                { excluded: payload.comparisonBasis.excluded.join(', ') },
              )}
            </p>
          </Disclosure>
        </section>
      ) : null}
    </>
  )
}
