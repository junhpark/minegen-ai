import { useMutation } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { api, ApiError } from '@/api/client'
import { ScenarioChangeDialog } from '@/components/panels/ScenarioChangeDialog'
import { ShaftSpecEditor } from '@/components/panels/ShaftSpecEditor'
import {
  type AccessStrategy,
  accessStrategyOf,
  withAccessStrategy,
} from '@/components/panels/accessStrategy'
import {
  persistedShafts,
  reconcileShaftDraft,
  shaftDraftIsDirty,
  shaftDraftProblems,
  type ShaftDraftState,
} from '@/components/panels/shaftDraft'
import { ActionButton } from '@/components/ui/ActionButton'
import { WorkflowCard } from '@/components/ui/WorkflowCard'
import { activateScenarioRevision } from '@/stores/scenarioSession'
import { useScenarioStore } from '@/stores/scenarioStore'
import type { ScenarioCreate, ShaftPlanningConfig, ShaftSpec } from '@/types/api'
import type { CollarSuggestion } from '@/types/scene'

/**
 * PR #54 review B3 — Setup › Access: the access strategy of the mine is
 * declared BEFORE the layout (○ Ramp only / ● Ramp + Shaft with the explicit
 * `scenario.shafts` parameters), so declaring a shaft is a Setup decision
 * and never resets a finished design by surprise. Applying is the rule 40
 * scenario PUT followed by world regeneration from the same seed; on a mine
 * that already has a world the shared reset-plan confirmation lists exactly
 * what the backend clears (everything from Layout on). Design › Shafts then
 * only PLANS the declared shafts and sweeps their mesh.
 */
export function AccessPanel() {
  const scenarioDoc = useScenarioStore((s) => s.scenario)
  const scene = useScenarioStore((s) => s.scene)
  const epoch = useScenarioStore((s) => s.epoch)
  const setScene = useScenarioStore((s) => s.setScene)
  const [pending, setPending] = useState<{ config: ShaftPlanningConfig; attempt: number } | null>(
    null,
  )
  const attempt = useRef(0)
  const apply = useMutation({
    mutationFn: async (config: ShaftPlanningConfig) => {
      if (!scenarioDoc) throw new Error('load a scenario first')
      const id = scenarioDoc.id
      const body: Record<string, unknown> = { ...scenarioDoc, shafts: config }
      delete body.id
      delete body.schemaVersion
      const updated = await api.replaceScenario(id, body as unknown as ScenarioCreate)
      // the PUT replaced the document: a NEW scenario revision (epoch + 1)
      const started = activateScenarioRevision(updated)
      await api.generateWorld(id)
      const next = await api.getScene(id)
      setScene(next, started)
      return updated
    },
  })
  const suggestCollar = async (spec: ShaftSpec): Promise<CollarSuggestion> => {
    if (!scenarioDoc) throw new Error('load a scenario first')
    return api.suggestShaftCollar(scenarioDoc.id, spec)
  }
  const err = apply.error
  const errorText =
    err instanceof ApiError ? `${err.code}: ${err.message}` : err ? err.message : null
  return (
    <>
      {scenarioDoc ? (
        <ScenarioChangeDialog
          scenarioId={scenarioDoc.id}
          pending={pending?.config ?? null}
          attempt={pending?.attempt ?? 0}
          hasWorld={scene !== null}
          title="Change access strategy"
          intro="The world is regenerated with the same seed; everything from Layout on is reset."
          confirmLabel="Apply access strategy"
          listTestId="access-will-delete"
          onCancel={() => setPending(null)}
          onConfirm={(config) => {
            setPending(null)
            apply.mutate(config)
          }}
        />
      ) : null}
      <AccessStrategyCard
        identity={`${scenarioDoc?.id ?? ''}:${String(epoch)}`}
        persisted={scenarioDoc?.shafts ?? null}
        hasScenario={scenarioDoc !== null}
        hasWorld={scene !== null}
        levelIds={scene?.levels?.levels.map((l) => l.levelId) ?? []}
        pending={apply.isPending}
        error={errorText}
        onApply={(config) => {
          if (scene) {
            attempt.current += 1
            setPending({ config, attempt: attempt.current })
          } else {
            apply.mutate(config)
          }
        }}
        onSuggestCollar={scene?.levels ? suggestCollar : undefined}
      />
    </>
  )
}

