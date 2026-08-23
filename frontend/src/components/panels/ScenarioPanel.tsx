import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, ApiError } from '@/api/client'
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
  const [seed, setSeed] = useState(42)
  const [withFault, setWithFault] = useState(true)

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

  const create = useMutation({
    mutationFn: () =>
      api.createScenario({
        name,
        seed,
        ...(withFault
          ? {
              geology: {
                rockQuality: {
                  mean: 65,
                  std: 12,
                  correlationLengthXy: 80,
                  correlationLengthZ: 40,
                  minimum: 20,
                  maximum: 90,
                },
                faults: [
                  {
                    origin: { x: -100, y: -200, z: 0 },
                    strikeDeg: 120,
                    dipDeg: 65,
                    coreHalfWidth: 2.5,
                    influenceHalfWidth: 20,
                    corePenalty: 50,
                    damageZonePenalty: 10,
                  },
                ],
              },
            }
          : {}),
      }),
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

  const error = create.error ?? load.error ?? generate.error
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
        <div className="mb-3 grid grid-cols-[1fr_auto] items-end gap-2">
          <label className="block">
            <span className="mb-1 block text-[11px] text-chalk-dim">Seed</span>
            <input
              type="number"
              value={seed}
              onChange={(e) => setSeed(Number(e.target.value))}
              className={`readout ${input}`}
            />
          </label>
          <label className="flex items-center gap-2 pb-1 text-[11px] text-chalk-dim">
            <input
              type="checkbox"
              checked={withFault}
              onChange={(e) => setWithFault(e.target.checked)}
              className="accent-lamp"
            />
            one fault
          </label>
        </div>
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
            <dt className="text-mute">Rock quality</dt>
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
