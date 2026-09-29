import type { ChangeEvent, ReactNode } from 'react'
import { ActionButton } from '@/components/ui/ActionButton'
import { Disclosure } from '@/components/ui/Disclosure'
import { InfoPopover } from '@/components/ui/InfoPopover'
import { Metrics } from '@/components/ui/MetricRow'
import type { StatusTone } from '@/components/ui/presentation'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { displayRange, legendTicks, rgbToHex, rampRgb, type DisplayRange } from '@/results/colorScale'
import {
  APPLICATION_LABEL,
  COMPATIBILITY_LABEL,
  DOMAIN_LABEL,
  fmtValue,
  formatResultTime,
  OPERATIONS_METRIC_LABEL,
  OPERATIONS_METRIC_UNIT,
  resultTitle,
  snapshotShort,
  STALE_TEXT,
  timeAxisLabel,
  VENTILATION_METRIC_LABEL,
  VENTILATION_METRIC_UNIT,
} from '@/results/format'
import type { ResultSpeed } from '@/stores/resultsStore'
import {
  OPERATIONS_EDGE_METRICS,
  type OperationsEdgeMetric,
  type OperationsFrame,
  type ResultSummary,
  type ResultTimeAxis,
  type SourceApplication,
  VENTILATION_METRICS,
  type VentilationFrame,
  type VentilationMetric,
} from '@/types/results'

export const NO_RESULTS_TEXT = 'No simulation results imported for this scenario.'
export const IMPORT_INFO =
  'Export a Ventsim or AnyLogic package (Design › Network › Export), run the simulation, ' +
  'fill the roundtrip/ kit it contains and import the ZIP here. A result is bound to the ' +
  'mine snapshot the package was exported from: the import refuses another scenario or ' +
  'an older snapshot, and a stored result becomes STALE (kept, not overlaid) once the ' +
  'mine changes. MineGen computes no simulation quantity.'

export interface VentilationControls {
  metric: VentilationMetric
  time: number
  axis: ResultTimeAxis | null
  range: DisplayRange | null
  showArrows: boolean
  frame: VentilationFrame | null
  error: string | null
  onMetric: (m: VentilationMetric) => void
  onTime: (t: number) => void
  onRange: (r: DisplayRange | null) => void
  onShowArrows: (v: boolean) => void
}

export interface OperationsControls {
  metric: OperationsEdgeMetric
  time: number
  axis: ResultTimeAxis | null
  range: DisplayRange | null
  playing: boolean
  speed: ResultSpeed
  frame: OperationsFrame | null
  error: string | null
  onMetric: (m: OperationsEdgeMetric) => void
  onTime: (t: number) => void
  onRange: (r: DisplayRange | null) => void
  onPlay: () => void
  onPause: () => void
  onSpeed: (s: ResultSpeed) => void
}

export interface SimulationResultsBodyProps {
  scenarioId: string | null
  results: ResultSummary[] | null
  listError: string | null
  listLoading: boolean
  importTarget: SourceApplication
  importing: boolean
  importError: string | null
  importNotice: string | null
  deleting: string | null
  deleteError: string | null
  exportError: string | null
  activeVentilationResultId: string | null
  activeOperationsResultId: string | null
  ventilation: VentilationControls
  operations: OperationsControls
  onImportTarget: (t: SourceApplication) => void
  onImportFile: (file: File) => void
  onActivate: (r: ResultSummary) => void
  onDeactivate: (r: ResultSummary) => void
  onDelete: (r: ResultSummary) => void
  onExport: (r: ResultSummary) => void
}

function compatibilityTone(c: ResultSummary['compatibility']): StatusTone {
  return c === 'COMPATIBLE' ? 'READY' : 'FAILED'
}

const SPEEDS: ResultSpeed[] = [1, 10, 60]

