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
  NetworkPayload,
  StopesPayload,
  TimelinePayload,
} from '@/types/scene'
import { DesignPanelBody, type DesignPanelBodyProps } from './DesignPanel'
import { CUT_FILL_DEFAULTS, LONGHOLE, METHOD_TABLE } from './miningMethod.fixture'
import { DESIGN_TABS, type DesignTab } from './workflowTabs'

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
    scenarioIdentity: 'scenario-a:1',
    methodPending: false,
    methodEnabled: true,
    onApplyMethod: () => undefined,
    production: null,
    productionPending: false,
    productionEnabled: false,
    onGenerateProduction: () => undefined,
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
  Production: 'MINING',
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

  it('Mining holds the method card (selector over the registry table) above Production', () => {
    const html = render({ view: 'MINING' })
    expect(html).toContain('>Production')
    expect(html).toContain('>Schedule')
    const card = html.slice(html.indexOf('Mining method'), html.indexOf('>Production'))
    expect(card).toContain('Longhole Open Stoping')
    expect(card).toContain('Implemented')
    expect(card).toContain('data-status="ACTIVE"')
    // Phase 21B/C: the selector lists EVERY registry method with its status
    expect(card).toContain('data-testid="mining-method-select"')
    for (const row of METHOD_TABLE) {
      expect(card).toContain(`${row.displayName.replace('&', '&amp;')} — `)
    }
    expect(card).toContain('Sublevel Caving — Not implemented')
    expect(card).toContain('Cut &amp; Fill — Implemented')
    expect(html.indexOf('Mining method')).toBeLessThan(html.indexOf('>Production'))
    // Longhole edits its three planning parameters
    const params = card.slice(card.indexOf('data-testid="mining-parameters"'))
    expect(params).toContain('Sublevel interval (m)')
    expect(params).toContain('Stope length (m)')
    expect(params).toContain('Minimum pillar (m)')
    expect(params).not.toContain('Lift height')
    // nothing is dirty yet, so Apply is present but disabled
    expect(card).toContain('Apply method')
    const details = card.slice(card.indexOf('hidden=""'))
    expect(details).toContain('Sublevel interval')
    expect(details).toContain('25 m')
    expect(details).toContain('Stope length')
    expect(details).toContain('20 m')
    expect(details).toContain('Minimum pillar')
    expect(details).toContain('15 m')
    // the generic production action names the active method's units
    expect(html).toContain('Generate Stopes')
  })

  it('a Cut & Fill scenario shows its own parameters and production action', () => {
    const html = render({
      view: 'MINING',
      miningMethod: {
        ...LONGHOLE,
        method: 'CUT_AND_FILL',
        displayName: 'Cut & Fill',
        productionKind: 'CUT_FILL',
        methodParameters: CUT_FILL_DEFAULTS,
      },
    })
    const card = html.slice(html.indexOf('Mining method'), html.indexOf('>Production'))
    expect(card).toContain('Lift height (m)')
    expect(card).toContain('Cut length (m)')
    expect(card).toContain('Panel length (m)')
    expect(card).toContain('Stoping direction')
    expect(card).toContain('Block order')
    expect(card).toContain('Concurrent panels (max)')
    expect(card).toContain('Sill mat cure (days)')
    expect(card).not.toContain('Stope length (m)')
    expect(html).toContain('Generate Cut &amp; Fill')
  })

  it('a Room & Pillar scenario shows its own parameters incl. bench mode', () => {
    const html = render({
      view: 'MINING',
      miningMethod: {
        ...LONGHOLE,
        method: 'ROOM_AND_PILLAR',
        displayName: 'Room & Pillar',
        productionKind: 'ROOM_PILLAR',
        methodParameters: {
          kind: 'ROOM_AND_PILLAR',
          roomWidthM: 8,
          pillarWidthM: 6,
          headingHeightM: 5,
          benchCount: 2,
          boundaryPillarM: 6,
        },
      },
    })
    const card = html.slice(html.indexOf('Mining method'), html.indexOf('>Production'))
    for (const label of [
      'Room width (m)',
      'Pillar width (m)',
      'Heading height (m)',
      'Bench mode',
      'Boundary pillar (m)',
    ]) {
      expect(card).toContain(label)
    }
    expect(card).toContain('data-testid="bench-mode-select"')
    expect(html).toContain('Generate Room &amp; Pillar')
  })

  it('an unsupported method reads "Not implemented" without implying a mine failure', () => {
    const html = render({
      view: 'MINING',
      miningMethod: {
        ...LONGHOLE,
        method: 'SUBLEVEL_CAVING',
        displayName: 'Sublevel Caving',
        implementationStatus: 'UNSUPPORTED_METHOD',
      },
    })
    const card = html.slice(html.indexOf('Mining method'), html.indexOf('>Production'))
    expect(card).toContain('Sublevel Caving')
    expect(card).toContain('Not implemented')
    expect(card).toContain('data-status="INACTIVE"')
    expect(card).not.toContain('data-status="FAILED"')
    expect(card).toContain('not implemented in this version')
    // review SHOULD_FIX 7: a method without a production implementation shows
    // the shared sublevel interval only — never the Longhole production
    // parameters — and offers no Longhole production action
    expect(card).toContain('Sublevel interval (m)')
    expect(card).not.toContain('Stope length (m)')
    expect(card).not.toContain('Minimum pillar (m)')
    const production = html.slice(html.indexOf('>Production'), html.indexOf('>Schedule'))
    expect(production).toContain('Not implemented')
    expect(production).not.toContain('Generate Stopes')
    expect(production).toContain('disabled=""')
    expect(production).toContain('no production geometry is generated')
  })

  it('the production action stays disabled for an unsupported method even when levels exist', () => {
    const html = render({
      view: 'MINING',
      productionEnabled: true, // the parent gate is also closed in DesignPanel; the body never trusts it alone
      miningMethod: {
        ...LONGHOLE,
        method: 'SHRINKAGE_STOPING',
        displayName: 'Shrinkage Stoping',
        implementationStatus: 'UNSUPPORTED_METHOD',
        productionKind: null,
      },
    })
    const production = html.slice(html.indexOf('>Production'), html.indexOf('>Schedule'))
    expect(production).toContain('Not implemented')
    expect(production).toContain('disabled=""')
  })

  it('without a loaded scene the method card is simply absent', () => {
    const html = render({ view: 'MINING', miningMethod: null })
    expect(html).not.toContain('Mining method')
    expect(html).toContain('>Production')
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
    const html = render({ view: 'MINING', production: stopes, timeline })
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
