import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, ApiError } from '@/api/client'
import { AdvancedScenarioEditor } from '@/scenario/AdvancedScenarioEditor'
import {
  DEFAULT_BUILDER,
  faultCountEnabled,
  morphologySummary,
  presetLabel,
  realizeRequest,
  realizedSummary,
} from '@/scenario/builder'
import { loadScene, openScenario } from '@/scenario/openScenario'
import {
  SCENARIO_PRESETS,
  type Scenario,
  type ScenarioCreate,
  type ScenarioPreset,
} from '@/types/api'
import { ActionButton } from '@/components/ui/ActionButton'
import { Disclosure } from '@/components/ui/Disclosure'
import { WorkflowCard } from '@/components/ui/WorkflowCard'
import { activateScenario, scenarioEpoch } from '@/stores/scenarioSession'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useViewerStore } from '@/stores/viewerStore'
import { fmtMeters } from '@/utils/format'

const INPUT =
  'w-full rounded-sm border border-rock-700 bg-rock-900 px-2 py-1 text-chalk focus:border-lamp focus:outline-none'

/**
 * Hardening H1 §4.3 — the Setup › Scenario stage.
 *
 * ONE primary action, "Create mine": the backend realizes preset + seed (the
 * panel never draws a random number — rule 119/124), persists the explicit
 * document the user reviewed, generates its world and loads the scene; the
 * shell then moves to the Method stage. Randomize (preview the deterministic
 * realization) and the Advanced editor are secondary; the saved list lives
 * under File › Open and in the Details of this card. Parameters shown are
 * echoed from the backend document, not computed.
 */
