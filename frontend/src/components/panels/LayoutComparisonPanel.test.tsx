/**
 * Phase 22C — the Layout comparison tab is a pure display of the backend
 * comparison (rules 204–206): persisted ranking order, backend costs, the
 * engineering rank and the comparable cost visually separate, no economic
 * recommendation vocabulary, NOT_CONFIGURED shown honestly.
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { AnalysisPanelBody, type AnalysisPanelBodyProps } from './AnalysisPanel'
import { CONFIG, FULL } from './analysis.fixture'
import {
  CONFIGURED,
  INACTIVE,
  NO_CATALOGUE,
  NOT_CONFIGURED,
  RANK2,
  RANK3,
  WINNER,
} from './layoutComparison.fixture'
import {
  COST_NOT_CONFIGURED_TEXT,
  INACTIVE_LAYOUT_TEXT,
  INCLUDED_BASIS_TEXT,
  LayoutComparisonBody,
} from './LayoutComparisonPanel'

const render = (payload = CONFIGURED, error: string | null = null) =>
  renderToStaticMarkup(<LayoutComparisonBody payload={payload} error={error} loading={false} />)

function rowsInOrder(html: string): string[] {
  const start = html.indexOf('data-testid="layout-comparison-table"')
  const table = html.slice(start, html.indexOf('</table>', start))
  return [...table.matchAll(/data-candidate-id="([^"]+)"/g)].map((m) => m[1] ?? '')
}

const FORBIDDEN = [
  'Recommended',
  'recommended',
  'Optimal',
  'optimal layout',
  'Best option',
  'best option',
  'Economic winner',
  'economic winner',
  'bankable',
  'feasible project',
  'economically viable',
  'profitable',
  'Total Mine Development Cost',
  'cheapest',
  'NPV ',
]

describe('Layout comparison — configured', () => {
  it('shows the rows in the persisted ranking order although cost disagrees', () => {
    const html = render()
    // rank 3 is the least expensive and rank 2 the most: order stays 1, 2, 3
    expect(rowsInOrder(html)).toEqual([WINNER, RANK2, RANK3])
    expect(html).toContain('#1')
    expect(html).toContain('#2')
    expect(html).toContain('#3')
  })

  it('renders the backend costs and lengths as given (formula is the backend’s)', () => {
    const html = render()
    expect(html).toContain('USD 11,000') // winner comparable cost
    expect(html).toContain('USD 16,500') // selected (rank 2)
    expect(html).toContain('USD 8,500') // rank 3
    expect(html).toContain('1,000 m')
    expect(html).toContain('200 m')
    expect(html).toContain('USD 10,000') // ramp cost
    expect(html).toContain('USD 1,000') // access cost
    expect(html).toContain('+USD 5,500') // Δ vs winner, rank 2
    expect(html).toContain('−USD 2,500') // Δ vs winner, rank 3
    expect(html).toContain('USD 10/m ramp')
    expect(html).toContain('USD 5/m access')
  })

  it('keeps the engineering rank and the comparable cost as separate readouts', () => {
    const html = render()
    expect(html).toContain('Ranking winner (engineering rank #1)')
    expect(html).toContain('Selected candidate')
    expect(html).toContain('(engineering rank #2)')
    expect(html).toContain('Comparable feasible candidates')
    expect(html).toContain('>3<')
    expect(html).toContain(INCLUDED_BASIS_TEXT)
    expect(html).toContain('Main ramp + level access only')
    expect(html).toContain('data-winner="true"')
    expect(html).toContain('data-selected="true"')
    // the winner row is marked ●, the selected row "(selected)", never a verdict
    expect(html).toContain('● ')
    expect(html).toContain('(selected)')
  })

  it('carries the backend disclaimer and the excluded cost kinds, and no forbidden vocabulary', () => {
    const html = render()
    expect(html).toContain('data-testid="layout-comparison-disclaimer"')
    expect(html).toContain('Comparable layout development cost includes only')
    expect(html).toContain('DRIFT, CROSSCUT, RAISE, SHAFT')
    for (const word of FORBIDDEN) expect(html).not.toContain(word)
  })

  it('shows the scores in Details with plain deltas and draws the optional bars', () => {
    const html = render()
    expect(html).toContain('aria-label="scores"')
    expect(html).toContain('4.521')
    expect(html).toContain('+0.107')
    expect(html).toContain('data-testid="cost-bars"')
    expect((html.match(/<rect/g) ?? []).length).toBe(3)
  })
})

describe('Layout comparison — availability', () => {
  it('NOT_CONFIGURED keeps the geometry facts and shows no cost number', () => {
    const html = render(NOT_CONFIGURED)
    expect(html).toContain('Not configured')
    expect(html).toContain(COST_NOT_CONFIGURED_TEXT)
    expect(html).toContain('data-testid="cost-not-configured"')
    expect(rowsInOrder(html)).toEqual([WINNER, RANK2, RANK3])
    expect(html).toContain('1,000 m')
    expect(html).toContain('1,500 m')
    expect(html).not.toContain('USD')
    expect(html).not.toContain('11,000')
    expect(html).not.toContain('data-testid="cost-bars"')
    expect(html).toContain('not configured')
  })

  it('INACTIVE_LAYOUT_V2 says so explicitly and keeps the rows', () => {
    const html = render(INACTIVE)
    expect(html).toContain(INACTIVE_LAYOUT_TEXT)
    expect(rowsInOrder(html)).toEqual([WINNER, RANK2, RANK3])
  })

  it('NOT_AVAILABLE shows the backend reason and no table', () => {
    const html = render(NO_CATALOGUE)
    expect(html).toContain('layout-v2 catalogue not generated')
    expect(html).toContain('Not available')
    expect(html).not.toContain('data-testid="layout-comparison-table"')
    expect(html).not.toContain(INACTIVE_LAYOUT_TEXT)
  })

  it('a typed refusal is named, never guessed around', () => {
    const html = render(CONFIGURED, 'ARTIFACT_MALFORMED: layout_v2.json …')
    expect(html).toContain('layout comparison unavailable — ARTIFACT_MALFORMED')
    expect(html).not.toContain('data-testid="layout-comparison-table"')
  })
})

describe('Layout comparison inside the Analysis panel', () => {
  const props = (over: Partial<AnalysisPanelBodyProps>): AnalysisPanelBodyProps => ({
    view: 'LAYOUT_COMPARISON',
    scenarioId: 'scn-a',
    analysis: FULL,
    analysisError: null,
    loading: false,
    assessment: null,
    assessmentError: null,
    assessmentLoading: false,
    layoutComparison: CONFIGURED,
    layoutComparisonError: null,
    layoutComparisonLoading: false,
    economicsConfig: { configured: true, revision: 'e', config: CONFIG },
    economicsError: null,
    activeMethod: 'LONGHOLE_OPEN_STOPING',
    saving: false,
    saveError: null,
    onSave: () => undefined,
    ...over,
  })

  it('the tab renders the comparison and none of the other tabs’ content', () => {
    const html = renderToStaticMarkup(<AnalysisPanelBody {...props({})} />)
    expect(html).toContain('data-testid="layout-comparison-table"')
    expect(html).not.toContain('Planning NPV')
    expect(html).not.toContain('data-testid="rulebook-table"')
    expect(html).not.toContain('Planned mined tonnes')
  })

  it('an analysis error never hides the comparison tab (independent queries)', () => {
    const html = renderToStaticMarkup(
      <AnalysisPanelBody
        {...props({ analysis: null, analysisError: 'ANALYSIS_SOURCE_INCONSISTENT: x' })}
      />,
    )
    expect(html).toContain('data-testid="layout-comparison-table"')
    expect(html).not.toContain('ANALYSIS_SOURCE_INCONSISTENT')
  })
})
