import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, ReferenceLine, Tooltip, XAxis, YAxis } from 'recharts'
import { ActionButton } from '@/components/ui/ActionButton'
import { Metrics } from '@/components/ui/MetricRow'
import type {
  SensitivityParameterKey,
  SensitivityPayload,
  WhatIfFactors,
  WhatIfOutcome,
} from '@/types/analysis'
import { WHAT_IF_LABEL } from '@/types/analysis'
import { days, fmt0, irrText, money, signedMoney } from './analysisFormat'

const FIELD =
  'w-full rounded-sm border border-rock-700 bg-rock-900 px-1.5 py-0.5 text-[11px] text-chalk focus:border-lamp focus:outline-none'

/**
 * Hardening PR-2 H3 §8.3 — the Sensitivity tab: the backend what-if grid
 * (nine declared parameters × ±10 / 20 / 30 %) as a tornado of Planning NPV
 * deltas plus the full table, and ONE explicit what-if form. Every number is
 * a backend projection labelled WHAT-IF OVERRIDE — NOT SCENARIO VALUE; the
 * frontend never computes an outcome, never persists an override and never
 * writes the scenario, economics.json or timeline.json. The revenue input is
 * exactly "Gross revenue per mined tonne" (rule 199).
 */
export function SensitivityBody({
  payload,
  error,
  loading,
  code,
  whatIf,
  whatIfPending,
  whatIfError,
  onWhatIf,
}: {
  payload: SensitivityPayload | null
  error: string | null
  loading: boolean
  code: string | null
  whatIf: WhatIfOutcome | null
  whatIfPending: boolean
  whatIfError: string | null
  onWhatIf: (factors: WhatIfFactors) => void
}) {
  if (error) {
    return (
      <p role="alert" className="break-words px-4 py-3 text-[11px] text-danger">
        {error}
      </p>
    )
  }
  if (!payload) {
    return (
      <p className="px-4 py-3 text-[11px] text-mute">{loading ? 'Computing the what-if grid…' : ''}</p>
    )
  }
  return (
    <>
      <div
        className="mx-4 my-2 rounded-sm border border-lamp/60 bg-rock-900/70 px-2 py-1.5 text-[11px] leading-relaxed text-chalk-dim"
        data-testid="what-if-label"
      >
        <span className="plate text-lamp">{WHAT_IF_LABEL}</span> — {payload.notice} Revenue
        authority: gross revenue per mined tonne (no commodity price, grade or recovery model).
      </div>
      {payload.availability === 'NOT_AVAILABLE' ? (
        <p className="px-4 py-2 text-[11px] text-mute">{payload.reason}</p>
      ) : (
        <>
          {payload.availability === 'NOT_CONFIGURED' ? (
            <p className="px-4 py-2 text-[11px] text-mute">{payload.reason}</p>
          ) : null}
          <section className="border-b border-rock-700 px-4 py-3">
            <h3 className="plate mb-1.5 text-[12px] text-chalk">Base (unperturbed)</h3>
            <OutcomeMetrics outcome={payload.base} code={code} withDeltas={false} />
          </section>
          <Tornado payload={payload} code={code} />
          <section className="border-b border-rock-700 px-4 py-3">
            <h3 className="plate mb-1.5 text-[12px] text-chalk">All cases</h3>
            <CaseTable payload={payload} code={code} />
          </section>
        </>
      )}
      <section className="border-b border-rock-700 px-4 py-3">
        <h3 className="plate mb-1.5 text-[12px] text-chalk">Explicit what-if</h3>
        <WhatIfForm
          parameters={payload.parameters}
          pending={whatIfPending}
          enabled={payload.availability !== 'NOT_AVAILABLE'}
          onSubmit={onWhatIf}
        />
        {whatIfError ? (
          <p role="alert" className="mt-1.5 break-words text-[11px] text-danger">
            {whatIfError}
          </p>
        ) : null}
        {whatIf ? (
          <div className="mt-2" data-testid="what-if-result">
            <p className="plate text-[11px] text-lamp">{whatIf.label}</p>
            {whatIf.status === 'AVAILABLE' ? (
              <OutcomeMetrics outcome={whatIf} code={code} withDeltas={false} />
            ) : (
              <p className="text-[11px] text-danger">
                {whatIf.status}: {whatIf.reason}
              </p>
            )}
          </div>
        ) : null}
      </section>
      <p className="px-4 py-2 text-[10px] text-mute">{payload.disclaimer}</p>
    </>
  )
}

