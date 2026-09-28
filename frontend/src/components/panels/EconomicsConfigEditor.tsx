import { useState } from 'react'
import { ActionButton } from '@/components/ui/ActionButton'
import { InfoPopover } from '@/components/ui/InfoPopover'
import type { EconomicsConfig } from '@/types/analysis'
import {
  DEMO_ASSUMPTIONS,
  DEVELOPMENT_RATE_KEYS,
  DEVELOPMENT_RATE_LABEL,
  METHOD_RATE_KEY,
  PRODUCTION_RATE_KEYS,
  PRODUCTION_RATE_LABEL,
  SCALAR_LABEL,
  type EconomicsDraft,
  type EconomicsDraftState,
  type ScalarKey,
  draftFromConfig,
  draftToConfig,
  economicsDraftIsDirty,
  persistedDraft,
  reconcileEconomicsDraft,
} from './economicsDraft'

const FIELD =
  'w-full rounded-sm border border-rock-700 bg-rock-900 px-1.5 py-0.5 text-[11px] text-chalk focus:border-lamp focus:outline-none'

interface Props {
  /** the persisted assumptions (null → not configured) */
  persisted: EconomicsConfig | null
  /** `scenarioId:economicsRevision` — a change discards the pending draft */
  identity: string
  /** the scenario's active mining method (its production rate is highlighted) */
  activeMethod: string | null
  saving: boolean
  enabled: boolean
  saveError: string | null
  onSave: (config: EconomicsConfig) => void
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <fieldset className="mb-1.5 rounded-sm border border-rock-700 px-2 py-1.5">
      <legend className="plate px-1 text-[10px] text-mute">{title}</legend>
      <div className="grid grid-cols-2 gap-1.5">{children}</div>
    </fieldset>
  )
}

/**
 * Phase 22B — the "Configure assumptions" editor. Every value is an explicit
 * user input persisted as `economics.json` beside the scenario; saving never
 * generates, regenerates or invalidates a mine artifact — it only reloads the
 * analysis. The one convenience, "Use demo assumptions", loads clearly
 * labelled DEMO / SYNTHETIC numbers on an explicit click and never runs on
 * its own.
 */
export function EconomicsConfigEditor(p: Props) {
  const persisted = persistedDraft(p.persisted)
  const [stored, setStored] = useState<EconomicsDraftState>({
    identity: p.identity,
    draft: persisted,
  })
  const draft = reconcileEconomicsDraft(stored, p.identity, persisted).draft
  const setDraft = (update: (d: EconomicsDraft) => EconomicsDraft) =>
    setStored((s) => {
      const current = reconcileEconomicsDraft(s, p.identity, persisted).draft
      return { identity: p.identity, draft: update(current) }
    })
  const parsed = draftToConfig(draft)
  const dirty = economicsDraftIsDirty(draft, persisted)
  const activeRate = p.activeMethod ? METHOD_RATE_KEY[p.activeMethod] : undefined
  const text = (label: string, value: string, set: (v: string) => void, hint?: string) => (
    <label key={label} className="block">
      <span className="mb-0.5 block text-[10px] text-mute">
        {label}
        {hint ? <span className="ml-1 text-lamp">{hint}</span> : null}
      </span>
      <input
        type="text"
        inputMode="decimal"
        className={FIELD}
        value={value}
        disabled={!p.enabled || p.saving}
        onChange={(e) => set(e.target.value)}
      />
    </label>
  )
  const scalar = (k: ScalarKey) =>
    text(SCALAR_LABEL[k], draft.scalars[k], (v) =>
      setDraft((d) => ({ ...d, scalars: { ...d.scalars, [k]: v } })),
    )
  return (
    <div className="flex flex-col gap-1.5" data-testid="economics-config-editor">
      <div className="flex items-center gap-1.5 text-[11px] text-chalk-dim">
        <span>Configure assumptions</span>
        <InfoPopover label="planning economics assumptions">
          Every number is an explicit planning assumption you enter; nothing is defaulted or
          estimated. Revenue is planned mined tonnes × gross revenue per mined tonne (the grade
          proxy is never a revenue input). Development cost is edge length × rate per edge type;
          production, processing and revenue follow the timeline&apos;s STOPING / MUCKING tasks;
          backfill cost applies to Cut &amp; Fill only. Saving writes economics.json beside the
          scenario and changes no mine geometry, production or schedule.
        </InfoPopover>
      </div>
      <Section title="Currency">
        {text('Currency code (3 letters, no conversion)', draft.currencyCode, (v) =>
          setDraft((d) => ({ ...d, currencyCode: v.toUpperCase() })),
        )}
      </Section>
      <Section title="Development costs">
        {DEVELOPMENT_RATE_KEYS.map((k) =>
          text(DEVELOPMENT_RATE_LABEL[k], draft.developmentCosts[k], (v) =>
            setDraft((d) => ({ ...d, developmentCosts: { ...d.developmentCosts, [k]: v } })),
          ),
        )}
      </Section>
      <Section title="Production costs">
        {PRODUCTION_RATE_KEYS.map((k) =>
          text(
            PRODUCTION_RATE_LABEL[k],
            draft.productionCosts[k],
            (v) => setDraft((d) => ({ ...d, productionCosts: { ...d.productionCosts, [k]: v } })),
            k === activeRate ? '(active method)' : undefined,
          ),
        )}
      </Section>
      <Section title="Processing / backfill">
        {scalar('processingCostPerTonne')}
        {scalar('backfillCostPerM3')}
      </Section>
      <Section title="Revenue assumption">{scalar('grossRevenuePerMinedTonne')}</Section>
      <Section title="Fixed / capital cost">
        {scalar('fixedOperatingCostPerDay')}
        {scalar('initialCapitalCost')}
      </Section>
      <Section title="Discounting">
        {scalar('annualDiscountRate')}
        {scalar('cashflowBucketDays')}
      </Section>
      <button
        type="button"
        data-testid="use-demo-assumptions"
        disabled={!p.enabled || p.saving}
        onClick={() => setDraft(() => draftFromConfig(DEMO_ASSUMPTIONS))}
        className="plate w-full rounded-sm border border-rock-600 px-3 py-1 text-[11px] text-chalk-dim hover:border-lamp hover:text-lamp disabled:cursor-not-allowed disabled:opacity-40"
        title="Loads illustrative round numbers into the editor. Nothing is saved until you press Save."
      >
        Use demo assumptions — DEMO / SYNTHETIC ASSUMPTIONS
      </button>
      {parsed.config === null && dirty ? (
        <p className="text-[10px] text-mute">Missing or invalid: {parsed.problems.join(', ')}</p>
      ) : null}
      {p.saveError ? <p className="break-words text-[11px] text-danger">{p.saveError}</p> : null}
      <ActionButton
        variant={dirty && parsed.config !== null ? 'primary' : 'secondary'}
        disabled={!p.enabled || p.saving || !dirty || parsed.config === null}
        onClick={() => {
          if (parsed.config) p.onSave(parsed.config)
        }}
        title="Writes economics.json beside the scenario and reloads the analysis; no mine artifact is regenerated"
      >
        {p.saving ? 'Saving assumptions…' : 'Save assumptions'}
      </ActionButton>
    </div>
  )
}
