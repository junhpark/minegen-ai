/**
 * Phase 22C §19 — frontend isolation of the Analysis workspace, asserted on
 * the container source (the wiring lives in react-query hooks that need a
 * store and a client; the live requests are observed in the browser
 * acceptance run):
 *
 * - every query is keyed on the scenario epoch + scenario id / scene identity
 *   (a response of scenario A can never populate scenario B), and the two
 *   economics-dependent queries also on the economics revision;
 * - the Rules tab reads the SAME `design-assessment` cache entry as the Layout
 *   panel (one read model, no second evaluator, no second request key);
 * - saving the economics is exactly ONE PUT that reloads the analysis and the
 *   layout comparison and nothing else: no epoch increment, no scene clear,
 *   no scenario mutation, no derived invalidation.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const read = (p: string) => readFileSync(join(__dirname, p), 'utf8')
const unique = (src: string, re: RegExp) => [...new Set(src.match(re) ?? [])].sort()

const panel = read('AnalysisPanel.tsx')
const layout = read('LayoutPanel.tsx')

describe('Analysis queries are scenario-scoped', () => {
  it('calls exactly the six read endpoints, the one economics PUT and the one what-if POST', () => {
    expect(unique(panel, /api\.[a-zA-Z0-9]+/g)).toEqual([
      'api.getAnalysis',
      'api.getDesignAssessment',
      'api.getEconomicsConfig',
      'api.getLayoutComparison',
      'api.getSensitivity',
      'api.getTimeseries',
      'api.postWhatIf',
      'api.putEconomicsConfig',
    ])
    expect((panel.match(/api\.putEconomicsConfig/g) ?? []).length).toBe(1)
    // hardening PR-2 H3 §8.3: the what-if is a projection — the ONE POST, no
    // invalidation, no persistence (its answer lives in the mutation state)
    expect((panel.match(/api\.postWhatIf/g) ?? []).length).toBe(1)
    const start = panel.indexOf('const whatIf = useMutation(')
    const block = panel.slice(start, panel.indexOf('\n  })', start))
    expect(block).not.toContain('invalidateQueries')
    expect(block).not.toContain('setQueryData')
  })

  it('keys every query on the epoch and the scenario / scene identity', () => {
    expect(panel).toContain("queryKey: ['economics-config', epoch, scenarioId]")
    expect(panel).toContain(
      "queryKey: ['mine-analysis', epoch, scenarioId, ...assessmentKey(scene), revision]",
    )
    expect(panel).toContain(
      "queryKey: ['layout-comparison', epoch, scenarioId, ...assessmentKey(scene), revision]",
    )
    expect(panel).toContain("queryKey: ['design-assessment', epoch, ...assessmentKey(scene)]")
    expect(panel).toContain(
      "queryKey: ['analysis-sensitivity', epoch, scenarioId, ...assessmentKey(scene), revision]",
    )
    // the time series shares the 4D results card's cache entry (one read model)
    const seriesKey = "queryKey: ['analysis-timeseries', epoch, scenarioId, timelineRevision]"
    expect(panel).toContain(seriesKey)
    expect(read('../timeline/FourDResults.tsx')).toContain(seriesKey)
  })

  it('the Rules tab shares the Layout panel’s design-assessment cache entry', () => {
    const key = "queryKey: ['design-assessment', epoch, ...assessmentKey(scene)]"
    expect(layout).toContain(key)
    expect(panel).toContain(key)
    expect(panel).toContain("queryFn: () => api.getDesignAssessment(scene?.scenarioId ?? '')")
    // no second evaluator anywhere in the analysis presentation
    for (const file of [
      'RulebookPanel.tsx',
      'rulebook.ts',
      'LayoutComparisonPanel.tsx',
      'SensitivityPanel.tsx',
      'SchedulePanel.tsx',
    ]) {
      const src = read(file)
      expect(src).not.toMatch(/api\./)
      expect(src).not.toMatch(/useQuery|useMutation/)
      expect(src).not.toMatch(/\.sort\(/) // never re-sorted on the client
    }
  })
})

describe('saving the economics is one PUT with a bounded effect', () => {
  it('reloads the analysis and the layout comparison only', () => {
    const start = panel.indexOf('onSuccess:')
    const onSuccess = panel.slice(start, panel.indexOf('\n    },', start))
    expect(onSuccess).toContain("qc.setQueryData(['economics-config', epoch, scenarioId], saved)")
    expect(onSuccess).toContain("qc.invalidateQueries({ queryKey: ['mine-analysis'] })")
    expect(onSuccess).toContain("qc.invalidateQueries({ queryKey: ['layout-comparison'] })")
    expect(onSuccess).toContain("qc.invalidateQueries({ queryKey: ['analysis-timeseries'] })")
    expect(onSuccess).toContain("qc.invalidateQueries({ queryKey: ['analysis-sensitivity'] })")
    expect(onSuccess).not.toContain("'design-assessment'") // rules are not economics-dependent
  })

  it('never touches the scenario epoch, the scene or a derived artifact', () => {
    for (const forbidden of [
      'activateScenarioRevision',
      'selectScenario',
      'setScene',
      'applyScene',
      'clearScene',
      'setLayerVisible',
      'afterLayout',
      'Regen(',
      'generateWorld',
      'replaceScenario',
    ]) {
      expect(panel).not.toContain(forbidden)
    }
  })
})