function OutcomeMetrics({
  outcome,
  code,
  withDeltas,
}: {
  outcome: WhatIfOutcome
  code: string | null
  withDeltas: boolean
}) {
  return (
    <Metrics
      rows={[
        { label: 'Planning NPV', value: money(outcome.planningNpv, code) },
        { label: 'Planning IRR', value: irrText(outcome.planningIrr) },
        { label: 'Mine duration', value: days(outcome.mineDurationDays) },
        { label: 'First production day', value: days(outcome.firstProductionDay) },
        {
          label: 'Schedule',
          value: outcome.scheduleRebuilt ? 'rerun in memory' : 'authoritative timeline',
        },
        withDeltas ? { label: 'Δ Planning NPV', value: signedMoney(outcome.npvDelta, code) } : null,
      ]}
    />
  )
}

function Tornado({ payload, code }: { payload: SensitivityPayload; code: string | null }) {
  // one row per parameter: the NPV delta at the largest ± perturbation
  const extreme = Math.max(...payload.perturbationsPct.map((p) => Math.abs(p)))
  const rows = payload.parameters
    .map((p) => {
      const minus = payload.cases.find(
        (c) => c.parameter === p.key && c.perturbationPct === -extreme,
      )
      const plus = payload.cases.find((c) => c.parameter === p.key && c.perturbationPct === extreme)
      return {
        name: p.label,
        minus: minus?.outcome.npvDelta ?? null,
        plus: plus?.outcome.npvDelta ?? null,
      }
    })
    .filter((r) => r.minus !== null || r.plus !== null)
  if (rows.length === 0) {
    return (
      <p className="px-4 py-2 text-[11px] text-mute">
        No Planning NPV deltas are available (planning economics not configured).
      </p>
    )
  }
  return (
    <section className="border-b border-rock-700 px-4 py-3" data-testid="sensitivity-tornado">
      <h3 className="plate mb-1.5 text-[12px] text-chalk">
        Planning NPV change at ±{fmt0(extreme)} % ({code ?? ''})
      </h3>
      <BarChart
        width={640}
        height={40 + rows.length * 28}
        data={rows}
        layout="vertical"
        margin={{ top: 4, right: 16, left: 8 }}
      >
        <CartesianGrid stroke="#3a3f46" strokeDasharray="2 4" />
        <XAxis type="number" tick={{ fontSize: 10, fill: '#8f99a3' }} tickLine={false} />
        <YAxis
          type="category"
          dataKey="name"
          width={190}
          tick={{ fontSize: 10, fill: '#8f99a3' }}
          tickLine={false}
        />
        <Tooltip
          contentStyle={{ background: '#1f2328', border: '1px solid #3a3f46', fontSize: 11 }}
          formatter={(v: unknown) => (typeof v === 'number' ? signedMoney(v, code) : '—')}
        />
        <ReferenceLine x={0} stroke="#8f99a3" />
        <Bar dataKey="minus" name={`−${fmt0(extreme)} %`} fill="#d9655a" isAnimationActive={false} />
        <Bar dataKey="plus" name={`+${fmt0(extreme)} %`} fill="#7fc97f" isAnimationActive={false} />
      </BarChart>
    </section>
  )
}

