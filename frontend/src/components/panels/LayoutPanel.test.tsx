/**
 * Phase 20A LayoutPanel: display of the backend catalogue and the explicit
 * ramp-source switch. No engineering values are computed here — every number
 * in the markup must be a backend-authored field.
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { LayoutCandidateSummary, LayoutV2Catalogue, WorldScene } from '@/types/scene'
import { LayoutPanelBody } from './LayoutPanel'
import { compareCandidates } from './layoutOrder'

function candidate(over: Partial<LayoutCandidateSummary>): LayoutCandidateSummary {
  return {
    candidateId: 'SPIRAL-n1-CW-e+0-g0.120',
    family: 'SPIRAL',
    parameters: {},
    status: 'FEASIBLE',
    stageReached: 'DETAILED',
    failureReasons: [],
    failureDetail: null,
    shortlisted: true,
    rank: 1,
    screenedLevels: 4,
    accessibleLevels: 4,
    requiredLevels: 4,
    rampLevelReferences: [
      {
        levelId: 'L01',
        elevation: -1.5,
        withinReach: true,
        referencePosition: [1, 2, -1.5],
        referenceChainage: 120,
        footprintDistance: 21.4,
        screenReason: null,
      },
    ],
    access: {
      feasible: true,
      levelCount: 4,
      accessibleLevelCount: 4,
      totalAccessLength: 211.1,
      worstAccessLength: 17.2,
      maxAccessGradient: 0.12,
      minAccessPlanRadius: 18,
      perLevelLength: { L01: 17.2 },
      failures: {},
      maxGradientLimit: 0.12,
      minTurnRadiusLimit: 18,
      requiredClearance: 10.59,
      effectivePreferredAccessLength: 30,
      preferredAccessSource: 'DEFAULT_6X_TUNNEL_WIDTH',
      longAccessCoefficient: 0.5,
      meanAbsDeviationFromPreferred: 3.8,
      maxAbsDeviationFromPreferred: 12.8,
    },
    levelAccesses: [
      {
        levelId: 'L01',
        elevation: -1.5,
        status: 'OK',
        anchor: null,
        rampJunction: [0, 0, 0],
        rampJunctionChainage: 1300,
        rampJunctionHeadingDeg: 10,
        rampJunctionEdgeIndex: 3,
        levelEntry: [5, 5, -1.5],
        terminalHeadingDeg: 40,
        connector: 'RSL',
        pieces: [],
        length3d: 17.2,
        horizontalLength: 17.1,
        maxGradient: 0.12,
        minPlanRadius: 18,
        fieldCost: 1,
        validation: {},
        candidatesTried: 9,
        candidatesValid: 2,
        rejectionCounts: {},
        failureReason: null,
        failureDetail: null,
        centerline: null,
        effectivePreferredAccessLength: 30,
        lengthDeviationFromPreferred: -12.8,
        selectionCost: 12.8,
      },
    ],
    diagnostics: {
      pointCount: 10,
      length3d: 3825.4,
      horizontalLength: 3800,
      verticalDrop: 300,
      maxAbsGradient: 0.12,
      meanAbsGradient: 0.118,
      minPlanRadius: 18.77,
      turningLength: 100,
      cumulativeHeadingChangeDeg: 6211,
      signedHeadingChangeDeg: -6211,
      headingReversalCount: 0,
      hairpinRunCount: 1,
      dominantAzimuthsDeg: [37.5, 127.5],
      turnDirectionConsistency: 1,
      maxLocalTurnDeg: 5.4,
      monotonicDescent: true,
    },
    scores: {
      development: 1.234,
      geology: 0.056,
      geometry: 0.884,
      total: 2.174,
      components: {},
    },
    clearance: {
      clearanceBasis: 'COARSE_CONSERVATIVE',
      requiredClearance: 10.59,
      conservativeMinimumClearance: 20.0,
      approximateMinimumClearance: 30.77,
      clearanceErrorBound: 10.77,
      satisfied: true,
    },
    cheapProxy: 1.1,
    ...over,
  }
}

const CATALOGUE: LayoutV2Catalogue = {
  layoutVersion: 1,
  status: 'SUCCESS',
  portal: [0, 0, 100],
  portalGenerated: true,
  requiredLevels: [
    { levelId: 'L01', index: 0, elevation: -1.5, hasOrebodySection: true },
    { levelId: 'L02', index: 1, elevation: -26.5, hasOrebodySection: false },
  ],
  serviceableLevelCount: 1,
  candidateCount: 68,
  feasibleCount: 2,
  shortlist: [],
  ranking: ['SPIRAL-n1-CW-e+0-g0.120', 'SWITCHBACK-k2-p+0-CCW-g0.120'],
  winnerId: 'SPIRAL-n1-CW-e+0-g0.120',
  clearanceBasis: 'COARSE_CONSERVATIVE',
  clearanceErrorBound: 10.77,
  requiredClearance: 10.59,
  accessReach: 60,
  footwallStandoff: 20,
  performance: { totalSeconds: 8.31 },
  searchConfig: {},
  candidates: [
    candidate({}),
    candidate({
      candidateId: 'SWITCHBACK-k2-p+0-CCW-g0.120',
      family: 'SWITCHBACK',
      rank: 2,
      scores: { development: 1.5, geology: 0.1, geometry: 0.9, total: 2.5, components: {} },
    }),
    candidate({
      candidateId: 'LONGITUDINAL-STRIKE_POSITIVE-FOOTWALL-g0.120',
      family: 'LONGITUDINAL',
      status: 'INFEASIBLE',
      rank: null,
      scores: null,
      clearance: null,
      failureReasons: ['LEVEL_SERVICE_INFEASIBLE'],
      failureDetail: '2 of 4 required levels fail the access-potential screen (NO_RL_CROSSING)',
      accessibleLevels: null,
      access: null,
      levelAccesses: null,
    }),
  ],
}

function sceneWith(over: Partial<WorldScene>): WorldScene {
  return {
    scenarioId: 'S',
    layoutV2: CATALOGUE,
    layoutV2Selected: null,
    legacySmoothedDecline: null,
    smoothedDecline: null,
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
    ...over,
  } as unknown as WorldScene
}

const noop = () => undefined

function render(scene: WorldScene | null): string {
  return renderToStaticMarkup(
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
      onPick={noop}
      onShowAll={noop}
      onGenerate={noop}
      onSelect={noop}
      onActivate={noop}
    />,
  )
}

describe('LayoutPanel', () => {
  it('shows the empty state as the primary workflow, without a legacy switch', () => {
    const html = render(null)
    expect(html).toContain('Layout v2')
    expect(html).toContain('Generate candidates')
    expect(html).toContain('Current design')
    // closeout v3 §1: the LEGACY / LAYOUT_V2 source switch is an Advanced
    // action of the legacy section, never a Layout v2 prerequisite
    expect(html).not.toContain('Legacy (Hybrid-A*)')
    expect(html).not.toContain('role="radiogroup"')
  })

  it('renders backend-authored candidate rows, scores and the winner mark', () => {
    const html = render(sceneWith({}))
    expect(html).toContain('2 feasible / 68 enumerated')
    expect(html).toContain('1/2 levels with ore')
    expect(html).toContain('clearance COARSE_CONSERVATIVE (−10.8 m) ≥ 10.6 m')
    expect(html).toContain('#1 ')
    expect(html).toContain('2.174')
    expect(html).toContain('D 1.23 · G 0.06 · M 0.88')
    expect(html).toContain('★')
    expect(html).toContain('SWITCHBACK')
    // infeasible candidates are hidden until requested, never re-scored
    expect(html).not.toContain('LEVEL_SERVICE_INFEASIBLE')
    // the winner is the default pick: its detail block is shown
    expect(html).toContain('SPIRAL-n1-CW-e+0-g0.120')
    expect(html).toContain('3825 m')
    expect(html).toContain('R ≥ 18.8 m')
    expect(html).toContain('20.0 m ≥ 10.6 m (bound 10.8 m)')
    // Phase 20B: explicit access, never "served" by an RL crossing
    expect(html).toContain('4/4 accessible')
    expect(html).toContain('access 211 m · worst 17 m')
    // closeout v3 §2.G: the backend preferred length and the deviation are shown
    expect(html).toContain('preferred access 30 m (6 × width)')
    expect(html).toContain('mean |ΔP| 3.8 m')
    expect(html).toContain('junction @1300 m · access 17 m (ΔP −13 m)')
    expect(html).not.toContain('served')
  })

  it('names the current design: none, legacy (advanced) or the active layout-v2 candidate', () => {
    const html = render(sceneWith({}))
    expect(html).toContain('none yet')
    expect(html).toContain('Select or Activate one to make it the design')
    const legacy = render(
      sceneWith({
        rampSource: {
          ...sceneWith({}).rampSource,
          available: true,
          legacyAvailable: true,
          sourceKind: 'LEGACY_SMOOTHED',
          segmentCount: 3,
        },
      }),
    )
    expect(legacy).toContain('Legacy decline (Hybrid-A*) — advanced')
    expect(legacy).toContain('LEGACY_SMOOTHED · 3 segments · decline_smoothed.json')
  })

  it('marks the active candidate when LAYOUT_V2 is the source', () => {
    const html = render(
      sceneWith({
        rampSource: {
          ...sceneWith({}).rampSource,
          activeSource: 'LAYOUT_V2',
          available: true,
          layoutV2Selected: true,
          candidateId: 'SPIRAL-n1-CW-e+0-g0.120',
          sourceKind: 'PARAMETRIC_V2',
          owningArtifact: 'layout_v2_selected.json',
          segmentCount: 4,
        },
      }),
    )
    expect(html).toContain('(active)')
    expect(html).toContain('Layout v2 · SPIRAL-n1-CW-e+0-g0.120 (active)')
    expect(html).toContain('PARAMETRIC_V2 · 4 segments · layout_v2_selected.json')
  })
})

describe('compareCandidates', () => {
  it('orders ranked feasible first, then family order and id — no client re-scoring', () => {
    const rows = [...CATALOGUE.candidates].reverse().sort(compareCandidates)
    expect(rows.map((c) => c.candidateId)).toEqual([
      'SPIRAL-n1-CW-e+0-g0.120',
      'SWITCHBACK-k2-p+0-CCW-g0.120',
      'LONGITUDINAL-STRIKE_POSITIVE-FOOTWALL-g0.120',
    ])
  })
})
