/**
 * Phase 22C — the Design Rulebook (rule 203) is a presentation of the Phase
 * 20D.3 design assessment: statuses verbatim, an advisory never a pass mark,
 * an informational row never pass / fail, scope distinguished, NOT_EVALUATED
 * never coerced, and no overall compliance score.
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { AssessmentCheck, DesignAssessmentPayload } from '@/types/scene'
import { AnalysisPanelBody, type AnalysisPanelBodyProps } from './AnalysisPanel'
import { CONFIG, FULL, H3_BODY_PROPS } from './analysis.fixture'
import { evidenceText, rulebookStatus } from './rulebook'
import { RULEBOOK_ADVISORY_NOTE, RULEBOOK_INACTIVE_NOTE, RulebookBody } from './RulebookPanel'

const WINNER = 'SWITCHBACK-k1-p+20-CW-g0.120'

function check(over: Partial<AssessmentCheck>): AssessmentCheck {
  return {
    id: 'CANDIDATE_FEASIBLE',
    title: 'Selected candidate feasible',
    category: 'LAYOUT',
    status: 'SATISFIED',
    authority: 'HARD_DESIGN_RULE',
    scope: 'ACTIVE_DESIGN',
    summary: 'candidate status FEASIBLE at stage DETAILED',
    evidence: { status: 'FEASIBLE', stageReached: 'DETAILED', rank: 1, failureReasons: [] },
    sourceArtifact: 'layout_v2.json',
    sourceField: 'candidates[].status',
    ...over,
  }
}

const CHECKS: AssessmentCheck[] = [
  check({}),
  check({
    id: 'LAYOUT_SELECTED',
    title: 'Layout candidate selected',
    authority: 'DERIVED_VALIDATION',
    status: 'NOT_SATISFIED',
    evidence: { candidateId: null },
  }),
  check({
    id: 'CLEARANCE_VALIDATED',
    title: 'Orebody clearance validated',
    category: 'CLEARANCE',
    status: 'NOT_EVALUATED',
    evidence: {},
  }),
  check({
    id: 'GEOMETRY_VALIDATED',
    title: 'Delivered centerline validated',
    category: 'GEOMETRY',
    authority: 'DERIVED_VALIDATION',
    status: 'NOT_APPLICABLE',
    scope: 'INACTIVE_LAYOUT_V2',
    evidence: {},
  }),
  check({
    id: 'DUAL_EGRESS_ADVISORY',
    title: 'Two independent egress routes (design advisory)',
    category: 'EGRESS',
    authority: 'ADVISORY',
    status: 'SATISFIED',
    evidence: { meetingNodeCount: 5, undergroundNodeCount: 5, requiredRoutes: 2 },
  }),
  check({
    id: 'ACTIVE_RAMP_SOURCE',
    title: 'Active ramp source',
    authority: 'INFORMATIONAL',
    status: 'SATISFIED',
    evidence: { activeSource: 'LAYOUT_V2', selectedCandidateId: WINNER, ratio: 0.12345 },
  }),
]

function payload(over: Partial<DesignAssessmentPayload> = {}): DesignAssessmentPayload {
  return {
    status: 'SUCCESS',
    activeSource: 'LAYOUT_V2',
    layoutScope: 'ACTIVE_DESIGN',
    activeDesignCandidateId: WINNER,
    winnerId: WINNER,
    selectedCandidateId: WINNER,
    selectedCandidate: null,
    checks: CHECKS,
    candidateComparison: [],
    requiredPaths: [],
    egressAdvisory: null,
    summary: 'Active design: Layout v2',
    sources: {
      activeSource: 'LAYOUT_V2',
      layoutV2Revision: 'a',
      selectedLayoutRevision: 'b',
      levelAccessesRevision: 'c',
      networkRevision: 'd',
      capabilityGraphRevision: 'e',
    },
    ...over,
  }
}

const render = (p: DesignAssessmentPayload | null = payload(), error: string | null = null) =>
  renderToStaticMarkup(<RulebookBody assessment={p} error={error} loading={false} />)

/** the status row AND its detail row of one check */
function cell(html: string, id: string): string {
  const start = html.indexOf(`data-check-id="${id}"`)
  const detail = html.indexOf(`data-check-detail="${id}"`, start)
  const end = html.indexOf('</tr>', detail)
  return html.slice(start, end)
}

