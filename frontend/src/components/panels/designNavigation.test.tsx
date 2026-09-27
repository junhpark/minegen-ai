/**
 * Phase 20E §26 D — Design workflow navigation.
 *
 * Each Design tab exposes exactly its own features as primary content, and a
 * feature is never rendered in two contexts. `DesignPanelBody` is pure, so
 * the grouping is asserted on real markup rather than on a lookup table.
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type {
  DevelopmentMeshReport,
  LevelsPayload,
  MiningMethodSummary,
  NetworkPayload,
  StopesPayload,
  TimelinePayload,
} from '@/types/scene'
import { DesignPanelBody, type DesignPanelBodyProps } from './DesignPanel'
import { DESIGN_TABS, type DesignTab } from './workflowTabs'

const LONGHOLE: MiningMethodSummary = {
  method: 'LONGHOLE_OPEN_STOPING',
  displayName: 'Longhole Open Stoping',
  implementationStatus: 'IMPLEMENTED',
  sublevelInterval: 25,
  stopeLength: 20,
  minimumPillar: 15,
}

function props(over: Partial<DesignPanelBodyProps> = {}): DesignPanelBodyProps {
  return {
    view: 'DEVELOP',
    rampSource: 'LAYOUT_V2',
    candidateId: 'SPIRAL-n1-CW-e+0-g0.120',
    rampReady: true,
    levels: null,
    levelsPending: false,
    levelsEnabled: true,
    onGenerateLevels: () => undefined,
    developmentMesh: null,
    developmentMeshJob: null,
    developmentMeshBusy: false,
    developmentMeshEnabled: false,
    onGenerateDevelopmentMesh: () => undefined,
    tunnel: null,
    tunnelJob: null,
    tunnelBusy: false,
    tunnelEnabled: true,
    onGenerateTunnel: () => undefined,
    shafts: null,
    shaftSpecCount: 0,
    shaftsPending: false,
    shaftsEnabled: false,
    onGenerateShafts: () => undefined,
    network: null,
    networkPending: false,
    networkEnabled: false,
    onGenerateNetwork: () => undefined,
    capabilityGraph: null,
    capabilityPending: false,
    capabilityEnabled: false,
    onGenerateCapabilityGraph: () => undefined,
    miningMethod: LONGHOLE,
    stopes: null,
    stopesPending: false,
    stopesEnabled: false,
    onGenerateStopes: () => undefined,
    timeline: null,
    timelinePending: false,
    timelineEnabled: false,
    onGenerateTimeline: () => undefined,
    developError: null,
    networkError: null,
    miningError: null,
    ...over,
  }
}

const render = (over: Partial<DesignPanelBodyProps> = {}) =>
  renderToStaticMarkup(<DesignPanelBody {...props(over)} />)

/** every card title the Design workflow owns, with the tab that owns it */
const OWNER: Record<string, DesignTab> = {
  'Level development': 'DEVELOP',
  'Development mesh': 'DEVELOP',
  'Ramp tunnel mesh': 'DEVELOP',
  Shafts: 'DEVELOP',
  'Mine network': 'NETWORK',
  Capabilities: 'NETWORK',
  'Mining method': 'MINING',
  Stopes: 'MINING',
  Schedule: 'MINING',
}