function Legend({
  label,
  unit,
  range,
  frameMin,
  frameMax,
  manual,
  onRange,
}: {
  label: string
  unit: string
  range: DisplayRange | null
  frameMin: number | null
  frameMax: number | null
  manual: DisplayRange | null
  onRange: (r: DisplayRange | null) => void
}) {
  const gradient = `linear-gradient(to right, ${[0, 0.25, 0.5, 0.75, 1]
    .map((t) => rgbToHex(rampRgb(t)))
    .join(', ')})`
  return (
    <div className="mt-1.5 text-[11px]" data-testid="result-legend">
      <div className="flex items-center justify-between text-chalk-dim">
        <span>
          {label} <span className="text-mute">({unit})</span>
        </span>
        <span className="text-mute">
          frame {fmtValue(frameMin)} … {fmtValue(frameMax)}
        </span>
      </div>
      <div className="mt-1 h-2 w-full rounded-sm" style={{ background: gradient }} />
      {range ? (
        <div className="flex justify-between text-[10px] text-mute">
          {legendTicks(range).map((t, i) => (
            <span key={i}>{fmtValue(t)}</span>
          ))}
        </div>
      ) : (
        <div className="text-[10px] text-mute">no value in this frame — edges stay neutral</div>
      )}
      <div className="mt-1 flex items-center gap-1 text-[10px] text-mute">
        <span>display range</span>
        <input
          type="number"
          className="w-16 rounded-sm border border-rock-700 bg-rock-900 px-1 text-chalk"
          value={manual?.min ?? ''}
          placeholder={frameMin === null ? 'min' : fmtValue(frameMin)}
          onChange={(e) =>
            onRange({
              min: e.target.value === '' ? (frameMin ?? 0) : Number(e.target.value),
              max: manual?.max ?? frameMax ?? 1,
            })
          }
        />
        <span>…</span>
        <input
          type="number"
          className="w-16 rounded-sm border border-rock-700 bg-rock-900 px-1 text-chalk"
          value={manual?.max ?? ''}
          placeholder={frameMax === null ? 'max' : fmtValue(frameMax)}
          onChange={(e) =>
            onRange({
              min: manual?.min ?? frameMin ?? 0,
              max: e.target.value === '' ? (frameMax ?? 1) : Number(e.target.value),
            })
          }
        />
        {manual ? (
          <button type="button" className="text-lamp hover:underline" onClick={() => onRange(null)}>
            auto
          </button>
        ) : null}
      </div>
    </div>
  )
}

function Clock({
  axis,
  time,
  onTime,
  children,
}: {
  axis: ResultTimeAxis | null
  time: number
  onTime: (t: number) => void
  children?: ReactNode
}) {
  if (!axis || axis.kind === 'STATIC' || axis.start === null || axis.end === null) {
    return (
      <div className="mt-1.5 text-[11px] text-mute" data-testid="result-clock">
        {axis ? formatResultTime(axis.kind, null) : ''}
      </div>
    )
  }
  return (
    <div className="mt-1.5 text-[11px]" data-testid="result-clock">
      <div className="flex items-center gap-2">
        {children}
        <input
          type="range"
          min={axis.start}
          max={axis.end}
          step={(axis.end - axis.start) / 400 || 1}
          value={time}
          onChange={(e) => onTime(Number(e.target.value))}
          className="min-w-0 flex-1 accent-[#f2c14e]"
          aria-label="result clock"
        />
      </div>
      <div className="mt-0.5 flex justify-between text-[10px] text-mute">
        <span className="text-chalk-dim">{formatResultTime(axis.kind, time)}</span>
        <span>
          {timeAxisLabel(axis.kind)} · {formatResultTime(axis.kind, axis.start)} →{' '}
          {formatResultTime(axis.kind, axis.end)} · {axis.sampleCount} samples
        </span>
      </div>
    </div>
  )
}

