import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { PanelSection } from '@/components/layout/PanelSection'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useSliceStore } from '@/stores/sliceStore'
import { useViewerStore } from '@/stores/viewerStore'
import type { LayerId } from '@/types/enums'
import type { SliceAxis, SliceField } from '@/types/scene'
import { rampForField } from '@/utils/colormap'

interface LayerRow {
  id: LayerId
  label: string
  /** phase in which the layer gets content; disabled until then */
  phase: number
}

const LAYER_GROUPS: { title: string; rows: LayerRow[] }[] = [
  {
    title: 'World',
    rows: [
      { id: 'terrain', label: 'Terrain', phase: 2 },
      { id: 'orebody', label: 'Orebody', phase: 2 },
      { id: 'gradeBlocks', label: 'Grade blocks', phase: 2 },
      // §3: explicit opt-in viewer layer, default OFF
      { id: 'rockQuality', label: 'Field slice', phase: 2 },
      { id: 'faults', label: 'Faults', phase: 2 },
    ],
  },
  {
    title: 'Design',
    rows: [{ id: 'accessTargets', label: 'Access targets', phase: 3 }],
  },
  {
    title: 'Excavations',
    rows: [
      // §2: default OFF, and suppressed outright in 4D / TIMELINE_SNAPSHOT
      { id: 'rawSearchPath', label: 'Raw search path', phase: 4 },
      { id: 'smoothedDecline', label: 'Smoothed / effective decline', phase: 5 },
      { id: 'tunnelMesh', label: 'Tunnel mesh', phase: 6 },
      { id: 'ramp', label: 'Ramp', phase: 6 },
      { id: 'levels', label: 'Levels', phase: 8 },
      { id: 'crosscuts', label: 'Crosscuts', phase: 8 },
      { id: 'stopes', label: 'Stopes', phase: 9 },
      { id: 'backfill', label: 'Backfill', phase: 10 },
      { id: 'networkGraph', label: 'Network graph', phase: 7 },
    ],
  },
  {
    title: 'Infrastructure',
    rows: [
      { id: 'routers', label: 'Routers', phase: 11 },
      { id: 'coverage', label: 'Communication coverage', phase: 11 },
      { id: 'sensors', label: 'Sensors', phase: 12 },
      { id: 'sensorCoverage', label: 'Monitoring coverage', phase: 12 },
    ],
  },
]

const CURRENT_PHASE = 4

const FIELDS: { id: SliceField; label: string }[] = [
  { id: 'rockQuality', label: 'Rock quality (synthetic RMR-like, 0-100)' },
  { id: 'grade', label: 'Grade' },
  { id: 'faultInfluence', label: 'Fault influence' },
  { id: 'faultZone', label: 'Fault zone' },
  { id: 'oreFraction', label: 'Ore fraction' },
]
const AXES: SliceAxis[] = ['x', 'y', 'z']

export function LayerPanel() {
  const visible = useViewerStore((s) => s.visibleLayers)
  const toggle = useViewerStore((s) => s.toggleLayer)

  return (
    <>
      <PanelSection title="Layers">
        {LAYER_GROUPS.map((g) => (
          <div key={g.title} className="mb-3 last:mb-0">
            <div className="readout mb-1 text-[10px] text-mute">{g.title}</div>
            <ul className="flex flex-col">
              {g.rows.map((r) => {
                const available = r.phase <= CURRENT_PHASE
                return (
                  <li key={r.id}>
                    <label
                      className={[
                        'flex items-center gap-2 rounded-sm px-1 py-0.5',
                        available ? 'text-chalk hover:bg-rock-700/60' : 'text-mute',
                      ].join(' ')}
                    >
                      <input
                        type="checkbox"
                        checked={visible.has(r.id)}
                        onChange={() => toggle(r.id)}
                        disabled={!available}
                        className="accent-lamp"
                      />
                      <span className="flex-1">{r.label}</span>
                      {!available ? (
                        <span className="readout text-[10px]">
                          P{String(r.phase).padStart(2, '0')}
                        </span>
                      ) : null}
                    </label>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
      </PanelSection>
      <SliceControls />
    </>
  )
}

/** Field / axis / index picker for the block-field slice layer. */
function SliceControls() {
  const scene = useScenarioStore((s) => s.scene)
  const { field, axis, index, slice, setField, setAxis, setIndex, setSlice } = useSliceStore()
  const scenarioId = scene?.scenarioId
  const shape = scene?.blockGrid.shape
  const axisIdx = axis === 'x' ? 0 : axis === 'y' ? 1 : 2
  const count = shape ? shape[axisIdx] : 0

  // start on the default slice shipped with the scene
  useEffect(() => {
    if (scene) {
      const d = scene.rockQuality.defaultSlice
      setField(d.field)
      setAxis(d.axis)
      setIndex(d.index)
      setSlice(d)
    }
  }, [scene, setField, setAxis, setIndex, setSlice])

  // Phase 17.1 §1/§3: slice COMPUTATION is independent of slice VISIBILITY —
  // the fetch runs whether or not the layer is on, and the layer renders only
  // when the user has enabled it. `placeholderData` keeps the slider smooth
  // WITHIN one scenario but must never carry scenario A's slice into B.
  const q = useQuery({
    queryKey: ['slice', scenarioId, field, axis, index],
    queryFn: () => api.getSlice(scenarioId as string, field, axis, index),
    enabled: Boolean(scenarioId) && count > 0,
    placeholderData: (prev, prevQuery) =>
      prevQuery?.queryKey[1] === scenarioId ? prev : undefined,
  })
  useEffect(() => {
    if (q.data) setSlice(q.data)
  }, [q.data, setSlice])

  if (!scene) return null
  const shown = slice ?? scene.rockQuality.defaultSlice
  const ramp = rampForField(shown.field)
  const stops = Array.from({ length: 12 }, (_, i) => ramp(i / 11))
  const gradient = `linear-gradient(90deg, ${stops
    .map(([r, g, b]) => `rgb(${Math.round(r * 255)},${Math.round(g * 255)},${Math.round(b * 255)})`)
    .join(',')})`
  const select =
    'readout rounded-sm border border-rock-700 bg-rock-900 px-1.5 py-1 text-[11px] text-chalk focus:border-lamp focus:outline-none'

  return (
    <PanelSection title="Field slice" tag={`${shown.axis} = ${shown.coordinate.toFixed(0)} m`}>
      <div className="mb-2 grid grid-cols-[1fr_auto] gap-2">
        <select
          value={field}
          onChange={(e) => setField(e.target.value as SliceField)}
          className={select}
        >
          {FIELDS.map((f) => (
            <option key={f.id} value={f.id}>
              {f.label}
            </option>
          ))}
        </select>
        <select
          value={axis}
          onChange={(e) => setAxis(e.target.value as SliceAxis)}
          className={select}
        >
          {AXES.map((a) => (
            <option key={a} value={a}>
              {a.toUpperCase()}
            </option>
          ))}
        </select>
      </div>
      <input
        type="range"
        min={0}
        max={Math.max(0, count - 1)}
        value={Math.min(index, Math.max(0, count - 1))}
        onChange={(e) => setIndex(Number(e.target.value))}
        className="w-full accent-lamp"
        aria-label="slice index"
      />
      <div className="mt-2 h-2 w-full rounded-sm" style={{ background: gradient }} aria-hidden />
      <div className="readout mt-1 flex justify-between text-[10px] text-chalk-dim">
        <span>{shown.min.toFixed(2)}</span>
        <span>{shown.field}</span>
        <span>{shown.max.toFixed(2)}</span>
      </div>
    </PanelSection>
  )
}