export function SetupPanel() {
  const qc = useQueryClient()
  const scenario = useScenarioStore((s) => s.scenario)
  const scene = useScenarioStore((s) => s.scene)
  const setStage = useViewerStore((s) => s.setStage)
  const [name, setName] = useState('Synthetic Gold Mine 001')
  const [seed, setSeed] = useState(DEFAULT_BUILDER.seed)
  const [preset, setPreset] = useState<ScenarioPreset>(DEFAULT_BUILDER.preset)
  const [faultCount, setFaultCount] = useState(DEFAULT_BUILDER.faultCount)
  // realized = the untouched backend realization; draft = the editable
  // document the user will actually persist (Phase 17 acceptance, rule 124)
  const [realized, setRealized] = useState<ScenarioCreate | null>(null)
  const [draft, setDraft] = useState<ScenarioCreate | null>(null)
  const [advancedOpen, setAdvancedOpen] = useState(false)

  const list = useQuery({ queryKey: ['scenarios'], queryFn: api.listScenarios })

  const realize = useMutation({
    mutationFn: () => api.realizeScenario(realizeRequest({ preset, seed, faultCount })),
    onSuccess: (sc) => {
      setRealized(sc)
      setDraft(sc) // realization seeds the editable draft
    },
  })

  /** preset / seed / fault-count changes make any existing realization
   * stale — never show or submit it as if it belonged to the new inputs */
  const invalidateDraft = () => {
    setRealized(null)
    setDraft(null)
  }

  // "Create mine" = create + generate world in one step (§4.3)
  const create = useMutation({
    mutationFn: async () => {
      // the edited draft is authoritative: never re-realize over user edits
      const resolved =
        draft ?? (await api.realizeScenario(realizeRequest({ preset, seed, faultCount })))
      const s = await api.createScenario({ ...resolved, name })
      // one scenario-identity transition clears everything derived (§1)
      const epoch = activateScenario(s)
      await api.generateWorld(s.id)
      await loadScene(s.id, epoch)
      return s
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['scenarios'] })
      setStage('METHOD')
    },
  })

  const load = useMutation({ mutationFn: openScenario })

  // a scenario loaded without a world (or a deliberate regeneration)
  const generate = useMutation({
    mutationFn: async () => {
      if (!scenario) throw new Error('no scenario selected')
      const epoch = scenarioEpoch()
      await api.generateWorld(scenario.id)
      await loadScene(scenario.id, epoch)
    },
  })

  const error = realize.error ?? create.error ?? load.error ?? generate.error
  const errorText =
    error instanceof ApiError ? `${error.code}: ${error.message}` : error ? error.message : null
  const busy = create.isPending || generate.isPending || load.isPending

  const design = scene?.rampSource.available
    ? scene.rampSource.activeSource === 'LAYOUT_V2'
      ? 'Layout v2'
      : 'Legacy decline'
    : 'no design yet'

  // ONE primary: creating a mine while none exists, else generating the
  // missing world of a loaded scenario; with a world both are secondary
  const createVariant = scenario === null && !busy ? 'primary' : 'secondary'
  const worldVariant = scenario !== null && scene === null && !busy ? 'primary' : 'secondary'

  return (
    <WorkflowCard
      stage="SCENARIO"
      title="Scenario"
      tone={scenario ? (scene ? 'READY' : 'NOT_GENERATED') : 'NOT_GENERATED'}
      statusLabel={scenario ? (scene ? 'World ready' : 'No world') : 'No mine'}
      info="A synthetic mine: terrain, an authoritative orebody solid and seeded numerical rock-quality and grade fields, plus the declared fault planes. Every stochastic parameter is drawn once by the backend when you randomize, then persisted resolved, so the same scenario always reproduces the same world. It is a synthetic sandbox — never a measured, estimated or imported orebody."
      summary={
        scenario ? (
          <>
            <div className="truncate text-[12px] text-chalk" title={scenario.name}>
              {scenario.name}
            </div>
            <div>
              {scenario.orebody.orebodyType} · seed {scenario.seed} · {design}
            </div>
          </>
        ) : (
          'No mine yet — create one in the Scenario stage.'
        )
      }
      action={
        <div data-testid="setup-form">
          <label className="mb-2 block">
            <span className="mb-1 block text-[11px] text-chalk-dim">Name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} className={INPUT} />
          </label>
          <label className="mb-2 block">
            <span className="mb-1 block text-[11px] text-chalk-dim">Preset</span>
            <select
              value={preset}
              onChange={(e) => {
                setPreset(e.target.value as ScenarioPreset)
                invalidateDraft()
              }}
              className={INPUT}
            >
              {SCENARIO_PRESETS.map((p) => (
                <option key={p} value={p}>
                  {presetLabel(p)}
                </option>
              ))}
            </select>
          </label>
          <div className="mb-2 grid grid-cols-[1fr_auto_auto] items-end gap-2">
            <label className="block">
              <span className="mb-1 block text-[11px] text-chalk-dim">Seed</span>
              <input
                type="number"
                value={seed}
                onChange={(e) => {
                  setSeed(Number(e.target.value))
                  invalidateDraft()
                }}
                className={`readout ${INPUT}`}
              />
            </label>
            <label className="block w-16">
              <span className="mb-1 block text-[11px] text-chalk-dim">Faults</span>
              <input
                type="number"
                min={0}
                max={6}
                value={faultCountEnabled(preset) ? faultCount : 1}
                disabled={!faultCountEnabled(preset)}
                onChange={(e) => {
                  setFaultCount(Math.max(0, Math.min(6, Number(e.target.value))))
                  invalidateDraft()
                }}
                className={`readout ${INPUT} disabled:opacity-50`}
              />
            </label>
            <button
              type="button"
              onClick={() => realize.mutate()}
              disabled={realize.isPending || busy}
              className="plate rounded-sm border border-rock-600 px-2 py-1 text-[12px] text-chalk hover:bg-rock-700 disabled:opacity-50"
              title="Preview the deterministic realization for this preset + seed"
            >
              {realize.isPending ? '…' : 'Randomize'}
            </button>
          </div>
          {draft ? (
            <>
              <div className="readout mb-2 rounded-sm border border-rock-700 bg-rock-900/60 px-2 py-1.5 text-[11px] leading-relaxed text-chalk-dim">
                {realizedSummary(draft).map((line) => (
                  <div key={line}>{line}</div>
                ))}
                <div className="mt-1 text-mute">
                  {realized && JSON.stringify(draft) !== JSON.stringify(realized)
                    ? 'Edited — your values will be persisted as-is.'
                    : 'Same seed always reproduces this exact mine.'}
                </div>
              </div>
              <button
                type="button"
                onClick={() => setAdvancedOpen((v) => !v)}
                className="mb-2 w-full rounded-sm border border-rock-700 px-2 py-1 text-left text-[11px] text-chalk-dim hover:bg-rock-800"
              >
                {advancedOpen ? '▾' : '▸'} Advanced
              </button>
              {advancedOpen ? <AdvancedScenarioEditor draft={draft} onChange={setDraft} /> : null}
            </>
          ) : null}
          <ActionButton
            variant={createVariant}
            disabled={busy}
            onClick={() => create.mutate()}
            title="Persist the reviewed scenario and generate its world in one step"
          >
            {create.isPending ? 'Creating mine…' : 'Create mine'}
          </ActionButton>
          {scenario ? (
            <div className="mt-1.5">
              <ActionButton
                variant={worldVariant}
                disabled={busy}
                onClick={() => generate.mutate()}
                title="Regenerate the world of the loaded scenario from its persisted document (same seed, same world)"
              >
                {generate.isPending
                  ? 'Generating world…'
                  : scene
                    ? 'Regenerate world'
                    : 'Generate world'}
              </ActionButton>
            </div>
          ) : null}
          {errorText ? (
            <p role="alert" className="mt-2 text-[11px] text-danger">
              {errorText}
            </p>
          ) : null}
          <Disclosure
            label="Saved mines"
            hint={list.isSuccess ? String(list.data.length) : undefined}
          >
            {list.isSuccess && list.data.length > 0 ? (
              <ul className="mt-1 flex max-h-40 flex-col gap-1 overflow-y-auto">
                {list.data.map((s) => (
                  <li key={s.id}>
                    <button
                      type="button"
                      onClick={() => load.mutate(s.id)}
                      disabled={busy}
                      className={[
                        'flex w-full items-center justify-between rounded-sm px-2 py-1 text-left hover:bg-rock-700/60',
                        scenario?.id === s.id ? 'bg-rock-700 text-chalk' : 'text-chalk-dim',
                      ].join(' ')}
                    >
                      <span className="truncate">{s.name}</span>
                      <span className="readout text-[10px] text-mute">#{s.seed}</span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-mute">No saved mines yet.</p>
            )}
          </Disclosure>
        </div>
      }
      details={scenario ? <ParametersPanel scenario={scenario} /> : null}
    />
  )
}

/**
 * Scenario parameter readout (Phase 17.1 §4). Split out of `ScenarioPanel`
 * so the two-column layout is directly testable; it is presentational only
 * and echoes the backend document without computing anything. Phase 20E
 * renders it inside the Scenario section's "Details" disclosure (§7).
 */
export function ParametersPanel({ scenario }: { scenario: Scenario | null }) {
  return (
    <>
      {scenario ? (
        /* Phase 17.1 §4: a fixed label column. `auto` sized itself to the
           longest label — the synthetic-RMR disclaimer — and squeezed
           every value into the remainder. Long labels now WRAP inside
           their own column, so all values keep one left edge. */
        <dl className="readout grid grid-cols-[7.5rem_minmax(0,1fr)] items-baseline gap-x-2 gap-y-1.5 text-[11px]">
          <dt className="break-words text-mute">World</dt>
          <dd className="break-words">
            {scenario.world.sizeX} × {scenario.world.sizeY} m
          </dd>
          <dt className="break-words text-mute">Model depth</dt>
          <dd className="break-words">
            {fmtMeters(scenario.world.depth, 0)} below{' '}
            {fmtMeters(scenario.terrain.baseElevation, 0)}
          </dd>
          <dt className="break-words text-mute">Orebody</dt>
          <dd className="break-words">{scenario.orebody.orebodyType}</dd>
          <dt className="break-words text-mute">Strike / dip</dt>
          <dd className="break-words">
            {scenario.orebody.strikeDeg}° / {scenario.orebody.dipDeg}°
          </dd>
          {/* Phase 19: a WARPED_VEIN has no constant thickness — its
              dimensions are NOMINAL and the resolved morphology modulates
              them, so the readout must not imply otherwise */}
          {scenario.orebody.orebodyType === 'WARPED_VEIN' && scenario.orebody.warpedVein ? (
            <>
              <dt className="break-words text-mute">Nominal size</dt>
              <dd className="break-words">
                {fmtMeters(scenario.orebody.length, 0)} × {fmtMeters(scenario.orebody.height, 0)}
              </dd>
              <dt className="break-words text-mute">Nominal thickness</dt>
              <dd className="break-words">{fmtMeters(scenario.orebody.thickness, 0)}</dd>
              <dt className="break-words text-mute">
                Morphology
                <span className="block text-[10px] leading-tight">synthetic, irregular</span>
              </dt>
              <dd className="break-words">{morphologySummary(scenario.orebody.warpedVein)}</dd>
            </>
          ) : (
            <>
              <dt className="break-words text-mute">Thickness</dt>
              <dd className="break-words">{fmtMeters(scenario.orebody.thickness, 0)}</dd>
            </>
          )}
          {/* the synthetic-RMR disclaimer is kept in full on its own line;
              it is never abbreviated to a misleading "RMR" */}
          <dt className="break-words text-mute">
            Rock quality
            <span className="block text-[10px] leading-tight">synthetic RMR-like, 0-100</span>
          </dt>
          <dd className="break-words">
            {scenario.geology.rockQuality.mean} ± {scenario.geology.rockQuality.std}
          </dd>
          <dt className="break-words text-mute">Faults</dt>
          <dd className="break-words">{scenario.geology.faults.length}</dd>
          {/* Phase 18: numerical field spacing — never a "Block" size or a
              mining-unit setting (rule 127) */}
          <dt className="break-words text-mute">
            Field sampling
            <span className="block text-[10px] leading-tight">numerical spacing</span>
          </dt>
          <dd className="break-words">
            {scenario.fieldSampling.spacingX} × {scenario.fieldSampling.spacingY} ×{' '}
            {scenario.fieldSampling.spacingZ} m
          </dd>
          <dt className="break-words text-mute">Max grade</dt>
          <dd className="break-words">{(scenario.ramp.maxGradient * 100).toFixed(0)} %</dd>
          <dt className="break-words text-mute">Min radius</dt>
          <dd className="break-words">{fmtMeters(scenario.ramp.minTurnRadius, 0)}</dd>
        </dl>
      ) : (
        <p className="text-[11px] text-mute">
          No scenario loaded. Create one, then generate its world.
        </p>
      )}
    </>
  )
}
