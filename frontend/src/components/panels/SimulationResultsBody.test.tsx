/**
 * Phase 23C — the Simulation Results workspace is a pure display of the
 * backend result list and frames: compatibility badges and the STALE
 * wording, import controls with a loading state, the metric selector, the
 * result clock (its OWN axis, "Mine day 12.5" for MINE_DAY), the legend
 * (name, unit, min, max) and the overlay toggles.
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { STALE_TEXT } from '@/results/format'
import {
  GEOMETRY,
  OPS_FRAME,
  OPS_SUMMARY,
  VENT_FRAME,
  VENT_PRESSURE_ONLY,
  VENT_STALE,
  VENT_SUMMARY,
} from '@/results/results.fixture'
import {
  IMPORT_INFO,
  NO_RESULTS_TEXT,
  SimulationResultsBody,
  type SimulationResultsBodyProps,
} from './SimulationResultsBody'

const noop = () => undefined

function props(over: Partial<SimulationResultsBodyProps> = {}): SimulationResultsBodyProps {
  return {
    scenarioId: 'scn-a',
    results: [VENT_SUMMARY, VENT_STALE, OPS_SUMMARY],
    listError: null,
    listLoading: false,
    importTarget: 'VENTSIM',
    importing: false,
    importError: null,
    importNotice: null,
    deleting: null,
    deleteError: null,
    exportError: null,
    activeVentilationResultId: null,
    activeOperationsResultId: null,
    ventilation: {
      metric: 'airflowM3s',
      metrics: ['airflowM3s'],
      time: 0,
      axis: VENT_SUMMARY.timeAxis,
      range: null,
      showArrows: true,
      frame: VENT_FRAME,
      error: null,
      onMetric: noop,
      onTime: noop,
      onRange: noop,
      onShowArrows: noop,
    },
    operations: {
      metric: 'utilization',
      metrics: ['utilization'],
      time: 12.5,
      axis: OPS_SUMMARY.timeAxis,
      range: null,
      playing: false,
      speed: 10,
      frame: OPS_FRAME,
      error: null,
      onMetric: noop,
      onTime: noop,
      onRange: noop,
      onPlay: noop,
      onPause: noop,
      onSpeed: noop,
    },
    onImportTarget: noop,
    onImportFile: noop,
    onActivate: noop,
    onDeactivate: noop,
    onDelete: noop,
    onExport: noop,
    ...over,
  }
}
const render = (over: Partial<SimulationResultsBodyProps> = {}) =>
  renderToStaticMarkup(<SimulationResultsBody {...props(over)} />)

describe('Simulation Results body', () => {
  it('needs a scenario, then lists every result with its compatibility', () => {
    expect(render({ scenarioId: null })).toContain('Load a scenario')
    const html = render()
    expect(html).toContain('Base case')
    expect(html).toContain('Fleet 4')
    expect(html).toContain('Ventsim result') // the unlabelled stale one
    expect(html.match(/Compatible/g)?.length).toBe(2)
    expect(html).toContain('Stale')
    expect(html).toContain(STALE_TEXT)
    expect(html).toContain('Ventilation · Ventsim · Static · 2 edges')
    expect(html).toContain('Operations · AnyLogic · Mine day (40 times) · 3 edges · 4 vehicles')
    expect(render({ results: [] })).toContain(NO_RESULTS_TEXT)
    expect(render({ results: null, listLoading: true })).toContain('Loading results')
    expect(render({ results: null, listError: 'RESULT_PACKAGE_INVALID: x' })).toContain(
      'RESULT_PACKAGE_INVALID: x',
    )
  })

  it('import controls: target select, .zip picker, loading state, typed error, info', () => {
    const html = render()
    expect(html).toContain('accept=".zip,application/zip"')
    expect(html).toContain('Ventsim — ventilation')
    expect(html).toContain('AnyLogic — operations')
    expect(html).toContain('MineResult 1.0')
    expect(render({ importing: true })).toContain('Importing and binding the package')
    expect(render({ importing: true })).toContain('disabled=""')
    expect(render({ importError: 'RESULT_SOURCE_SNAPSHOT_MISMATCH: differs' })).toContain(
      'RESULT_SOURCE_SNAPSHOT_MISMATCH: differs',
    )
    expect(IMPORT_INFO).toContain('computes no simulation quantity')
    expect(IMPORT_INFO).toContain('STALE')
  })

  it('a STALE result can be exported and deleted but never overlaid', () => {
    const html = render()
    const stale = html.slice(html.indexOf(`result-${VENT_STALE.resultId}`))
    const card = stale.slice(0, stale.indexOf('</section>'))
    expect(card).toContain('Export')
    expect(card).toContain('Delete')
    expect(card).toMatch(/<button[^>]*disabled=""[^>]*>Show overlay<\/button>/)
    expect(card).not.toContain('Hide overlay')
  })

  it('the active ventilation result shows the metric selector, arrows toggle and legend', () => {
    const html = render({ activeVentilationResultId: VENT_SUMMARY.resultId })
    expect(html).toContain('Hide overlay')
    expect(html).toContain('data-testid="ventilation-controls"')
    expect(html).toContain('Airflow (m3/s)')
    // B2: the selector offers ONLY the metrics the result carries
    expect(html).not.toContain('Air density (kg/m3)')
    expect(html).not.toContain('Pressure (Pa)')
    expect(html).toContain('airflow direction arrows (positive = sourceNode → targetNode)')
    expect(html).toContain('data-testid="result-legend"')
    expect(html).toContain('Airflow <span class="text-mute">(m3/s)</span>')
    expect(html).toContain('frame -8.50 … -8.50')
    expect(html).toContain('1 edges with a value · 1 without')
    expect(html).toContain('static (no time axis)')
    // no operations controls leak into a ventilation card
    expect(html).not.toContain('data-testid="operations-controls"')
  })

  it('the active operations result shows the heatmap metric, the result clock and playback', () => {
    const html = render({ activeOperationsResultId: OPS_SUMMARY.resultId })
    expect(html).toContain('data-testid="operations-controls"')
    expect(html).toContain('Utilization (fraction)')
    expect(html).not.toContain('Travel time (s)') // not carried by the result
    expect(html).toContain('Mine day 12.5')
    expect(html).toContain('Mine day · Mine day 0.0 → Mine day 30.0 · 40 samples')
    expect(html).toContain('>Play<')
    expect(html).toContain('>10x<')
    expect(html).toContain('1 vehicles in frame · 1 edges with')
    expect(html).toContain('frame 0.40 … 0.40')
    expect(
      render({
        activeOperationsResultId: OPS_SUMMARY.resultId,
        operations: { ...props().operations, playing: true },
      }),
    ).toContain('>Pause<')
  })

  it('an overlay refusal is shown verbatim and a missing frame reads as loading', () => {
    const html = render({
      activeVentilationResultId: VENT_SUMMARY.resultId,
      ventilation: { ...props().ventilation, frame: null, error: 'RESULT_STALE: older snapshot' },
    })
    expect(html).toContain('RESULT_STALE: older snapshot')
    expect(html).not.toContain('Loading frame')
    expect(
      render({
        activeVentilationResultId: VENT_SUMMARY.resultId,
        ventilation: { ...props().ventilation, frame: null },
      }),
    ).toContain('Loading frame')
    expect(GEOMETRY.edges.length).toBe(2)
  })
})

describe('metric authority (B2)', () => {
  it('a pressure-only result offers Pressure alone and no airflow arrows toggle', () => {
    const html = render({
      results: [VENT_PRESSURE_ONLY],
      activeVentilationResultId: VENT_PRESSURE_ONLY.resultId,
      ventilation: {
        ...props().ventilation,
        metric: 'pressurePa',
        metrics: ['pressurePa'],
        frame: null,
      },
    })
    expect(html).toContain('>Pressure (Pa)</option>')
    expect(html).not.toContain('Airflow (m3/s)')
    expect(html).not.toContain('airflow direction arrows')
    expect(html).toContain('Loading frame')
  })

  it('a frame of another metric is never shown under the selected metric label', () => {
    const html = render({
      activeVentilationResultId: VENT_SUMMARY.resultId,
      ventilation: {
        ...props().ventilation,
        metric: 'pressurePa',
        metrics: ['airflowM3s', 'pressurePa'],
        frame: VENT_FRAME, // an AIRFLOW frame
      },
    })
    expect(html).not.toContain('data-testid="result-legend"')
    expect(html).not.toContain('Pressure <span class="text-mute">(m3/s)</span>')
    expect(html).toContain('Loading frame')
  })
})
