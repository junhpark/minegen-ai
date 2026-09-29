/**
 * Phase 22A/B — the Analysis workspace is a pure display of the backend read
 * model: quantities, availabilities and economics are rendered as given, the
 * vocabulary stays planning vocabulary, and the two tabs expose disjoint
 * content.
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { CONFIG, EMPTY, FULL } from './analysis.fixture'
import {
  AnalysisPanelBody,
  type AnalysisPanelBodyProps,
  ECONOMICS_NOT_CONFIGURED_TEXT,
} from './AnalysisPanel'
import { ANALYSIS_TABS } from './workflowTabs'

function props(over: Partial<AnalysisPanelBodyProps> = {}): AnalysisPanelBodyProps {
  return {
    view: 'OVERVIEW',
    scenarioId: 'scn-a',
    analysis: FULL,
    analysisError: null,
    loading: false,
    assessment: null,
    assessmentError: null,
    assessmentLoading: false,
    layoutComparison: null,
    layoutComparisonError: null,
    layoutComparisonLoading: false,
    economicsConfig: { configured: true, revision: 'e', config: CONFIG },
    economicsError: null,
    activeMethod: 'LONGHOLE_OPEN_STOPING',
    saving: false,
    saveError: null,
    onSave: () => undefined,
    ...over,
  }
}
const render = (over: Partial<AnalysisPanelBodyProps> = {}) =>
  renderToStaticMarkup(<AnalysisPanelBody {...props(over)} />)

const FORBIDDEN = [
  'Reserves',
  'Resources',
  'Recoverable ore',
  'Proven tonnes',
  'Economic grade',
  'Optimized schedule',
  'feasibility study passed',
  'bankable',
]

describe('Analysis tabs', () => {
  it('are Overview | Economics | Rules | Layout comparison | Simulation Results — "Rules", never "Compliance"', () => {
    expect(ANALYSIS_TABS.map((t) => t.id)).toEqual([
      'OVERVIEW',
      'ECONOMICS',
      'RULES',
      'LAYOUT_COMPARISON',
      'SIMULATION',
    ])
    expect(ANALYSIS_TABS.map((t) => t.label)).toEqual([
      'Overview',
      'Economics',
      'Rules',
      'Layout comparison',
      'Simulation Results',
    ])
    expect(ANALYSIS_TABS.some((t) => /compliance/i.test(t.label))).toBe(false)
  })
})

describe('Overview', () => {
  it('renders the four quantity cards from the backend values', () => {
    const html = render()
    for (const title of ['Development', 'Production', 'Schedule', 'Ratios']) {
      expect(html).toContain(title)
    }
    expect(html).toContain('230 m')
    expect(html).toContain('4,400 m³')
    expect(html).toContain('4,000 t')
    expect(html).toContain('Planned mined tonnes')
    expect(html).toContain('Gross development volume')
    expect(html).toContain('Grade proxy')
    expect(html).toContain('Baseline duration')
    expect(html).toContain('120 d')
    expect(html).toContain('57.5 m/kt')
    expect(html).toContain('Longhole Open Stoping')
    expect(html).not.toContain('Planning economics') // economics lives on its own tab
  })

  it('never uses resource / reserve vocabulary', () => {
    const html = render() + render({ view: 'ECONOMICS' })
    for (const word of FORBIDDEN) expect(html).not.toContain(word)
  })

  it('shows every missing source as Not available with the backend reason (partial 200)', () => {
    const html = render({ analysis: EMPTY })
    expect(html.match(/Not available/g)?.length).toBe(4)
    expect(html).toContain('network.json not generated')
    expect(html).toContain('stopes.json not generated')
    expect(html).toContain('timeline.json not generated')
    expect(html).not.toContain('data-status="READY"')
  })

  it('renders method-specific detail rows for Cut & Fill and Room & Pillar', () => {
    const cf = render({
      analysis: {
        ...FULL,
        production: {
          ...FULL.production,
          method: 'CUT_AND_FILL',
          detail: {
            kind: 'CUT_AND_FILL',
            cutCount: 12,
            liftCount: 3,
            backfillCount: 12,
            totalBackfillVolumeM3: 900,
          },
        },
      },
    })
    expect(cf).toContain('Backfill volume (not production)')
    expect(cf).toContain('900 m³')
    const rp = render({
      analysis: {
        ...FULL,
        production: {
          ...FULL.production,
          method: 'ROOM_AND_PILLAR',
          detail: {
            kind: 'ROOM_AND_PILLAR',
            roomCount: 4,
            extractionUnitCount: 8,
            pillarCount: 5,
            headingCount: 4,
            benchCount: 4,
            retainedPillarVolumeM3: 2500,
            retainedPillarTonnesEquivalent: 7000,
            geometricExtractionFraction: 0.61,
          },
        },
      },
    })
    expect(rp).toContain('Retained pillar volume')
    expect(rp).toContain('2,500 m³')
    expect(rp).toContain('Pillars (retained)')
  })

  it('shows a typed backend refusal instead of guessing', () => {
    const html = render({ analysis: null, analysisError: 'ANALYSIS_SOURCE_INCONSISTENT: x' })
    expect(html).toContain('ANALYSIS_SOURCE_INCONSISTENT: x')
    expect(html).not.toContain('Development')
  })
})

describe('Economics', () => {
  it('not configured: the exact text, the disclaimer and the editor — no summary, no NPV', () => {
    const html = render({
      view: 'ECONOMICS',
      analysis: EMPTY,
      economicsConfig: { configured: false, revision: null, config: null },
    })
    expect(html).toContain(ECONOMICS_NOT_CONFIGURED_TEXT)
    expect(html).toContain('Synthetic planning economics.')
    expect(html).toContain('data-testid="economics-config-editor"')
    expect(html).toContain('DEMO / SYNTHETIC ASSUMPTIONS')
    expect(html).not.toContain('Planning NPV')
    expect(html).not.toContain('data-testid="cashflow-table"')
    // every assumption section is present and the active method is marked
    for (const s of [
      'Currency',
      'Development costs',
      'Production costs',
      'Processing / backfill',
      'Revenue assumption',
      'Fixed / capital cost',
      'Discounting',
    ]) {
      expect(html).toContain(s)
    }
    expect(html).toContain('(active method)')
  })

  it('configured: summary cards, currency, cashflow table and the disclaimer', () => {
    const html = render({ view: 'ECONOMICS' })
    expect(html).toContain('Planning NPV USD 4,039')
    expect(html).toContain('Baseline Planning NPV')
    expect(html).toContain('USD 2,030') // development cost
    expect(html).toContain('USD 20,000') // gross revenue
    expect(html).toContain('USD 4,270') // undiscounted net
    expect(html).toContain('Mine duration')
    expect(html).toContain('data-testid="cashflow-table"')
    expect(html).toContain('90–120')
    expect(html).toContain('11,700')
    expect(html).toContain('data-testid="economics-disclaimer"')
    expect(html).toContain('Synthetic planning economics.')
    // the editor keeps the persisted values as its draft
    expect(html).toContain('value="USD"')
    expect(html).toContain('value="0.1"')
  })

  it('sources missing: the backend reason, never an NPV', () => {
    const html = render({
      view: 'ECONOMICS',
      analysis: {
        ...EMPTY,
        economics: {
          ...EMPTY.economics,
          availability: 'NOT_AVAILABLE',
          reason: 'SOURCE_NOT_AVAILABLE: requires development, production, schedule',
          currencyCode: 'USD',
        },
      },
    })
    expect(html).toContain('SOURCE_NOT_AVAILABLE: requires development, production, schedule')
    expect(html).not.toContain('Planning NPV')
  })
})