/** the visible text of a row (tags stripped) */
function text(html: string, id: string): string {
  return cell(html, id).replace(/<[^>]+>/g, '')
}

describe('rulebookStatus (presentation mapping only)', () => {
  it('hard rules and validations use ✓ ✗ ? — verbatim statuses', () => {
    expect(rulebookStatus(check({}))).toMatchObject({ glyph: '✓', text: 'SATISFIED' })
    expect(rulebookStatus(check({ status: 'NOT_SATISFIED' }))).toMatchObject({
      glyph: '✗',
      text: 'NOT SATISFIED',
    })
    expect(rulebookStatus(check({ status: 'NOT_EVALUATED' }))).toMatchObject({
      glyph: '?',
      text: 'NOT EVALUATED',
    })
    expect(rulebookStatus(check({ status: 'NOT_APPLICABLE' }))).toMatchObject({
      glyph: '—',
      text: 'NOT APPLICABLE',
    })
    expect(
      rulebookStatus(check({ authority: 'DERIVED_VALIDATION', status: 'SATISFIED' })),
    ).toMatchObject({ glyph: '✓', text: 'SATISFIED' })
  })

  it('an advisory is spelled out as an advisory and never gets the ✓ pass glyph', () => {
    const ok = rulebookStatus(check({ authority: 'ADVISORY', status: 'SATISFIED' }))
    expect(ok.glyph).toBe('')
    expect(ok.text).toBe('Advisory satisfied')
    const no = rulebookStatus(check({ authority: 'ADVISORY', status: 'NOT_SATISFIED' }))
    expect(no.glyph).toBe('')
    expect(no.text).toBe('Advisory not satisfied')
  })

  it('an informational row has no pass / fail whatever its recorded status', () => {
    for (const status of ['SATISFIED', 'NOT_SATISFIED', 'NOT_EVALUATED'] as const) {
      const st = rulebookStatus(check({ authority: 'INFORMATIONAL', status }))
      expect(st).toMatchObject({ glyph: '', text: 'Info' })
    }
  })

  it('evidence is the backend record, compactly', () => {
    expect(evidenceText(check({}))).toBe(
      'status: FEASIBLE · stageReached: DETAILED · rank: 1 · failureReasons: []',
    )
    expect(evidenceText(check({ evidence: {} }))).toBe('—')
    expect(evidenceText(check({ evidence: { ratio: 0.12345, ids: ['a', 'b'], x: null } }))).toBe(
      'ratio: 0.123 · ids: a, b · x: —',
    )
  })
})