function VentilationOverlayControls({ c }: { c: VentilationControls }) {
  const frameRange = displayRange(c.frame?.min ?? null, c.frame?.max ?? null, c.range)
  return (
    <div className="mt-1.5 border-t border-rock-700 pt-1.5" data-testid="ventilation-controls">
      <label className="flex items-center gap-2 text-[11px] text-chalk-dim">
        <span className="w-14 text-mute">Metric</span>
        <select
          className="flex-1 rounded-sm border border-rock-700 bg-rock-900 px-1 py-0.5 text-chalk"
          value={c.metric}
          onChange={(e) => c.onMetric(e.target.value as VentilationMetric)}
        >
          {VENTILATION_METRICS.map((m) => (
            <option key={m} value={m}>
              {VENTILATION_METRIC_LABEL[m]} ({VENTILATION_METRIC_UNIT[m]})
            </option>
          ))}
        </select>
      </label>
      <Clock axis={c.axis} time={c.time} onTime={c.onTime} />
      {c.metric === 'airflowM3s' ? (
        <label className="mt-1 flex items-center gap-2 text-[11px] text-chalk-dim">
          <input
            type="checkbox"
            className="accent-lamp"
            checked={c.showArrows}
            onChange={(e) => c.onShowArrows(e.target.checked)}
          />
          airflow direction arrows (positive = sourceNode → targetNode)
        </label>
      ) : null}
      {c.error ? <p className="mt-1 break-words text-[11px] text-danger">{c.error}</p> : null}
      {c.frame ? (
        <>
          <Legend
            label={VENTILATION_METRIC_LABEL[c.metric]}
            unit={c.frame.unit}
            range={frameRange}
            frameMin={c.frame.min}
            frameMax={c.frame.max}
            manual={c.range}
            onRange={c.onRange}
          />
          <div className="mt-1 text-[10px] text-mute">
            {c.frame.values.length} edges with a value · {c.frame.missingEdgeIds.length} without
            (neutral)
            {c.frame.sampleTime !== null ? ` · held sample ${fmtValue(c.frame.sampleTime, 1)}` : ''}
          </div>
        </>
      ) : c.error ? null : (
        <div className="mt-1 text-[10px] text-mute">Loading frame…</div>
      )}
    </div>
  )
}

function OperationsOverlayControls({ c }: { c: OperationsControls }) {
  const values = (c.frame?.edgeMetrics ?? [])
    .map((r) => r[c.metric])
    .filter((v): v is number => v !== null && Number.isFinite(v))
  const frameMin = values.length ? Math.min(...values) : null
  const frameMax = values.length ? Math.max(...values) : null
  const frameRange = displayRange(frameMin, frameMax, c.range)
  return (
    <div className="mt-1.5 border-t border-rock-700 pt-1.5" data-testid="operations-controls">
      <label className="flex items-center gap-2 text-[11px] text-chalk-dim">
        <span className="w-14 text-mute">Heatmap</span>
        <select
          className="flex-1 rounded-sm border border-rock-700 bg-rock-900 px-1 py-0.5 text-chalk"
          value={c.metric}
          onChange={(e) => c.onMetric(e.target.value as OperationsEdgeMetric)}
        >
          {OPERATIONS_EDGE_METRICS.map((m) => (
            <option key={m} value={m}>
              {OPERATIONS_METRIC_LABEL[m]} ({OPERATIONS_METRIC_UNIT[m]})
            </option>
          ))}
        </select>
      </label>
      <Clock axis={c.axis} time={c.time} onTime={c.onTime}>
        <button
          type="button"
          className="plate rounded-sm border border-edge px-2 py-0.5 text-[11px] hover:border-lamp"
          onClick={() => (c.playing ? c.onPause() : c.onPlay())}
        >
          {c.playing ? 'Pause' : 'Play'}
        </button>
        {SPEEDS.map((sp) => (
          <button
            key={sp}
            type="button"
            className={`plate rounded-sm border px-1.5 py-0.5 text-[10px] ${
              c.speed === sp ? 'border-lamp text-lamp' : 'border-edge text-mute hover:border-lamp'
            }`}
            onClick={() => c.onSpeed(sp)}
          >
            {sp}x
          </button>
        ))}
      </Clock>
      {c.error ? <p className="mt-1 break-words text-[11px] text-danger">{c.error}</p> : null}
      {c.frame ? (
        <>
          <Legend
            label={OPERATIONS_METRIC_LABEL[c.metric]}
            unit={OPERATIONS_METRIC_UNIT[c.metric]}
            range={frameRange}
            frameMin={frameMin}
            frameMax={frameMax}
            manual={c.range}
            onRange={c.onRange}
          />
          <div className="mt-1 text-[10px] text-mute">
            {c.frame.vehicles.length} vehicles in frame · {c.frame.edgeMetrics.length} edges with
            metrics
          </div>
        </>
      ) : c.error ? null : (
        <div className="mt-1 text-[10px] text-mute">Loading frame…</div>
      )}
    </div>
  )
}