function CaseTable({ payload, code }: { payload: SensitivityPayload; code: string | null }) {
  return (
    <div className="readout max-h-80 overflow-y-auto text-[10px]" data-testid="sensitivity-table">
      <table className="w-full border-collapse">
        <thead>
          <tr className="text-mute">
            <th className="text-left font-normal">Parameter</th>
            <th className="text-right font-normal">%</th>
            <th className="text-right font-normal">Planning NPV</th>
            <th className="text-right font-normal">Δ NPV</th>
            <th className="text-right font-normal">Planning IRR</th>
            <th className="text-right font-normal">Duration</th>
            <th className="text-right font-normal">First production</th>
          </tr>
        </thead>
        <tbody>
          {payload.cases.map((c) => (
            <tr
              key={`${c.parameter}:${String(c.perturbationPct)}`}
              className="border-t border-rock-800 text-chalk-dim"
            >
              <td className="py-0.5">
                {c.label} <span className="text-mute">({c.kind.toLowerCase()})</span>
              </td>
              <td className="text-right">
                {c.perturbationPct > 0 ? '+' : ''}
                {fmt0(c.perturbationPct)}
              </td>
              {c.outcome.status === 'AVAILABLE' ? (
                <>
                  <td className="text-right">{money(c.outcome.planningNpv, code)}</td>
                  <td
                    className={`text-right ${(c.outcome.npvDelta ?? 0) < 0 ? 'text-danger' : 'text-lamp'}`}
                  >
                    {signedMoney(c.outcome.npvDelta, code)}
                  </td>
                  <td className="text-right">{irrText(c.outcome.planningIrr)}</td>
                  <td className="text-right">{days(c.outcome.mineDurationDays)}</td>
                  <td className="text-right">{days(c.outcome.firstProductionDay)}</td>
                </>
              ) : (
                <td className="text-right text-danger" colSpan={5}>
                  {c.outcome.status}: {c.outcome.reason}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const FACTOR_KEYS: SensitivityParameterKey[] = [
  'grossRevenuePerMinedTonne',
  'developmentCost',
  'miningCost',
  'processingCost',
  'backfillCost',
  'initialCapital',
  'discountRate',
  'developmentRate',
  'miningRate',
]

function WhatIfForm({
  parameters,
  pending,
  enabled,
  onSubmit,
}: {
  parameters: SensitivityPayload['parameters']
  pending: boolean
  enabled: boolean
  onSubmit: (factors: WhatIfFactors) => void
}) {
  const [pct, setPct] = useState<Record<string, number>>({})
  const labels = new Map(parameters.map((p) => [p.key, p.label] as const))
  const factors: WhatIfFactors = {}
  for (const key of FACTOR_KEYS) {
    const v = pct[key]
    if (v !== undefined && v !== 0) factors[key] = 1 + v / 100
  }
  const dirty = Object.keys(factors).length > 0
  return (
    <div className="flex flex-col gap-1.5" data-testid="what-if-form">
      <div className="grid grid-cols-3 gap-1.5">
        {FACTOR_KEYS.map((key) => (
          <label key={key} className="block">
            <span className="mb-0.5 block text-[10px] text-mute">
              {labels.get(key) ?? key} (% change)
            </span>
            <input
              type="number"
              className={FIELD}
              step={5}
              min={-99}
              max={900}
              value={pct[key] ?? 0}
              disabled={!enabled || pending}
              onChange={(e) => {
                const v = Number(e.target.value)
                if (Number.isFinite(v)) setPct((s) => ({ ...s, [key]: v }))
              }}
            />
          </label>
        ))}
      </div>
      <div className="flex gap-2">
        <ActionButton
          variant="secondary"
          disabled={!enabled || pending || !dirty}
          onClick={() => onSubmit(factors)}
        >
          {pending ? 'Evaluating…' : 'Evaluate what-if (not saved)'}
        </ActionButton>
        <ActionButton variant="secondary" disabled={pending || !dirty} onClick={() => setPct({})}>
          Reset to scenario values
        </ActionButton>
      </div>
      <p className="text-[10px] text-mute">
        Percent changes are applied as multiplicative factors to the configured assumption or
        schedule rate for this evaluation only. Nothing is saved.
      </p>
    </div>
  )
}
