import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, ApiError } from '@/api/client'
import { AdvancedScenarioEditor } from '@/scenario/AdvancedScenarioEditor'
import {
  DEFAULT_BUILDER,
  faultCountEnabled,
  realizeRequest,
  realizedSummary,
} from '@/scenario/builder'
import { SCENARIO_PRESETS, type ScenarioCreate, type ScenarioPreset } from '@/types/api'
import { PanelSection } from '@/components/layout/PanelSection'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useSliceStore } from '@/stores/sliceStore'
import { fmtMeters } from '@/utils/format'

/**
 * Scenario creation / selection and world generation. Parameters shown here
 * are echoed from the backend document, not computed.
 */
export function ScenarioPanel() {
  const qc = useQueryClient()
  const scenario = useScenarioStore((s) => s.scenario)
  const scene = useScenarioStore((s) => s.scene)
  const setScenario = useScenarioStore((s) => s.setScenario)
  const setScene = useScenarioStore((s) => s.setScene)
  const setSlice = useSliceStore((s) => s.setSlice)
  const [name, setName] = useState('Synthetic Gold Mine 001')
  const [seed, setSeed] = useState(DEFAULT_BUILDER.seed)
  const [preset, setPreset] = useState<ScenarioPreset>(DEFAULT_BUILDER.preset)
  const [faultCount, setFaultCount] = useState(DEFAULT_BUILDER.faultCount)
  // realized = the untouched backend realization; draft = the editable
  // document the user will actually persist (Phase 17 acceptance, rule 124)
  const [realized, setRealized] = useState<ScenarioCreate | null>(null)
  const [draft, setDraft] = useState<ScenarioCreate | null>(null)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  // Phase 17 (rule 119): the panel never draws random numbers — it asks the
  // backend to realize preset+seed and shows/creates the result verbatim

  const list = useQuery({ queryKey: ['scenarios'], queryFn: api.listScenarios })

  const loadScene = async (id: string) => {
    try {
      const sc = await api.getScene(id)
      setScene(sc)
      setSlice(null)
    } catch (e) {
      if (e instanceof ApiError && e.code === 'WORLD_NOT_GENERATED') {
        setScene(null)
        return
      }
      throw e
    }
  }

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

  const create = useMutation({
    mutationFn: async () => {
      // the edited draft is authoritative: never re-realize over user edits
      const resolved =
        draft ?? (await api.realizeScenario(realizeRequest({ preset, seed, faultCount })))
      return api.createScenario({ ...resolved, name })
    },
    onSuccess: (s) => {
      setScenario(s)
      setScene(null)
      void qc.invalidateQueries({ queryKey: ['scenarios'] })
    },
  })

  const load = useMutation({
    mutationFn: async (id: string) => {
      const s = await api.getScenario(id)
      setScenario(s)
      await loadScene(id)
      return s
    },
  })

  const generate = useMutation({
    mutationFn: async () => {
      if (!scenario) throw new Error('no scenario selected')
      await api.generateWorld(scenario.id)
      await loadScene(scenario.id)
    },
  })

  const error = realize.error ?? create.error ?? load.error ?? generate.error
  const errorText =
    error instanceof ApiError ? `${error.code}: ${error.message}` : error ? error.message : null

  const input =
    'w-full rounded-sm border border-rock-700 bg-rock-900 px-2 py-1 text-chalk focus:border-lamp focus:outline-none'

  return (
    <>
      <PanelSection title="Scenario" tag="Phase 02">
        <label className="mb-2 block">
          <span className="mb-1 block text-[11px] text-chalk-dim">Name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} className={input} />
        </label>
        <label className="mb-2 block">
          <span className="mb-1 block text-[11px] text-chalk-dim">Preset</span>
          <select
            value={preset}
            onChange={(e) => {
              setPreset(e.target.value as ScenarioPreset)
              invalidateDraft()
            }}
            className={input}
          >
            {SCENARIO_PRESETS.map((p) => (
              <option key={p} value={p}>
                {p === 'BASELINE'
                  ? 'Baseline (fixed reference mine)'
                  : p === 'RANDOM_TABULAR'
                    ? 'Randomized · tabular orebody'
                    : 'Randomized · ellipsoid orebody'}
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
              className={`readout ${input}`}
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
              className={`readout ${input} disabled:opacity-50`}
            />
          </label>
          <button
            type="button"
            onClick={() => realize.mutate()}
            disabled={realize.isPending}
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
        <button
          type="button"
          onClick={() => create.mutate()}
          disabled={create.isPending}
          className="plate w-full rounded-sm border border-rock-600 px-3 py-1.5 text-[13px] text-chalk hover:bg-rock-700 disabled:opacity-50"
        >
          {create.isPending ? 'Creating…' : 'New synthetic mine'}
        </button>

        <button
          type="button"
          onClick={() => generate.mutate()}
          disabled={!scenario || generate.isPending}
          className="plate mt-2 w-full rounded-sm bg-lamp px-3 py-1.5 text-[13px] text-rock-950 hover:bg-lamp-deep hover:text-chalk disabled:cursor-not-allowed disabled:opacity-40"
        >
          {generate.isPending ? 'Generating world…' : scene ? 'Regenerate world' : 'Generate world'}
        </button>

        {errorText ? (
          <p role="alert" className="mt-2 text-[11px] text-danger">
            {errorText}
          </p>
        ) : null}

        {list.isSuccess && list.data.length > 0 ? (
          <div className="mt-3">
            <span className="mb-1 block text-[11px] text-chalk-dim">Saved scenarios</span>
            <ul className="flex max-h-40 flex-col gap-1 overflow-y-auto">
              {list.data.map((s) => (
                <li key={s.id}>
                  <button
                    type="button"
                    onClick={() => load.mutate(s.id)}
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
          </div>
        ) : null}
      </PanelSection>

      <PanelSection title="Parameters">
        {scenario ? (
          <dl className="readout grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[11px]">
            <dt className="text-mute">World</dt>
            <dd>
              {scenario.world.sizeX} × {scenario.world.sizeY} m
            </dd>
            <dt className="text-mute">Model depth</dt>
            <dd>
              {fmtMeters(scenario.world.depth, 0)} below{' '}
              {fmtMeters(scenario.terrain.baseElevation, 0)}
            </dd>
            <dt className="text-mute">Orebody</dt>
            <dd>
              {scenario.orebody.orebodyType} · strike {scenario.orebody.strikeDeg}° · dip{' '}
              {scenario.orebody.dipDeg}°
            </dd>
            <dt className="text-mute">Thickness</dt>
            <dd>{fmtMeters(scenario.orebody.thickness, 0)}</dd>
            <dt className="text-mute">Rock quality (synthetic RMR-like, 0-100)</dt>
            <dd>
              {scenario.geology.rockQuality.mean} ± {scenario.geology.rockQuality.std}
            </dd>
            <dt className="text-mute">Faults</dt>
            <dd>{scenario.geology.faults.length}</dd>
            <dt className="text-mute">Block</dt>
            <dd>
              {scenario.blockModel.dx} × {scenario.blockModel.dy} × {scenario.blockModel.dz} m
            </dd>
            <dt className="text-mute">Max grade</dt>
            <dd>{(scenario.ramp.maxGradient * 100).toFixed(0)} %</dd>
            <dt className="text-mute">Min radius</dt>
            <dd>{fmtMeters(scenario.ramp.minTurnRadius, 0)}</dd>
          </dl>
        ) : (
          <p className="text-[11px] text-mute">
            No scenario loaded. Create one, then generate its world.
          </p>
        )}
      </PanelSection>
    </>
  )
}
