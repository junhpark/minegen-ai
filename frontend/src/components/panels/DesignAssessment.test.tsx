/**
 * Phase 20D.3 — design assessment + alternatives (rule 189): pure display of
 * the backend read model. Every expectation is a backend field rendered as
 * given; the tests pin that nothing is re-sorted, re-scored or inferred and
 * that authorities stay visually distinct (directive §23).
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type {
  AssessmentCheck,
  CandidateComparisonRow,
  DesignAssessmentPayload,
  WorldScene,
} from '@/types/scene'
import { assessmentKey } from './assessmentKey'
import { AlternativesTable, DesignAssessmentList } from './DesignAssessment'
import { LayoutPanelBody } from './LayoutPanel'

function row(over: Partial<CandidateComparisonRow>): CandidateComparisonRow {
  return {
    candidateId: 'SWITCHBACK-k1-p+20-CW-g0.120',
    family: 'SWITCHBACK',
    rank: 1,
    selected: false,
    winner: false,
    status: 'FEASIBLE',
    stageReached: 'DETAILED',
    scores: { development: 1.729, geology: 0, geometry: 2.792, total: 4.520685616859209 },
    deltas: {
      totalScoreDeltaFromWinner: 0,
      developmentScoreDelta: 0,
      geologyScoreDelta: 0,
      geometryScoreDelta: 0,
    },
    accessibleLevels: 4,
    requiredLevels: 4,
    clearance: {
      clearanceBasis: 'EXACT',
      requiredClearance: 10.59,
      conservativeMinimumClearance: 19.65,
      clearanceErrorBound: null,
      satisfied: true,
    },
    access: {
      levelCount: 4,
      accessibleLevelCount: 4,
      totalAccessLength: 224.2,
      worstAccessLength: 71.2,
      maxAccessGradient: 0.12,
      minAccessPlanRadius: 18,
    },
    failureReasons: [],
    failureDetail: null,
    ...over,
  }
}

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

const WINNER = 'SWITCHBACK-k1-p+20-CW-g0.120'
const RANK2 = 'SWITCHBACK-k1-p+0-CW-g0.120'
const RANK3 = 'SPIRAL-n1-CW-e+0-g0.120'

// totals deliberately NOT monotone in rank: rank 3 beats rank 2 on total
const WINNER_ROW = row({ candidateId: WINNER, rank: 1, winner: true, selected: true })
const RANK2_ROW = row({
  candidateId: RANK2,
  rank: 2,
  scores: { development: 1.8, geology: 0, geometry: 2.83, total: 4.6277 },
  deltas: {
    totalScoreDeltaFromWinner: 0.107,
    developmentScoreDelta: 0.071,
    geologyScoreDelta: 0,
    geometryScoreDelta: 0.038,
  },
})
const RANK3_ROW = row({
  candidateId: RANK3,
  family: 'SPIRAL',
  rank: 3,
  scores: { development: 1.75, geology: 0, geometry: 2.8, total: 4.55 },
  deltas: {
    totalScoreDeltaFromWinner: 0.0293,
    developmentScoreDelta: 0.021,
    geologyScoreDelta: 0,
    geometryScoreDelta: 0.008,
  },
  accessibleLevels: 4,
})
const ROWS: CandidateComparisonRow[] = [WINNER_ROW, RANK2_ROW, RANK3_ROW]

function payload(over: Partial<DesignAssessmentPayload>): DesignAssessmentPayload {
  return {
    status: 'SUCCESS',
    activeSource: 'LAYOUT_V2',
    layoutScope: 'ACTIVE_DESIGN',
    activeDesignCandidateId: WINNER,
    winnerId: WINNER,
    selectedCandidateId: WINNER,
    selectedCandidate: WINNER_ROW,
    checks: [
      check({
        id: 'LAYOUT_SELECTED',
        title: 'Layout candidate selected',
        authority: 'DERIVED_VALIDATION',
        evidence: { candidateId: WINNER, layoutRevision: 'abc' },
        sourceArtifact: 'layout_v2_selected.json',
        sourceField: 'candidateId',
      }),
      check({
        id: 'ACTIVE_RAMP_SOURCE',
        title: 'Active ramp source is Layout v2',
        authority: 'INFORMATIONAL',
        evidence: { activeSource: 'LAYOUT_V2', selectedCandidateId: WINNER },
        sourceArtifact: 'ramp_source.json',
        sourceField: 'activeSource',
      }),
      check({}),
      check({
        id: 'ALL_REQUIRED_LEVELS_ACCESSIBLE',
        title: 'All required levels accessible',
        category: 'ACCESS',
        evidence: { accessibleLevels: 4, requiredLevels: 4, unservedLevelIds: [] },
      }),
      check({
        id: 'CLEARANCE_VALIDATED',
        title: 'Orebody clearance validated',
        category: 'CLEARANCE',
        evidence: {
          clearanceBasis: 'EXACT',
          requiredClearance: 10.59,
          conservativeMinimumClearance: 19.65,
          clearanceErrorBound: null,
          satisfied: true,
        },
      }),
      check({
        id: 'REQUIRED_CAPABILITY_PATHS',
        title: 'Required capability paths',
        category: 'CAPABILITY',
        authority: 'DERIVED_VALIDATION',
        evidence: {
          requiredPathCount: 4,
          satisfiedPathCount: 4,
          unsatisfiedPathIds: [],
          physicalOnlyPathIds: [],
        },
        sourceArtifact: 'capability_graph.json',
        sourceField: 'requiredPaths',
      }),
      check({
        id: 'DUAL_EGRESS_ADVISORY',
        title: 'Dual-egress design advisory',
        category: 'EGRESS',
        authority: 'ADVISORY',
        status: 'NOT_SATISFIED',
        summary:
          '18 / 22 underground nodes meet the 2-route design criterion. This is a design advisory, not a statutory compliance determination.',
        evidence: {
          requiredRoutes: 2,
          surfaceNodeIds: ['PORTAL'],
          undergroundNodeCount: 22,
          meetingNodeCount: 18,
          failingNodeCount: 4,
          failingNodeIds: ['L04:ENTRY', 'RAMP_END'],
          minimumIndependentRoutes: 1,
          advisoryOnly: true,
        },
        sourceArtifact: 'capability_graph.json',
        sourceField: 'egressAdvisory',
      }),
    ],
    candidateComparison: ROWS,
    requiredPaths: [],
    egressAdvisory: {
      criterion: 'edge-disjoint EMERGENCY_EGRESS routes to any surface node',
      requiredRoutes: 2,
      advisoryOnly: true,
      surfaceNodeIds: ['PORTAL'],
      undergroundNodeCount: 22,
      meetingNodeCount: 18,
      failingNodeCount: 4,
      failingNodeIds: ['L04:ENTRY', 'RAMP_END'],
      minimumIndependentRoutes: 1,
    },
    summary: `Selected ${WINNER} (SWITCHBACK). Rank: 1 of 11 feasible. Status: FEASIBLE.`,
    sources: {
      activeSource: 'LAYOUT_V2',
      layoutV2Revision: 'abc',
      selectedLayoutRevision: 'def',
      levelAccessesRevision: 'ghi',
      networkRevision: 'net',
      capabilityGraphRevision: 'cap',
    },
    ...over,
  }
}

function rowsInOrder(html: string): string[] {
  return [...html.matchAll(/data-candidate-id="([^"]+)"/g)].map((m) => m[1] ?? '')
}

describe('AlternativesTable', () => {
  it('highlights the winner and the selection and keeps the stored ranking order', () => {
    const html = renderToStaticMarkup(<AlternativesTable assessment={payload({})} />)
    expect(html).toContain('● k1-p+20-CW-g0.120 (selected)')
    expect(html).toContain('data-winner="true"')
    // ranking order as delivered — rank 3 has the LOWER total but stays third
    expect(rowsInOrder(html)).toEqual([WINNER, RANK2, RANK3])
    expect(html).toContain('4.521')
    expect(html).toContain('4.628')
    expect(html).toContain('4.550')
    // deltas are shown as delivered (plain subtraction, signed)
    expect(html).toContain('+0.107')
    expect(html).toContain('+0.029')
    expect(html).toContain('4/4')
    expect(html).toContain('ranking order · ● winner')
  })

  it('never re-sorts rows the backend delivered in another order', () => {
    // a deliberately shuffled payload is rendered as given: the client has
    // no ranking authority (rule 189)
    const shuffled = payload({ candidateComparison: [RANK3_ROW, WINNER_ROW, RANK2_ROW] })
    const html = renderToStaticMarkup(<AlternativesTable assessment={shuffled} />)
    expect(rowsInOrder(html)).toEqual([RANK3, WINNER, RANK2])
  })

  it('labels a non-FEASIBLE row by its status, never as a feasible alternative', () => {
    const html = renderToStaticMarkup(
      <AlternativesTable
        assessment={payload({
          candidateComparison: [
            WINNER_ROW,
            row({
              candidateId: 'LONGITUDINAL-STRIKE_NEGATIVE-FOOTWALL-g0.100',
              family: 'LONGITUDINAL',
              rank: null,
              status: 'NOT_VALIDATED',
              stageReached: 'CHEAP',
              scores: null,
              deltas: null,
              accessibleLevels: null,
            }),
          ],
        })}
      />,
    )
    expect(html).toContain('NOT_VALIDATED')
    expect(html).toContain('<td class="pr-1">—</td>')
    expect(html).toContain('—/4')
    expect(html).not.toContain('● STRIKE_NEGATIVE')
  })

  it('shows the empty comparison of a NO_FEASIBLE catalogue', () => {
    const html = renderToStaticMarkup(
      <AlternativesTable
        assessment={payload({ candidateComparison: [], winnerId: null, selectedCandidate: null })}
      />,
    )
    expect(html).toContain('no feasible candidate')
  })
})

describe('DesignAssessmentList', () => {
  it('renders hard checks, validations and the advisory with distinct marks', () => {
    const html = renderToStaticMarkup(<DesignAssessmentList assessment={payload({})} />)
    expect(html).toContain('DESIGN ASSESSMENT')
    // hard rule satisfied: check mark + "hard rule" tag
    expect(html).toContain('data-check-id="CANDIDATE_FEASIBLE" data-authority="HARD_DESIGN_RULE"')
    expect(html).toContain('Selected candidate feasible: satisfied (hard rule)')
    expect(html).toContain('4/4 levels')
    expect(html).toContain('19.6 m ≥ 10.6 m (EXACT)')
    expect(html).toContain('4/4 paths')
    // the advisory: "!" mark, dashed advisory tag, italic title, never ✓
    expect(html).toContain('data-check-id="DUAL_EGRESS_ADVISORY" data-authority="ADVISORY"')
    expect(html).toContain('Dual-egress design advisory: criterion not met (advisory)')
    expect(html).toContain('border-dashed')
    expect(html).toContain('18/22 nodes · 2 routes')
    expect(html).toContain(
      '18 / 22 underground nodes meet the 2-route design criterion. This is a design advisory, not a statutory compliance determination.',
    )
    const advisoryRow = html.slice(html.indexOf('data-check-id="DUAL_EGRESS_ADVISORY"'))
    expect(advisoryRow.slice(0, advisoryRow.indexOf('</li>'))).not.toContain('✓')
    // informational: "i" mark and the info tag
    expect(html).toContain('Active ramp source is Layout v2: satisfied (info)')
    expect(html).toContain('read-only projection · no statutory claim')
    expect(html).not.toMatch(/compliant|certified|\bsafe\b|unsafe/i)
  })

  it('a satisfied advisory is still marked as an advisory, not a certification', () => {
    const p = payload({})
    const adv = p.checks.find((c) => c.id === 'DUAL_EGRESS_ADVISORY')
    if (!adv) throw new Error('fixture')
    adv.status = 'SATISFIED'
    const html = renderToStaticMarkup(<DesignAssessmentList assessment={p} />)
    expect(html).toContain('Dual-egress design advisory: criterion met (advisory)')
    const advisoryRow = html.slice(html.indexOf('data-check-id="DUAL_EGRESS_ADVISORY"'))
    expect(advisoryRow.slice(0, advisoryRow.indexOf('</li>'))).not.toContain('✓')
    expect(advisoryRow.slice(0, advisoryRow.indexOf('</li>'))).toContain('!')
  })

  it('shows NOT EVALUATED for a missing capability graph, never a pass', () => {
    const p = payload({ egressAdvisory: null, requiredPaths: [] })
    for (const c of p.checks) {
      if (c.category === 'CAPABILITY' || c.category === 'EGRESS') {
        c.status = 'NOT_EVALUATED'
        c.evidence = {}
        c.summary = 'not evaluated: capability_graph.json is not generated'
      }
    }
    const html = renderToStaticMarkup(<DesignAssessmentList assessment={p} />)
    expect(html).toContain('Dual-egress design advisory: NOT EVALUATED (advisory)')
    expect(html).toContain('Required capability paths: NOT EVALUATED (validation)')
    expect(html).toContain(
      'data-check-id="DUAL_EGRESS_ADVISORY" data-authority="ADVISORY" data-status="NOT_EVALUATED"',
    )
    const advisoryRow = html.slice(html.indexOf('data-check-id="DUAL_EGRESS_ADVISORY"'))
    expect(advisoryRow.slice(0, advisoryRow.indexOf('</li>'))).toContain('?')
    expect(advisoryRow.slice(0, advisoryRow.indexOf('</li>'))).not.toContain('nodes')
    expect(html).not.toContain('dual-egress advisory note')
  })

  it('renders a not-satisfied hard rule with the cross mark and its evidence', () => {
    const p = payload({})
    const levels = p.checks.find((c) => c.id === 'ALL_REQUIRED_LEVELS_ACCESSIBLE')
    if (!levels) throw new Error('fixture')
    levels.status = 'NOT_SATISFIED'
    levels.evidence = { accessibleLevels: 3, requiredLevels: 4, unservedLevelIds: ['L03'] }
    const html = renderToStaticMarkup(<DesignAssessmentList assessment={p} />)
    expect(html).toContain('All required levels accessible: not satisfied (hard rule)')
    expect(html).toContain('3/4 levels')
    expect(html).toContain('✗')
  })
})

describe('LayoutPanelBody assessment wiring', () => {
  const scene = {
    scenarioId: 'S',
    layoutV2: {
      layoutVersion: 2,
      status: 'SUCCESS',
      portal: [0, 0, 0],
      portalGenerated: true,
      requiredLevels: [],
      serviceableLevelCount: 0,
      candidateCount: 3,
      feasibleCount: 3,
      shortlist: [],
      ranking: [WINNER, RANK2, RANK3],
      winnerId: WINNER,
      clearanceBasis: 'EXACT',
      clearanceErrorBound: 0,
      requiredClearance: 10.6,
      accessReach: 60,
      footwallStandoff: 50,
      performance: { totalSeconds: 1 },
      searchConfig: {},
      candidates: [],
    },
    layoutV2Selected: null,
    smoothedDecline: null,
    legacySmoothedDecline: null,
    network: null,
    rampSource: {
      activeSource: 'LEGACY',
      owningArtifact: 'decline_smoothed.json',
      available: false,
      legacyAvailable: false,
      layoutV2Available: true,
      layoutV2Selected: false,
      sourceKind: null,
      sourceRevision: null,
      candidateId: null,
      family: null,
      status: null,
      segmentCount: 0,
    },
  } as unknown as WorldScene
  const noop = () => undefined
  const render = (assessment: DesignAssessmentPayload | null, assessmentError: string | null) =>
    renderToStaticMarkup(
      <LayoutPanelBody
        scene={scene}
        pick={null}
        showAll={false}
        job={null}
        busy={false}
        generating={false}
        selecting={false}
        activating={false}
        errorText={null}
        assessment={assessment}
        assessmentError={assessmentError}
        onPick={noop}
        onShowAll={noop}
        onGenerate={noop}
        onSelect={noop}
        onActivate={noop}
      />,
    )

  it('shows both sections when the read model is present', () => {
    const html = render(payload({}), null)
    expect(html).toContain('DESIGN ASSESSMENT')
    expect(html).toContain('ALTERNATIVES')
    expect(rowsInOrder(html)).toEqual([WINNER, RANK2, RANK3])
  })

  it('names the typed read refusal instead of guessing', () => {
    const html = render(null, 'CAPABILITY_GRAPH_STALE: the capability graph is stale')
    expect(html).toContain('design assessment unavailable — CAPABILITY_GRAPH_STALE')
    expect(html).not.toContain('DESIGN ASSESSMENT')
  })

  it('renders nothing while there is no read model and no error', () => {
    const html = render(null, null)
    expect(html).not.toContain('DESIGN ASSESSMENT')
    expect(html).not.toContain('ALTERNATIVES')
  })

  it('derives the query key from the scene identity', () => {
    expect(assessmentKey(null)).toEqual([null])
    const key = assessmentKey(scene)
    expect(key[0]).toBe('S')
    expect(typeof key[1]).toBe('number')
    expect(assessmentKey(scene)).toEqual(key)
    expect(assessmentKey({ ...scene })).not.toEqual(key)
  })
})

const CATALOGUE_A = {
  layoutVersion: 2,
  status: 'SUCCESS',
  portal: [0, 0, 0],
  portalGenerated: true,
  requiredLevels: [],
  serviceableLevelCount: 0,
  candidateCount: 3,
  feasibleCount: 3,
  shortlist: [],
  ranking: [WINNER, RANK2, RANK3],
  winnerId: WINNER,
  clearanceBasis: 'EXACT',
  clearanceErrorBound: 0,
  requiredClearance: 10.6,
  accessReach: 60,
  footwallStandoff: 50,
  performance: { totalSeconds: 1 },
  searchConfig: {},
  candidates: [
    {
      candidateId: WINNER,
      rank: 1,
      scores: { development: 1, geology: 0, geometry: 1, total: 4.5, components: {} },
    },
    {
      candidateId: RANK2,
      rank: 2,
      scores: { development: 1, geology: 0, geometry: 1, total: 4.6, components: {} },
    },
  ],
}

function sceneFor(catalogue: unknown): WorldScene {
  return {
    scenarioId: 'S',
    layoutV2: catalogue,
    layoutV2Selected: null,
    smoothedDecline: null,
    legacySmoothedDecline: null,
    network: null,
    rampSource: {
      activeSource: 'LEGACY',
      owningArtifact: 'decline_smoothed.json',
      available: false,
      legacyAvailable: false,
      layoutV2Available: true,
      layoutV2Selected: false,
      sourceKind: null,
      sourceRevision: null,
      candidateId: null,
      family: null,
      status: null,
      segmentCount: 0,
    },
  } as unknown as WorldScene
}

describe('PR #43 review correction', () => {
  it('assessmentKey changes for a regenerated catalogue with the same winner / count / ranking', () => {
    // the projected values (scores) changed while every identity field the
    // old key used stayed the same: a stale read model must not survive
    const before = sceneFor(CATALOGUE_A)
    const regenerated = sceneFor({
      ...CATALOGUE_A,
      candidates: CATALOGUE_A.candidates.map((c) =>
        c.scores ? { ...c, scores: { ...c.scores, total: c.scores.total + 1 } } : c,
      ),
    })
    expect(assessmentKey(before)).not.toEqual(assessmentKey(regenerated))
    // the same scene object keeps the same key (no refetch storm)
    expect(assessmentKey(before)).toEqual(assessmentKey(before))
    expect(assessmentKey(null)).toEqual([null])
  })

  it('renders the generic assessment for a LEGACY-only scene without a catalogue', () => {
    const legacyOnly = {
      scenarioId: 'S',
      layoutV2: null,
      layoutV2Selected: null,
      smoothedDecline: null,
      legacySmoothedDecline: null,
      network: null,
      rampSource: {
        activeSource: 'LEGACY',
        owningArtifact: 'decline_smoothed.json',
        available: true,
        legacyAvailable: true,
        layoutV2Available: false,
        layoutV2Selected: false,
        sourceKind: 'LEGACY_SMOOTHED',
        sourceRevision: 'r',
        candidateId: null,
        family: null,
        status: 'SUCCESS',
        segmentCount: 3,
      },
    } as unknown as WorldScene
    const p = payload({
      activeSource: 'LEGACY',
      layoutScope: 'NONE',
      winnerId: null,
      selectedCandidateId: null,
      selectedCandidate: null,
      activeDesignCandidateId: null,
      candidateComparison: [],
    })
    for (const c of p.checks) {
      if (c.category === 'CAPABILITY' || c.category === 'EGRESS') continue
      c.status = 'NOT_APPLICABLE'
      c.scope = 'INACTIVE_LAYOUT_V2'
      c.evidence = {}
    }
    const html = renderToStaticMarkup(
      <LayoutPanelBody
        scene={legacyOnly}
        pick={null}
        showAll={false}
        job={null}
        busy={false}
        generating={false}
        selecting={false}
        activating={false}
        errorText={null}
        assessment={p}
        assessmentError={null}
        onPick={() => undefined}
        onShowAll={() => undefined}
        onGenerate={() => undefined}
        onSelect={() => undefined}
        onActivate={() => undefined}
      />,
    )
    expect(html).toContain('DESIGN ASSESSMENT')
    expect(html).toContain('active design: LEGACY')
    expect(html).toContain('18/22 nodes · 2 routes')
    expect(html).toContain('Selected candidate feasible: NOT APPLICABLE (hard rule)')
    expect(html).toContain('no layout-v2 catalogue')
    expect(html).not.toContain('data-candidate-id=')
  })

  it('labels a dormant layout-v2 selection as inactive, never as the active design', () => {
    const p = payload({
      activeSource: 'LEGACY',
      layoutScope: 'INACTIVE_LAYOUT_V2',
      activeDesignCandidateId: null,
    })
    for (const c of p.checks) {
      if (c.category === 'CAPABILITY' || c.category === 'EGRESS') continue
      c.scope = 'INACTIVE_LAYOUT_V2'
    }
    const html = renderToStaticMarkup(<DesignAssessmentList assessment={p} />)
    expect(html).toContain('active design: LEGACY')
    expect(html).toContain('layout-v2 checks describe the INACTIVE layout-v2 selection')
    expect(html).toContain('data-scope="INACTIVE_LAYOUT_V2"')
    const table = renderToStaticMarkup(<AlternativesTable assessment={p} />)
    expect(table).toContain('inactive layout-v2 catalogue')
    expect(table).toContain('(selected)')
    expect(table).not.toContain('(active)')
  })
})