function ResultCard({
  r,
  active,
  deleting,
  onActivate,
  onDeactivate,
  onDelete,
  onExport,
  children,
}: {
  r: ResultSummary
  active: boolean
  deleting: boolean
  onActivate: () => void
  onDeactivate: () => void
  onDelete: () => void
  onExport: () => void
  children?: ReactNode
}) {
  const stale = r.compatibility === 'STALE'
  const available = r.metrics.filter((m) => m.available)
  return (
    <section
      className={`min-w-0 overflow-hidden border-b border-rock-700 px-4 py-3 ${active ? 'bg-rock-900/40' : ''}`}
      data-testid={`result-${r.resultId}`}
    >
      <header className="mb-1 flex items-center justify-between gap-2">
        <h3 className="plate text-[12px] text-chalk">{resultTitle(r)}</h3>
        <StatusBadge tone={compatibilityTone(r.compatibility)} label={COMPATIBILITY_LABEL[r.compatibility]} />
      </header>
      <div className="readout break-words text-[11px] text-chalk-dim">
        {DOMAIN_LABEL[r.domain]} · {APPLICATION_LABEL[r.sourceApplication]} · {timeAxisLabel(r.timeAxis.kind)}
        {r.timeAxis.kind === 'STATIC' ? '' : ` (${r.timeAxis.sampleCount} times)`} · {r.counts.edgeCount}{' '}
        edges
        {r.domain === 'OPERATIONS' ? ` · ${r.counts.vehicleCount} vehicles` : ''}
      </div>
      {stale ? <p className="mt-1 text-[11px] text-danger">{STALE_TEXT}</p> : null}
      <div className="mt-1.5 flex min-w-0 gap-1.5">
        <div className="min-w-0 flex-1">
          {active ? (
            <ActionButton variant="secondary" onClick={onDeactivate}>
              Hide overlay
            </ActionButton>
          ) : (
            <ActionButton
              variant="primary"
              onClick={onActivate}
              disabled={stale}
              title={stale ? STALE_TEXT : undefined}
            >
              Show overlay
            </ActionButton>
          )}
        </div>
        <button
          type="button"
          className="plate shrink-0 rounded-sm border border-edge px-2 text-[11px] text-chalk-dim hover:border-lamp"
          onClick={onExport}
          title="Download the canonical MineResult 1.0 ZIP"
        >
          Export
        </button>
        <button
          type="button"
          className="plate shrink-0 rounded-sm border border-edge px-2 text-[11px] text-chalk-dim hover:border-danger disabled:opacity-40"
          onClick={onDelete}
          disabled={deleting}
        >
          {deleting ? 'Deleting…' : 'Delete'}
        </button>
      </div>
      {active ? children : null}
      <Disclosure label="Details">
        <Metrics
          rows={[
            { label: 'Result id', value: r.resultId },
            { label: 'MineResult', value: r.mineResultVersion },
            { label: 'Description', value: r.description || null },
            { label: 'Snapshot', value: snapshotShort(r) },
            { label: 'Samples', value: String(r.counts.sampleCount) },
            r.domain === 'OPERATIONS'
              ? { label: 'Edge metric samples', value: String(r.counts.edgeMetricSampleCount) }
              : null,
            {
              label: 'Metrics',
              value: available.length
                ? available.map((m) => `${m.name} (${m.unit}) ${fmtValue(m.min)}…${fmtValue(m.max)}`).join('; ')
                : 'none',
            },
          ]}
        />
      </Disclosure>
    </section>
  )
}

