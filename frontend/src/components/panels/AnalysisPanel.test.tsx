/**
 * Phase 22A/B — the Analysis workspace is a pure display of the backend read
 * model: quantities, availabilities and economics are rendered as given, the
 * vocabulary stays planning vocabulary, and the two tabs expose disjoint
 * content.
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import {
  CONFIG,
  EMPTY,
  FULL,
  H3_BODY_PROPS,
  SENSITIVITY,
  SENSITIVITY_NOT_CONFIGURED,
  TIMESERIES,
} from './analysis.fixture'
import { irrText } from './analysisFormat'
import {
  AnalysisPanelBody,
  type AnalysisPanelBodyProps,
  ECONOMICS_NOT_CONFIGURED_TEXT,
} from './AnalysisPanel'
import type { LevelsPayload, TimelinePayload } from '@/types/scene'
import { WHAT_IF_LABEL } from '@/types/analysis'
import { ANALYSIS_TABS } from './workflowTabs'

function props(over: Partial<AnalysisPanelBodyProps> = {}): AnalysisPanelBodyProps {
  return {
    view: 'OVERVIEW',
    scenarioId: 'scn-a',
    analysis: FULL,
    analysisError: null,
    loading: false,
    levels: null,
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
    ...H3_BODY_PROPS,
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
  it('are Overview | Economics | Sensitivity | Schedule | Rules | Layouts | Simulation Results — "Rules", never "Compliance"', () => {
    expect(ANALYSIS_TABS.map((t) => t.id)).toEqual([
      'OVERVIEW',
      'ECONOMICS',
      'SENSITIVITY',
      'SCHEDULE',
      'RULES',
      'LAYOUT_COMPARISON',
      'SIMULATION',
    ])
    expect(ANALYSIS_TABS.map((t) => t.label)).toEqual([
      'Overview',
      'Economics',
      'Sensitivity',
      'Schedule',
      'Rules',
      'Layouts',
      'Simulation Results',
    ])
    expect(ANALYSIS_TABS.some((t) => /compliance/i.test(t.label))).toBe(false)
  })
})

describe('KPI tiles (hardening PR-2 H3 §8.1)', () => {
  it('head every analysis tab with Planning NPV, Planning IRR, mine life and first production — backend values', () => {
    for (const view of ['OVERVIEW', 'ECONOMICS', 'SENSITIVITY', 'SCHEDULE'] as const) {
      const html = render({ view, sensitivity: SENSITIVITY, timeseries: TIMESERIES })
      expect(html).toContain('data-testid="analysis-kpis"')
      expect(html).toContain('data-kpi="Planning NPV"')
      expect(html).toContain('USD 4,039')
      expect(html).toContain('data-kpi="Planning IRR"')
      expect(html).toContain('12.3 %')
      expect(html).toContain('data-kpi="Mine life"')
      expect(html).toContain('120 d')
      expect(html).toContain('data-kpi="First production day"')
      expect(html).toContain('50 d')
    }
    // Rules / Layouts keep their bodies and gain the tiles
    expect(render({ view: 'RULES' })).toContain('data-testid="analysis-kpis"')
    expect(render({ view: 'LAYOUT_COMPARISON' })).toContain('data-testid="analysis-kpis"')
    // the Simulation Results tab is its own container
    expect(render({ view: 'SIMULATION' })).toBe('')
  })

  it('show the typed economics status instead of a number when not configured', () => {
    const html = render({
      analysis: EMPTY,
      economicsConfig: { configured: false, revision: null, config: null },
    })
    expect(html).toContain('data-testid="analysis-kpis"')
    expect(html).toContain('Not configured')
    expect(html).toContain('NOT_CONFIGURED')
    expect(html).not.toContain('NaN')
    expect(html).not.toContain('Infinity')
  })

  it('irrText is typed — a percentage when DEFINED, the reason otherwise, never NaN', () => {
    expect(irrText(FULL.economics.planningIrr)).toBe('12.3 %')
    expect(irrText(EMPTY.economics.planningIrr)).toBe('NOT_CONFIGURED')
    expect(
      irrText({ ...EMPTY.economics.planningIrr, status: 'NOT_DEFINED', reason: 'NO_SIGN_CHANGE' }),
    ).toBe('NOT_DEFINED · NO_SIGN_CHANGE')
    expect(
      irrText({
        ...EMPTY.economics.planningIrr,
        status: 'NOT_DEFINED',
        reason: 'MULTIPLE_SIGN_CHANGES',
      }),
    ).toBe('NOT_DEFINED · MULTIPLE_SIGN_CHANGES')
    expect(irrText(null)).toBe('—')
  })
})

describe('Sensitivity (hardening PR-2 H3 §8.3)', () => {
  it('renders the what-if label, the tornado, the case table and the form from the backend grid', () => {
    const html = render({ view: 'SENSITIVITY', sensitivity: SENSITIVITY })
    expect(html).toContain('data-testid="what-if-label"')
    expect(html).toContain(WHAT_IF_LABEL)
    expect(html).toContain('WHAT-IF OVERRIDE')
    expect(html).toContain('NOT SCENARIO VALUE')
    expect(html).toContain('data-testid="sensitivity-tornado"')
    expect(html).toContain('data-testid="sensitivity-table"')
    expect(html).toContain('data-testid="what-if-form"')
    expect(html).toContain('Gross revenue per mined tonne')
    expect(html).toContain('+USD 5,700')
    expect(html).toContain('−USD 5,700') // the backend delta with its sign, layout-comparison convention
    expect(html).toContain('150 d') // a schedule what-if changes the duration
    expect(html).toContain('Evaluate what-if (not saved)')
    expect(html).toContain('Synthetic planning economics.')
    // the revenue authority stays "gross revenue per mined tonne" — no price model input
    for (const word of ['Metal price', 'Recovery', 'Royalty', 'Tax', 'Payability', 'Smelter']) {
      expect(html).not.toContain(word)
    }
    expect(html).not.toContain('data-testid="what-if-result"')
  })

  it('shows the explicit what-if answer under its label, and a typed failure as text', () => {
    const ok = render({
      view: 'SENSITIVITY',
      sensitivity: SENSITIVITY,
      whatIf: { ...SENSITIVITY.base, planningNpv: 5000, npvDelta: 961.49 },
    })
    expect(ok).toContain('data-testid="what-if-result"')
    expect(ok).toContain('USD 5,000')
    const failed = render({
      view: 'SENSITIVITY',
      sensitivity: SENSITIVITY,
      whatIf: {
        ...SENSITIVITY.base,
        status: 'FAILED',
        reason: 'TIMELINE_CYCLE: …',
        planningNpv: null,
      },
    })
    expect(failed).toContain('FAILED: TIMELINE_CYCLE: …')
  })

  it('not configured: the reason, no tornado, the form still present; a typed refusal is shown verbatim', () => {
    const html = render({
      view: 'SENSITIVITY',
      analysis: EMPTY,
      sensitivity: SENSITIVITY_NOT_CONFIGURED,
      economicsConfig: { configured: false, revision: null, config: null },
    })
    expect(html).toContain('Planning economics is not configured.')
    expect(html).not.toContain('data-testid="sensitivity-tornado"')
    expect(html).toContain('data-testid="what-if-form"')
    const refused = render({
      view: 'SENSITIVITY',
      sensitivity: null,
      sensitivityError: 'READ_SNAPSHOT_CHANGED: the mine moved',
    })
    expect(refused).toContain('READ_SNAPSHOT_CHANGED: the mine moved')
    expect(refused).not.toContain('data-testid="what-if-form"')
  })
})

describe('Schedule (hardening PR-2 H3 §8)', () => {
  const timeline: TimelinePayload = {
    status: 'SUCCESS',
    failureReason: null,
    sourceRevision: 't',
    startDay: 0,
    endDay: 120,
    tasks: [
      {
        id: 'DEV:RAMP:0',
        taskType: 'DEVELOPMENT',
        targetKind: 'DEVELOPMENT',
        targetId: 'RAMP:0',
        startDay: 0,
        endDay: 30,
        durationDays: 30,
        dependencies: [],
        basis: null,
      },
    ],
    developments: [],
    stopes: [],
    production: null,
    metrics: null,
  } as unknown as TimelinePayload
  it('renders the baseline KPIs, the backend series charts and the persisted task table', () => {
    const html = render({ view: 'SCHEDULE', timeseries: TIMESERIES, timeline })
    expect(html).toContain('Baseline schedule')
    expect(html).toContain('data-testid="schedule-series"')
    expect(html).toContain('Excavated development rock')
    expect(html).not.toContain('waste')
    expect(html).toContain('Planned mined tonnes per bucket')
    expect(html).toContain('Development tonnes: NOT_CONFIGURED')
    expect(html).toContain('data-testid="schedule-tasks"')
    expect(html).toContain('RAMP:0')
    expect(html).toContain('(1 of 1)')
    expect(html).toContain('never a production forecast')
  })

  it('series unavailable: the backend reason; a typed refusal verbatim; no timeline → the note', () => {
    const html = render({
      view: 'SCHEDULE',
      timeseries: { ...TIMESERIES, availability: 'NOT_AVAILABLE', reason: 'timeline.json not generated' },
    })
    expect(html).toContain('timeline.json not generated')
    expect(html).toContain('The timeline artifact is not in the scene.')
    const refused = render({ view: 'SCHEDULE', timeseriesError: 'READ_SNAPSHOT_CHANGED: moved' })
    expect(refused).toContain('READ_SNAPSHOT_CHANGED: moved')
    const noSchedule = render({ view: 'SCHEDULE', analysis: EMPTY })
    expect(noSchedule).toContain('timeline.json not generated')
    expect(noSchedule).not.toContain('data-testid="schedule-series"')
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

  it('shows the level-coverage report of the levels artifact when levels are excluded (hardening H0 §3.1)', () => {
    const levels: LevelsPayload = {
      status: 'SUCCESS',
      failureReason: null,
      sourceRevision: 'r',
      developments: [],
      levels: [],
      metrics: null,
      excludedLevels: [
        {
          levelId: 'L01',
          index: 0,
          elevation: 105.5,
          reason: 'NO_FOOTWALL_CONTACT_AT_LEVEL',
          overshootM: 2.1206,
          minimumTopMiningMarginM: 11.865,
        },
      ],
      unservedIntervals: [
        {
          upperLevelId: 'L01',
          lowerLevelId: 'L02',
          upperElevation: 105.5,
          lowerElevation: 80.5,
          reason: 'NO_FOOTWALL_CONTACT_AT_LEVEL',
        },
      ],
    }
    const html = render({ levels })
    expect(html).toContain('Level coverage')
    expect(html).toContain(
      'Top level L01 excluded — footwall contact above orebody top (2.12 m). Minimum topMiningMargin for L01: 11.87 m',
    )
    expect(html).toContain('No production interval L01–L02')
    // nothing excluded → no card
    expect(
      render({ levels: { ...levels, excludedLevels: [], unservedIntervals: [] } }),
    ).not.toContain('Level coverage')
    expect(render()).not.toContain('Level coverage')
  })

  it('never uses resource / reserve vocabulary', () => {
    const html = render() + render({ view: 'ECONOMICS' })
    for (const word of FORBIDDEN) expect(html).not.toContain(word)
  })

  it('shows every missing source as Not available with the backend reason (partial 200)', () => {
    const html = render({ analysis: EMPTY })
    // four section cards + the two schedule KPI tiles (mine life, first production)
    expect(html.match(/Not available/g)?.length).toBe(6)
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
    expect(html).not.toContain('Planning NPV USD') // no figure anywhere, only the typed status
    expect(html).not.toContain('data-testid="cashflow-charts"')
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
    expect(html).toContain('Planning IRR 12.3 %')
    expect(html).toContain('data-testid="cashflow-charts"')
    expect(html).toContain('Cost breakdown (whole mine), USD')
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
    expect(html).not.toContain('Planning NPV USD')
    expect(html).toContain('Not available') // the KPI tile shows the typed status
  })
})
