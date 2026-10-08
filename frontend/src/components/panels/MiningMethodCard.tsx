import { useState } from 'react'
import { ActionButton } from '@/components/ui/ActionButton'
import { Metrics } from '@/components/ui/MetricRow'
import { WorkflowCard } from '@/components/ui/WorkflowCard'
import type { BlockOrder, MethodParameters, MiningConfig, StopingDirection } from '@/types/api'
import type { MiningMethodType } from '@/types/enums'
import type { AvailableMethod, MiningMethodSummary } from '@/types/scene'
import {
  IMPLEMENTATION_LABEL,
  type MiningDraftState,
  miningDraftFor,
  miningDraftIsDirty,
  persistedMining,
  reconcileMiningDraft,
} from './miningDraft'

const STOPING_DIRECTION_LABEL: Record<StopingDirection, string> = {
  OVERHAND: 'Overhand',
  UNDERHAND: 'Underhand (not implemented)',
}
const BLOCK_ORDER_LABEL: Record<BlockOrder, string> = {
  SHALLOW_TO_DEEP: 'Shallow to deep',
  DEEP_TO_SHALLOW: 'Deep to shallow',
}

const FIELD =
  'w-full rounded-sm border border-rock-700 bg-rock-900 px-1.5 py-0.5 text-[11px] text-chalk focus:border-lamp focus:outline-none'

interface Props {
  summary: MiningMethodSummary
  /** the scenario REVISION this card edits (`scenarioId:epoch`); a change
   * discards the pending draft (review blocker 3: never leak A's edits into B) */
  identity: string
  pending: boolean
  enabled: boolean
  onApply: (mining: MiningConfig) => void
}

/**
 * Phase 21B/C Mining-method card: a selector over the registry's method
 * table (every method listed with its Implemented / Not implemented status),
 * the explicit parameters of the selected method and one "Apply" action that
 * submits the edited MiningConfig. Applying rewrites the scenario document,
 * which clears EVERY derived artifact (rule 40) and regenerates the world.
 * The card computes nothing: statuses, defaults and validation are the
 * backend's.
 */