describe('RulebookBody', () => {
  it('renders every check as a row with Category · Rule · Status · Authority · Scope · Evidence', () => {
    const html = render()
    for (const head of ['Category', 'Rule', 'Status', 'Authority', 'Scope', 'Evidence']) {
      expect(html).toContain(`>${head}<`)
    }
    expect((html.match(/data-check-id=/g) ?? []).length).toBe(CHECKS.length)
    expect(html).toContain('6 rules')
    const feasible = cell(html, 'CANDIDATE_FEASIBLE')
    expect(feasible).toContain('✓')
    expect(feasible).toContain('SATISFIED')
    expect(feasible).toContain('Hard design rule')
    expect(feasible).toContain('Active design')
    expect(feasible).toContain('status: FEASIBLE · stageReached: DETAILED · rank: 1')
    const selected = cell(html, 'LAYOUT_SELECTED')
    expect(selected).toContain('✗')
    expect(selected).toContain('NOT SATISFIED')
    expect(selected).toContain('Design validation')
  })

  it('NOT_EVALUATED stays NOT EVALUATED — never a failure — and NOT_APPLICABLE is a dash', () => {
    const html = render()
    const clearance = cell(html, 'CLEARANCE_VALIDATED')
    expect(clearance).toContain('data-status="NOT_EVALUATED"')
    expect(text(html, 'CLEARANCE_VALIDATED')).toContain('? NOT EVALUATED')
    expect(clearance).not.toContain('✗')
    expect(clearance).not.toContain('NOT SATISFIED')
    expect(text(html, 'GEOMETRY_VALIDATED')).toContain('— NOT APPLICABLE')
    expect(text(html, 'GEOMETRY_VALIDATED')).toContain('Inactive layout-v2')
  })

  it('a satisfied advisory is "Advisory satisfied" with the non-statutory note, never a ✓', () => {
    const html = render()
    const egress = cell(html, 'DUAL_EGRESS_ADVISORY')
    expect(egress).toContain('Advisory satisfied')
    expect(egress).toContain(RULEBOOK_ADVISORY_NOTE)
    expect(egress).toContain('Design advisory')
    expect(egress).not.toContain('✓')
    expect(egress).not.toContain('>SATISFIED<')
  })

  it('an informational row shows Info and no pass / fail glyph', () => {
    const html = render()
    const info = cell(html, 'ACTIVE_RAMP_SOURCE')
    expect(info).toContain('>Info<')
    expect(info).toContain('Informational')
    expect(info).not.toContain('✓')
    expect(info).not.toContain('✗')
    expect(info).toContain('activeSource: LAYOUT_V2')
  })

  it('never aggregates: no overall score, percentage, compliant verdict or certification', () => {
    const html = render()
    for (const word of [
      '%',
      'compliant: YES',
      'Compliant',
      'certified',
      'Certified',
      'regulatory',
      'SAFE',
      'unsafe',
      'score:',
      'Score:',
      '/6',
      'passed',
      'Passed',
    ]) {
      expect(html).not.toContain(word)
    }
    expect(html).not.toMatch(/\d+\s*(of|\/)\s*\d+\s*(rules|checks)/)
    expect(html).toContain('no overall compliance score')
  })

  it('distinguishes the INACTIVE layout-v2 scope from the active design', () => {
    const html = render(payload({ activeSource: 'LEGACY', layoutScope: 'INACTIVE_LAYOUT_V2' }))
    expect(html).toContain(RULEBOOK_INACTIVE_NOTE)
    expect(html).toContain('Active design: Legacy ramp (Hybrid-A*)')
    const active = render()
    expect(active).not.toContain(RULEBOOK_INACTIVE_NOTE)
    expect(active).toContain(`Active design: Layout v2 · ${WINNER}`)
    const none = render(payload({ activeSource: 'LEGACY', layoutScope: 'NONE' }))
    expect(none).toContain('no layout-v2 catalogue')
  })

  it('names a typed refusal and renders nothing else', () => {
    const html = render(null, 'LAYOUT_V2_SELECTION_STALE: …')
    expect(html).toContain('design assessment unavailable — LAYOUT_V2_SELECTION_STALE')
    expect(html).not.toContain('data-testid="rulebook-table"')
  })
})

describe('Rules tab inside the Analysis panel', () => {
  const props = (over: Partial<AnalysisPanelBodyProps>): AnalysisPanelBodyProps => ({
    view: 'RULES',
    levels: null,
    scenarioId: 'scn-a',
    analysis: FULL,
    analysisError: null,
    loading: false,
    assessment: payload(),
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
  })

  it('renders the rulebook and none of the other tabs’ content', () => {
    const html = renderToStaticMarkup(<AnalysisPanelBody {...props({})} />)
    expect(html).toContain('data-testid="rulebook-table"')
    // the KPI tiles head every tab (PR-2 H3 §8.1); the economics CARD does not
    expect(html).toContain('data-testid="analysis-kpis"')
    expect(html).not.toContain('Baseline Planning NPV')
    expect(html).not.toContain('data-testid="layout-comparison-table"')
    expect(html).not.toContain('Planned mined tonnes')
  })

  it('does not depend on the analysis query (an analysis error never hides the rules)', () => {
    const html = renderToStaticMarkup(
      <AnalysisPanelBody
        {...props({ analysis: null, analysisError: 'ANALYSIS_SOURCE_INCONSISTENT: x' })}
      />,
    )
    expect(html).toContain('data-testid="rulebook-table"')
  })
})