/** pure presentation — every value is a backend value */
export function SimulationResultsBody(p: SimulationResultsBodyProps) {
  if (p.scenarioId === null) {
    return (
      <p className="px-4 py-3 text-[11px] text-mute">
        Load a scenario to import and overlay simulation results.
      </p>
    )
  }
  const onFile = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) p.onImportFile(file)
    e.target.value = ''
  }
  return (
    <div data-testid="simulation-results" className="min-w-0 max-w-full overflow-x-hidden">
      <section className="border-b border-rock-700 px-4 py-3">
        <header className="mb-1.5 flex items-center justify-between gap-2">
          <h3 className="plate flex items-center gap-1.5 text-[12px] text-chalk">
            Import result
            <InfoPopover label="Import result">{IMPORT_INFO}</InfoPopover>
          </h3>
          <StatusBadge tone={p.importing ? 'RUNNING' : 'INACTIVE'} label={p.importing ? 'Importing' : 'MineResult 1.0'} />
        </header>
        <label className="flex items-center gap-2 text-[11px] text-chalk-dim">
          <span className="w-14 text-mute">Source</span>
          <select
            className="flex-1 rounded-sm border border-rock-700 bg-rock-900 px-1 py-0.5 text-chalk"
            value={p.importTarget}
            onChange={(e) => p.onImportTarget(e.target.value as SourceApplication)}
            disabled={p.importing}
          >
            <option value="VENTSIM">Ventsim — ventilation</option>
            <option value="ANYLOGIC">AnyLogic — operations</option>
          </select>
        </label>
        <label className="mt-1.5 block text-[11px] text-chalk-dim">
          <span className="text-mute">Package (.zip)</span>
          <input
            type="file"
            accept=".zip,application/zip"
            className="mt-0.5 block w-full max-w-full text-[11px]"
            onChange={onFile}
            disabled={p.importing}
            data-testid="result-file-input"
          />
        </label>
        {p.importing ? <p className="mt-1 text-[11px] text-mute">Importing and binding the package…</p> : null}
        {p.importError ? <p className="mt-1 break-words text-[11px] text-danger">{p.importError}</p> : null}
        {p.importNotice ? <p className="mt-1 text-[11px] text-chalk-dim">{p.importNotice}</p> : null}
      </section>
      {p.listError ? (
        <p className="break-words px-4 py-3 text-[11px] text-danger" data-testid="results-error">
          {p.listError}
        </p>
      ) : p.results === null ? (
        <p className="px-4 py-3 text-[11px] text-mute">{p.listLoading ? 'Loading results…' : ''}</p>
      ) : p.results.length === 0 ? (
        <p className="px-4 py-3 text-[11px] text-mute">{NO_RESULTS_TEXT}</p>
      ) : (
        p.results.map((r) => {
          const active =
            r.domain === 'VENTILATION'
              ? p.activeVentilationResultId === r.resultId
              : p.activeOperationsResultId === r.resultId
          return (
            <ResultCard
              key={r.resultId}
              r={r}
              active={active}
              deleting={p.deleting === r.resultId}
              onActivate={() => p.onActivate(r)}
              onDeactivate={() => p.onDeactivate(r)}
              onDelete={() => p.onDelete(r)}
              onExport={() => p.onExport(r)}
            >
              {r.domain === 'VENTILATION' ? (
                <VentilationOverlayControls c={p.ventilation} />
              ) : (
                <OperationsOverlayControls c={p.operations} />
              )}
            </ResultCard>
          )
        })
      )}
      {p.deleteError ? <p className="px-4 py-2 text-[11px] text-danger">{p.deleteError}</p> : null}
      {p.exportError ? <p className="px-4 py-2 text-[11px] text-danger">{p.exportError}</p> : null}
    </div>
  )
}