describe('Design workflow tabs expose one context at a time', () => {
  it.each(['DEVELOP', 'NETWORK', 'MINING'] as const)('%s shows only its own cards', (view) => {
    const html = render({ view })
    for (const [title, owner] of Object.entries(OWNER)) {
      const heading = `>${title}`
      if (owner === view) expect(html).toContain(heading)
      else expect(html).not.toContain(heading)
    }
  })

  it('the Layout tab renders no development content at all', () => {
    expect(render({ view: 'LAYOUT' })).toBe('')
  })

  it('the tab list is exactly the four declared workflow contexts, in order', () => {
    expect(DESIGN_TABS.map((t) => t.id)).toEqual(['LAYOUT', 'DEVELOP', 'NETWORK', 'MINING'])
    expect(DESIGN_TABS.map((t) => t.label)).toEqual(['Layout', 'Develop', 'Network', 'Mining'])
  })

  it('Mining holds the production features and a READ-ONLY method card, no selector (§21)', () => {
    const html = render({ view: 'MINING' })
    expect(html).toContain('>Stopes')
    expect(html).toContain('>Schedule')
    // Phase 21A: the card echoes the backend registry; nothing here edits the method
    const card = html.slice(html.indexOf('Mining method'), html.indexOf('>Stopes'))
    expect(card).toContain('Longhole Open Stoping')
    expect(card).toContain('Implemented')
    expect(card).toContain('data-status="ACTIVE"')
    expect(card).not.toContain('<select')
    expect(card).not.toContain('type="radio"')
    expect(html.indexOf('Mining method')).toBeLessThan(html.indexOf('>Stopes'))
    const details = card.slice(card.indexOf('hidden=""'))
    expect(details).toContain('Sublevel interval')
    expect(details).toContain('25 m')
    expect(details).toContain('Stope length')
    expect(details).toContain('20 m')
    expect(details).toContain('Minimum pillar')
    expect(details).toContain('15 m')
  })

  it('an unsupported method reads "Not implemented" without implying a mine failure', () => {
    const html = render({
      view: 'MINING',
      miningMethod: {
        ...LONGHOLE,
        method: 'CUT_AND_FILL',
        displayName: 'Cut & Fill',
        implementationStatus: 'UNSUPPORTED_METHOD',
      },
    })
    const card = html.slice(html.indexOf('Mining method'), html.indexOf('>Stopes'))
    expect(card).toContain('Cut &amp; Fill')
    expect(card).toContain('Not implemented')
    expect(card).toContain('data-status="INACTIVE"')
    expect(card).not.toContain('data-status="FAILED"')
    expect(card).toContain('not implemented in this version')
    expect(card).not.toContain('<select')
  })

  it('without a loaded scene the method card is simply absent', () => {
    const html = render({ view: 'MINING', miningMethod: null })
    expect(html).not.toContain('Mining method')
    expect(html).toContain('>Stopes')
  })
})

describe('a workflow card always states where the user stands', () => {
  it('a not-yet-generated feature still shows its status and its action', () => {
    const html = render({ view: 'NETWORK' })
    expect(html).toContain('data-status="NOT_GENERATED"')
    expect(html).toContain('Build network')
    // a prerequisite that is not met disables the action but never hides it
    expect(html).toContain('disabled=""')
  })

  it('a running job reports Running over the persisted artifact', () => {
    const html = render({ view: 'DEVELOP', levels: null, levelsPending: true })
    expect(html).toContain('data-status="RUNNING"')
    expect(html).toContain('Laying out levels…')
  })

  it('a failure and its reason are visible without opening Details (§24)', () => {
    const levels = {
      status: 'FAILED',
      failureReason: 'GRADE_LIMIT: L05 access cannot reach its entry',
      metrics: null,
      entrySource: 'LEVEL_ACCESS',
      developmentGeometry: 'TABULAR_RULE_43',
      productionDevelopment: null,
    } as unknown as LevelsPayload
    const html = render({ view: 'DEVELOP', levels })
    expect(html).toContain('data-status="FAILED"')
    const shown = html.slice(0, html.indexOf('hidden=""'))
    expect(shown).toContain('GRADE_LIMIT: L05 access cannot reach its entry')
  })

  it('an action error is announced in the context that owns it', () => {
    const html = render({ view: 'MINING', miningError: 'STOPES_STALE: regenerate levels' })
    expect(html).toContain('role="alert"')
    expect(html).toContain('STOPES_STALE: regenerate levels')
    expect(render({ view: 'DEVELOP', miningError: 'STOPES_STALE' })).not.toContain('STOPES_STALE')
  })

  it('every context says so when no design is active', () => {
    for (const view of ['DEVELOP', 'NETWORK', 'MINING'] as const) {
      expect(render({ view, rampReady: false })).toContain('No active design yet')
    }
    expect(render({ view: 'DEVELOP', rampReady: true })).not.toContain('No active design yet')
  })
})