interface CardProps {
  /** the scenario REVISION this card edits (`scenarioId:epoch`) */
  identity: string
  persisted: ShaftPlanningConfig | null | undefined
  hasScenario: boolean
  hasWorld: boolean
  /** level ids of an existing level development (collar suggestion targets) */
  levelIds: readonly string[]
  pending: boolean
  error: string | null
  onApply: (config: ShaftPlanningConfig) => void
  /** present only while a level development exists (the planner's default
   * collar is derived from it) */
  onSuggestCollar?: ((spec: ShaftSpec) => Promise<CollarSuggestion>) | undefined
}

/** pure presentation of the Access stage (testable as static markup) */
export function AccessStrategyCard(p: CardProps) {
  const base = persistedShafts(p.persisted)
  const [stored, setStored] = useState<ShaftDraftState>({ identity: p.identity, draft: base })
  const draft = reconcileShaftDraft(stored, p.identity, base).draft
  const setDraft = (update: (d: ShaftPlanningConfig) => ShaftPlanningConfig) =>
    setStored((s) => {
      const current = reconcileShaftDraft(s, p.identity, base).draft
      return { identity: p.identity, draft: update(current) }
    })
  const strategy = accessStrategyOf(draft)
  const dirty = shaftDraftIsDirty(draft, base)
  const problems = shaftDraftProblems(draft)
  const enabled = p.hasScenario && !p.pending
  const canApply = enabled && dirty && problems.length === 0
  const persistedStrategy = accessStrategyOf(base)
  const radio = (value: AccessStrategy, label: string, testId: string) => (
    <label className="flex items-center gap-1.5 text-[11px] text-chalk-dim">
      <input
        type="radio"
        name="access-strategy"
        value={value}
        data-testid={testId}
        checked={strategy === value}
        disabled={!enabled}
        onChange={() => setDraft((d) => withAccessStrategy(d, value))}
      />
      {label}
    </label>
  )
  return (
    <WorkflowCard
      stage="ACCESS"
      title="Access strategy"
      tone={p.hasWorld ? 'READY' : 'NOT_GENERATED'}
      info="How the mine is accessed: the ramp always exists and stays the primary access; a declared shaft is additional vertical infrastructure (collar on the terrain, one station per required level, sump) the backend plans against the level development later, in Design › Shafts. The declaration is part of the scenario document, so changing it rewrites the scenario, regenerates the world from the same seed and clears everything from Layout on — decide it here, before the layout."
      summary={
        persistedStrategy === 'RAMP_ONLY'
          ? 'Ramp only'
          : `Ramp + ${String(base.specs.length)} shaft${base.specs.length === 1 ? '' : 's'}`
      }
      failure={p.error}
      notice={
        !p.hasScenario ? (
          <>Create or open a mine first — the access strategy is part of its scenario.</>
        ) : null
      }
      action={
        <div className="flex flex-col gap-1.5" data-testid="access-strategy">
          <div className="flex gap-4" role="radiogroup" aria-label="access strategy">
            {radio('RAMP_ONLY', 'Ramp only', 'access-ramp-only')}
            {radio('RAMP_AND_SHAFT', 'Ramp + Shaft', 'access-ramp-shaft')}
          </div>
          {strategy === 'RAMP_AND_SHAFT' ? (
            <ShaftSpecEditor
              draft={draft}
              onChange={(next) => setDraft(() => next)}
              levelIds={p.levelIds}
              pending={p.pending}
              enabled={enabled}
              onSuggestCollar={p.onSuggestCollar}
            />
          ) : null}
          {problems.length > 0 ? (
            <ul className="list-disc pl-4 text-[10px] text-danger">
              {problems.map((problem) => (
                <li key={problem}>{problem}</li>
              ))}
            </ul>
          ) : null}
          <ActionButton
            variant={canApply ? 'primary' : 'secondary'}
            disabled={!canApply}
            onClick={() => p.onApply(draft)}
          >
            {p.pending ? 'Applying…' : 'Apply access strategy'}
          </ActionButton>
          <p className="text-[10px] text-mute">
            {p.hasWorld
              ? 'Applying rewrites the scenario: every design artifact is cleared and the world is regenerated from the same seed (you confirm the list first).'
              : 'Applying rewrites the scenario and generates its world.'}
          </p>
        </div>
      }
    />
  )
}