export function MiningMethodCard({ summary, identity, pending, enabled, onApply }: Props) {
  const persisted = persistedMining(summary)
  // the draft is derived from (identity, stored state): a stored draft of
  // another identity is never shown or submitted — no effect, no remount needed
  const [stored, setStored] = useState<MiningDraftState>({ identity, draft: persisted })
  const draft = reconcileMiningDraft(stored, identity, persisted).draft
  const setDraft = (update: (d: MiningConfig) => MiningConfig) =>
    setStored((s) => {
      const current = reconcileMiningDraft(s, identity, persisted).draft
      return { identity, draft: update(current) }
    })
  const selected: AvailableMethod | undefined = summary.availableMethods.find(
    (m) => m.method === draft.method,
  )
  const implemented =
    (selected?.implementationStatus ?? summary.implementationStatus) === 'IMPLEMENTED'
  const activeImplemented = summary.implementationStatus === 'IMPLEMENTED'
  const dirty = miningDraftIsDirty(draft, persisted)
  const num = (label: string, value: number, set: (v: number) => void, step = 1) => (
    <label key={label} className="block">
      <span className="mb-0.5 block text-[10px] text-mute">{label}</span>
      <input
        type="number"
        className={FIELD}
        value={value}
        step={step}
        min={0}
        onChange={(e) => {
          const v = Number(e.target.value)
          if (Number.isFinite(v)) set(v)
        }}
      />
    </label>
  )
  const setParams = (patch: Partial<MethodParameters>) =>
    setDraft((d) =>
      d.methodParameters
        ? { ...d, methodParameters: { ...d.methodParameters, ...patch } as MethodParameters }
        : d,
    )
  const mp = draft.methodParameters
  return (
    <WorkflowCard
      stage="METHOD"
      title="Mining method"
      tone={activeImplemented ? 'ACTIVE' : 'INACTIVE'}
      statusLabel={IMPLEMENTATION_LABEL[summary.implementationStatus]}
      info="The mining method is a scenario parameter. The backend registry decides which methods this version implements: Longhole Open Stoping, Cut & Fill and Room & Pillar plan production geometry and a schedule; a method that is not implemented still receives level access and the generic footwall drift, and nothing is substituted from another method. Applying a change rewrites the scenario, clears every derived design artifact and regenerates the world from the same seed."
      summary={<span data-testid="mining-method-name">{summary.displayName}</span>}
      notice={
        activeImplemented
          ? null
          : `${summary.displayName} production is not implemented in this version. Level access and the generic footwall drift are still designed.`
      }
      action={
        <div className="flex flex-col gap-1.5">
          <label className="block">
            <span className="mb-0.5 block text-[10px] text-mute">Method</span>
            <select
              data-testid="mining-method-select"
              className={FIELD}
              value={draft.method}
              disabled={!enabled || pending}
              onChange={(e) =>
                setDraft((d) => miningDraftFor(summary, e.target.value as MiningMethodType, d))
              }
            >
              {summary.availableMethods.map((m) => (
                <option key={m.method} value={m.method}>
                  {m.displayName} — {IMPLEMENTATION_LABEL[m.implementationStatus]}
                </option>
              ))}
            </select>
          </label>
          {!implemented && selected ? (
            <p className="text-[10px] text-mute">
              {selected.displayName} is not implemented: applying it designs level access and the
              generic drift only — it has no production parameters.
            </p>
          ) : null}
          <div className="grid grid-cols-2 gap-1.5" data-testid="mining-parameters">
            {num('Sublevel interval (m)', draft.sublevelInterval, (v) =>
              setDraft((d) => ({ ...d, sublevelInterval: v })),
            )}
            {/* stope length / minimum pillar are LONGHOLE production parameters
                (rule 159): a method without a production implementation shows
                the shared sublevel interval only */}
            {mp === undefined && implemented
              ? [
                  num('Stope length (m)', draft.stopeLength, (v) =>
                    setDraft((d) => ({ ...d, stopeLength: v })),
                  ),
                  num('Minimum pillar (m)', draft.minimumPillar, (v) =>
                    setDraft((d) => ({ ...d, minimumPillar: v })),
                  ),
                ]
              : null}
            {mp?.kind === 'CUT_AND_FILL'
              ? [
                  num('Lift height (m)', mp.liftHeightM, (v) => setParams({ liftHeightM: v }), 0.5),
                  num('Cut length (m)', mp.cutLengthM, (v) => setParams({ cutLengthM: v })),
                  num('Panel length (m)', mp.panelLengthM, (v) => setParams({ panelLengthM: v })),
                  num('Rib pillar (m)', mp.ribPillarWidthM, (v) =>
                    setParams({ ribPillarWidthM: v }),
                  ),
                  <label key="stoping-direction" className="block">
                    <span className="mb-0.5 block text-[10px] text-mute">Stoping direction</span>
                    <select
                      data-testid="stoping-direction-select"
                      className={FIELD}
                      value={mp.stopingDirection}
                      onChange={(e) =>
                        setParams({ stopingDirection: e.target.value as StopingDirection })
                      }
                    >
                      <option value="OVERHAND">Overhand (lifts bottom → top)</option>
                      <option value="UNDERHAND">Underhand — not implemented</option>
                    </select>
                  </label>,
                  <label key="block-order" className="block">
                    <span className="mb-0.5 block text-[10px] text-mute">Block order</span>
                    <select
                      data-testid="block-order-select"
                      className={FIELD}
                      value={mp.blockOrder}
                      onChange={(e) => setParams({ blockOrder: e.target.value as BlockOrder })}
                    >
                      <option value="SHALLOW_TO_DEEP">Shallow to deep (cemented sill mats)</option>
                      <option value="DEEP_TO_SHALLOW">Deep to shallow</option>
                    </select>
                  </label>,
                  num(
                    'Concurrent panels (max)',
                    mp.maxConcurrentPanels,
                    (v) => setParams({ maxConcurrentPanels: Math.max(1, Math.round(v)) }),
                    1,
                  ),
                  num('Sill mat cure (days)', mp.sillMatCureDays, (v) =>
                    setParams({ sillMatCureDays: v }),
                  ),
                ]
              : null}
            {mp?.kind === 'CUT_AND_FILL' ? (
              <p className="col-span-2 text-[10px] text-mute">
                Planning defaults, never engineering truth: panels and the concurrency bound are
                sequencing assumptions; sill-mat cure is a planning duration.
              </p>
            ) : null}
            {mp?.kind === 'ROOM_AND_PILLAR'
              ? [
                  num('Room width (m)', mp.roomWidthM, (v) => setParams({ roomWidthM: v })),
                  num('Pillar width (m)', mp.pillarWidthM, (v) => setParams({ pillarWidthM: v })),
                  num('Heading height (m)', mp.headingHeightM, (v) =>
                    setParams({ headingHeightM: v }),
                  ),
                  <label key="bench" className="block">
                    <span className="mb-0.5 block text-[10px] text-mute">Bench mode</span>
                    <select
                      data-testid="bench-mode-select"
                      className={FIELD}
                      value={mp.benchCount === 2 ? 'double' : 'single'}
                      onChange={(e) =>
                        setParams({ benchCount: e.target.value === 'double' ? 2 : 1 })
                      }
                    >
                      <option value="single">single</option>
                      <option value="double">double</option>
                    </select>
                  </label>,
                  num('Boundary pillar (m)', mp.boundaryPillarM, (v) =>
                    setParams({ boundaryPillarM: v }),
                  ),
                ]
              : null}
          </div>
          <ActionButton
            variant={dirty ? 'primary' : 'secondary'}
            disabled={!enabled || pending || !dirty}
            onClick={() => onApply(draft)}
            title="Rewrites the scenario: every derived artifact is cleared and the world is regenerated"
          >
            {pending ? 'Applying method…' : 'Apply method'}
          </ActionButton>
        </div>
      }
      details={
        <Metrics
          rows={[
            { label: 'Persisted method', value: summary.displayName },
            { label: 'Export group', value: summary.productionKind ?? 'none (not implemented)' },
            { label: 'Sublevel interval', value: `${summary.sublevelInterval} m` },
            summary.methodParameters === null && activeImplemented
              ? { label: 'Stope length', value: `${summary.stopeLength} m` }
              : null,
            summary.methodParameters === null && activeImplemented
              ? { label: 'Minimum pillar', value: `${summary.minimumPillar} m` }
              : null,
            ...parameterRows(summary.methodParameters),
          ]}
        />
      }
    />
  )
}