describe('key metrics stay in the primary view, detailed numbers move to Details', () => {
  const levels = {
    status: 'SUCCESS',
    failureReason: null,
    entrySource: 'LEVEL_ACCESS',
    developmentGeometry: 'SECTION_FOOTWALL_OFFSET_TRACE',
    productionDevelopment: null,
    metrics: {
      driftPieceCount: 12,
      crosscutCount: 24,
      stationPitch: 35,
      totalDriftLength3d: 1234.5,
      totalCrosscutLength3d: 678.9,
      stationsPerLevel: 4,
    },
  } as unknown as LevelsPayload

  it('shows the headline counts above the fold and the lengths inside Details', () => {
    const html = render({ view: 'DEVELOP', levels })
    const above = html.slice(0, html.indexOf('hidden=""'))
    expect(above).toContain('12 drift pieces')
    expect(above).toContain('24 crosscuts')
    const details = html.slice(html.indexOf('hidden=""'))
    expect(details).toContain('1235 m')
    expect(details).toContain('679 m')
    expect(details).toContain('SECTION_FOOTWALL_OFFSET_TRACE')
  })

  it('network keeps nodes / edges / connectivity visible and lengths in Details', () => {
    const network = {
      status: 'SUCCESS',
      failureReason: null,
      validation: { connected: true },
      surfacePathAdvisory: [{ requiredPaths: 2, perNode: [{ independentSurfacePaths: 1 }] }],
      metrics: {
        nodeCount: 143,
        edgeCount: 151,
        totalRampLength3d: 3825,
        verticalDropFromPortal: 460,
      },
    } as unknown as NetworkPayload
    const html = render({ view: 'NETWORK', network })
    const above = html.slice(0, html.indexOf('hidden=""'))
    expect(above).toContain('143 nodes')
    expect(above).toContain('151 edges')
    expect(above).toContain('connected')
    const details = html.slice(html.indexOf('hidden=""'))
    expect(details).toContain('3825 m')
    expect(details).toContain('1 / 2')
  })

  it('mining keeps counts visible and tonnage / grade proxy in Details', () => {
    const stopes = {
      status: 'SUCCESS',
      failureReason: null,
      metrics: {
        stopeCount: 48,
        levelIntervalCount: 6,
        stationsPerInterval: 8,
        totalGeometricVolumeM3: 2.5e6,
        totalTonnes: 6.8e6,
        weightedMeanGradeProxy: 4.12,
      },
    } as unknown as StopesPayload
    const timeline = {
      status: 'SUCCESS',
      failureReason: null,
      metrics: {
        taskCount: 312,
        developmentTaskCount: 264,
        stopeTaskCount: 48,
        endDay: 1840,
        firstStopingDay: 620,
      },
    } as unknown as TimelinePayload
    const html = render({ view: 'MINING', stopes, timeline })
    expect(html).toContain('48 stopes')
    expect(html).toContain('312 tasks')
    expect(html).toContain('end day 1840')
    const details = html.slice(html.indexOf('hidden=""'))
    expect(details).toContain('6.80 Mt')
    expect(details).toContain('4.12')
    expect(details).toContain('day 620')
  })

  it('an access-only development sweep is stated, not left to be inferred', () => {
    const mesh = {
      status: 'SUCCESS',
      failureReason: null,
      byKind: {
        LEVEL_ACCESS: { developmentCount: 3 },
        DRIFT: { developmentCount: 0 },
        CROSSCUT: { developmentCount: 0 },
      },
      triangleCount: 9000,
      primitiveCount: 4,
      glbBytes: 51200,
      generationSeconds: 1.2,
    } as unknown as DevelopmentMeshReport
    const html = render({ view: 'DEVELOP', developmentMesh: mesh, levels: null })
    expect(html).toContain('3 access')
    expect(html).toContain('data-status="READY"')
  })
})

describe('no implementation history in the Design workflow copy (§12)', () => {
  it('no phase or rule number reaches the user', () => {
    for (const view of ['DEVELOP', 'NETWORK', 'MINING'] as const) {
      const html = render({ view })
      expect(html).not.toMatch(/Phase\s?\d/)
      expect(html).not.toMatch(/rules?\s\d/)
    }
  })
})
