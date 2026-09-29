/**
 * Phase 23C — isolation of the Simulation Results feature, asserted on the
 * sources: the container talks to exactly the result endpoints, the frame
 * controller to exactly the frame / geometry endpoints, both keyed per the
 * directive; importing / deleting refreshes the results list ONLY (no epoch
 * bump, no scene clear, no derived invalidation); the presentation body and
 * the scene layers issue no request and compute no simulation quantity;
 * the overlays never mount in the walkthrough.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { LAYER_IDS } from '@/types/enums'
import { useViewerStore } from '@/stores/viewerStore'

const read = (p: string) => readFileSync(join(__dirname, p), 'utf8')
const unique = (src: string, re: RegExp) => [...new Set(src.match(re) ?? [])].sort()

const panel = read('SimulationResultsPanel.tsx')
const body = read('SimulationResultsBody.tsx')
const controller = read('../../results/SimulationOverlayController.tsx')
const ventLayer = read('../../scene/VentilationResultLayer.tsx')
const opsLayer = read('../../scene/OperationsResultLayer.tsx')
const scene = read('../../scene/MineScene.tsx')
const analysis = read('AnalysisPanel.tsx')

const FORBIDDEN = [
  'activateScenarioRevision',
  'activateScenario(',
  'selectScenario',
  'setScene',
  'applyScene',
  'clearScene',
  'setLayerVisible',
  'afterLayout',
  'Regen(',
  'generateWorld',
  'replaceScenario',
  'useTimelineStore',
  'setCurrentDay',
]

describe('Simulation Results container', () => {
  it('calls exactly the result endpoints', () => {
    expect(unique(panel, /api\.[a-zA-Z0-9]+/g)).toEqual([
      'api.deleteSimulationResult',
      'api.exportSimulationResult',
      'api.importSimulationResult',
      'api.listSimulationResults',
    ])
    expect(panel).toContain("queryKey: ['simulation-results', scenarioId]")
  })

  it('import and delete refresh the results list only', () => {
    expect(
      (
        panel.match(/invalidateQueries\(\{ queryKey: \['simulation-results', scenarioId\] \}\)/g) ??
        []
      ).length,
    ).toBe(2)
    expect(panel).not.toMatch(/invalidateQueries\(\{ queryKey: \['(?!simulation-results)/)
    for (const f of FORBIDDEN) expect(panel).not.toContain(f)
  })

  it('the Analysis read panel is untouched by the results feature', () => {
    expect(analysis).not.toContain('SimulationResult')
    expect(analysis).not.toContain('resultsStore')
  })
})

describe('overlay data controller', () => {
  it('reads exactly the geometry and frame endpoints under the directive keys', () => {
    expect(unique(controller, /api\.[a-zA-Z0-9]+/g)).toEqual([
      'api.getOperationsFrame',
      'api.getSimulationResultGeometry',
      'api.getVentilationFrame',
    ])
    expect(controller).toContain("queryKey: ['simulation-result', scenarioId, ventId, 'geometry']")
    expect(controller).toContain(
      "queryKey: ['simulation-result-frame', scenarioId, ventId, ventMetric, ventT]",
    )
    expect(controller).toContain(
      "queryKey: ['simulation-result-frame', scenarioId, opsId, 'operations', opsT]",
    )
    for (const f of FORBIDDEN) expect(controller).not.toContain(f)
  })

  it('commits a ventilation frame only for the selected metric (B2)', () => {
    expect(controller).toContain(
      'placeholderData: (prev) => ventilationPlaceholder(prev, ventMetric)',
    )
    expect(controller).toContain('ventilationFrameMatches(frame, ventId, ventMetric)')
    // the only bare placeholder is the OPERATIONS frame (its query key carries no metric)
    const bare = controller.indexOf('placeholderData: (prev) => prev,')
    expect(bare).toBeGreaterThan(controller.indexOf("'operations', opsT]"))
    expect(controller.indexOf('placeholderData: (prev) => prev,', bare + 1)).toBe(-1)
    // the selectors render the CARRIED metrics only
    expect(body).toContain('{c.metrics.map((m) => (')
    expect(body).not.toContain('VENTILATION_METRICS.map')
    expect(body).not.toContain('OPERATIONS_EDGE_METRICS.map')
    expect(panel).toContain('availableVentilationMetrics(r)')
    expect(panel).toContain('availableOperationsMetrics(r)')
  })
})

describe('presentation and layers compute nothing', () => {
  it('the body and the layers issue no request and hold no query', () => {
    for (const src of [body, ventLayer, opsLayer]) {
      expect(src).not.toMatch(/api\./)
      expect(src).not.toMatch(/useQuery|useMutation|fetch\(/)
      for (const f of FORBIDDEN) expect(src).not.toContain(f)
    }
    // no interpolation across edges, no route, no solver on the client
    for (const src of [ventLayer, opsLayer, controller]) {
      expect(src).not.toMatch(/dijkstra|shortestPath|interpolateRoute/i)
    }
  })

  it('the overlays are separate layers gated by the derived visibility set', () => {
    for (const id of ['ventilationResult', 'operationsHeatmap', 'operationsVehicles'] as const) {
      expect(LAYER_IDS).toContain(id)
      expect(useViewerStore.getState().visibleLayers.has(id)).toBe(true)
      expect(scene).toContain(`visible.has('${id}')`)
    }
    expect(scene).toContain('<VentilationResultLayer overlay={ventilationOverlay} />')
    expect(scene).toContain('<OperationsResultLayer')
    // the walkthrough authority set never contains a result overlay
    const readiness = read('../../walkthrough/readiness.ts')
    expect(readiness).not.toContain('ventilationResult')
    expect(readiness).not.toContain('operationsVehicles')
  })
})