function parameterRows(mp: MethodParameters | null): { label: string; value: string }[] {
  if (!mp) return []
  if (mp.kind === 'CUT_AND_FILL') {
    return [
      { label: 'Lift height', value: `${mp.liftHeightM} m` },
      { label: 'Cut length', value: `${mp.cutLengthM} m` },
      { label: 'Panel length', value: `${mp.panelLengthM} m` },
      { label: 'Rib pillar', value: `${mp.ribPillarWidthM} m` },
      { label: 'Stoping direction', value: STOPING_DIRECTION_LABEL[mp.stopingDirection] },
      { label: 'Block order', value: BLOCK_ORDER_LABEL[mp.blockOrder] },
      { label: 'Concurrent panels (max)', value: `${mp.maxConcurrentPanels}` },
      { label: 'Sill mat cure', value: `${mp.sillMatCureDays} days` },
    ]
  }
  return [
    { label: 'Room width', value: `${mp.roomWidthM} m` },
    { label: 'Pillar width', value: `${mp.pillarWidthM} m` },
    { label: 'Heading height', value: `${mp.headingHeightM} m` },
    { label: 'Bench mode', value: mp.benchCount === 2 ? 'double' : 'single' },
    { label: 'Boundary pillar', value: `${mp.boundaryPillarM} m` },
  ]
}
