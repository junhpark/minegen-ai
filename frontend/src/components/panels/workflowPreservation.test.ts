/**
 * Phase 20E §26 E/F — behaviour preservation across the UI consolidation.
 *
 * The consolidation is presentation only, so the endpoint set, the scene
 * invalidation chain and the layer reveals of each workflow action must be
 * exactly the pre-20E ones, and each panel must be gated on its own tab
 * rather than unmounted. These are asserted on the source text because the
 * wiring lives in hooks that need a store and a query client; the rendered
 * grouping is asserted in `designNavigation.test.tsx` and the real requests
 * are observed in the browser acceptance run.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { DESIGN_TABS, SYSTEMS_TABS } from './workflowTabs'

const HERE = join(__dirname)
const LAYOUT = join(__dirname, '..', 'layout')
const read = (p: string) => readFileSync(p, 'utf8')
const unique = (src: string, re: RegExp) => [...new Set(src.match(re) ?? [])].sort()

const designPanel = read(join(HERE, 'DesignPanel.tsx'))

describe('the mine-development endpoints are unchanged', () => {
  it('calls exactly the declared generation endpoints — no more, no fewer', () => {
    // Phase 21B/C: the Longhole-only stopes route is replaced by the
    // method-generic production route, and the method card's apply action is
    // the scenario PUT followed by world regeneration + a scene reload
    expect(unique(designPanel, /api\.[a-zA-Z0-9]+/g)).toEqual([
      'api.generateCapabilityGraph',
      'api.generateLevels',
      'api.generateNetwork',
      'api.generateProduction',
      'api.generateShafts',
      'api.generateTimeline',
      'api.generateWorld',
      'api.getScene',
      'api.replaceScenario',
      'api.submitDevelopmentMesh',
      'api.submitTunnel',
    ])
  })

  it('keeps the whole scene invalidation chain', () => {
    expect(unique(designPanel, /after[A-Za-z]+Regen/g)).toEqual([
      'afterCapabilityGraphRegen',
      'afterDevelopmentMeshRegen',
      'afterLevelsRegen',
      'afterNetworkRegen',
      'afterShaftsRegen',
      'afterStopesRegen',
      'afterTimelineRegen',
    ])
  })

  it('reveals the same layers on success', () => {
    expect(unique(designPanel, /setLayerVisible\('[a-zA-Z]+', true\)/g)).toEqual([
      "setLayerVisible('crosscuts', true)",
      "setLayerVisible('developmentMesh', true)",
      "setLayerVisible('levels', true)",
      "setLayerVisible('network', true)",
      "setLayerVisible('shafts', true)",
      "setLayerVisible('stopes', true)",
      "setLayerVisible('tunnelMesh', true)",
    ])
  })

  it('each action is bound to its own endpoint', () => {
    for (const [handler, call] of [
      ['onGenerateLevels', 'api.generateLevels'],
      ['onGenerateNetwork', 'api.generateNetwork'],
      ['onGenerateProduction', 'api.generateProduction'],
      ['onGenerateTimeline', 'api.generateTimeline'],
      ['onGenerateShafts', 'api.generateShafts'],
      ['onGenerateCapabilityGraph', 'api.generateCapabilityGraph'],
      ['onGenerateDevelopmentMesh', 'api.submitDevelopmentMesh'],
      ['onGenerateTunnel', 'api.submitTunnel'],
    ] as const) {
      const mutation = handler.replace('onG', 'g')
      expect(designPanel).toContain(`${handler}={() => ${mutation}.mutate()}`)
      expect(designPanel).toContain(call)
    }
  })
})

describe('the layout and legacy endpoints are unchanged', () => {
  it('layout keeps its search, select and activate calls and its invalidations', () => {
    const src = read(join(HERE, 'LayoutPanel.tsx'))
    expect(unique(src, /api\.[a-zA-Z0-9]+/g)).toEqual([
      'api.activateLayoutCandidate',
      'api.getDesignAssessment',
      'api.getJob',
      'api.getLevelAccesses',
      'api.selectLayoutCandidate',
      'api.submitLayoutV2',
    ])
    expect(unique(src, /afterLayout[A-Za-z]+/g)).toEqual([
      'afterLayoutActivate',
      'afterLayoutRegen',
      'afterLayoutSelect',
    ])
  })

  it('the legacy chain keeps its own endpoints and invalidations', () => {
    const src = read(join(HERE, 'LegacyDeclinePanel.tsx'))
    expect(unique(src, /api\.[a-zA-Z0-9]+/g)).toEqual([
      'api.generateTargets',
      'api.submitDecline',
      'api.submitSmooth',
    ])
    expect(unique(src, /afterLegacy[A-Za-z]+/g)).toEqual([
      'afterLegacySmoothRegen',
      'afterLegacyUpstreamRegen',
    ])
  })

  it('infrastructure keeps one endpoint and one invalidation each', () => {
    const comm = read(join(HERE, 'CommunicationPanel.tsx'))
    const sens = read(join(HERE, 'SensorPanel.tsx'))
    expect(unique(comm, /api\.[a-zA-Z0-9]+/g)).toEqual(['api.generateCommunication'])
    expect(unique(comm, /after[A-Za-z]+Regen/g)).toEqual(['afterCommunicationRegen'])
    expect(unique(sens, /api\.[a-zA-Z0-9]+/g)).toEqual(['api.generateSensors'])
    expect(unique(sens, /after[A-Za-z]+Regen/g)).toEqual(['afterSensorsRegen'])
  })

  it('the prerequisite helpers still gate the infrastructure actions', () => {
    expect(read(join(HERE, 'CommunicationPanel.tsx'))).toContain(
      'canGenerateCommunication(network)',
    )
    expect(read(join(HERE, 'SensorPanel.tsx'))).toContain('canGenerateSensors(network)')
  })
})

describe('switching a tab is presentation only (§19)', () => {
  const design = read(join(LAYOUT, 'DesignWorkspace.tsx'))
  const systems = read(join(LAYOUT, 'SystemsWorkspace.tsx'))

  it('every panel stays mounted and is gated on its own tab, never unmounted', () => {
    expect(design).toContain("<LayoutPanel active={tab === 'LAYOUT'} />")
    expect(design).toContain('<DesignPanel view={tab} />')
    expect(design).toContain("<LegacyDeclinePanel active={tab === 'LAYOUT'} />")
    expect(systems).toContain("<CommunicationPanel active={tab === 'COMMUNICATION'} />")
    expect(systems).toContain("<SensorPanel active={tab === 'SENSORS'} />")
    // a conditional mount would drop a running job poll
    for (const src of [design, systems]) {
      expect(src).not.toMatch(/tab === '[A-Z_]+' \?\s*</)
      expect(src).not.toMatch(/&&\s*<[A-Z]/)
    }
  })

  it('the tab handlers only set tab state — they run no mutation', () => {
    for (const src of [design, systems]) {
      expect(src).toContain('onSelect={setTab}')
      expect(src).not.toContain('mutate')
      expect(src).not.toContain('setLayerVisible')
      expect(src).not.toContain('api.')
    }
  })
})

describe('Systems navigation (§26 E)', () => {
  it('exposes Communication and Sensors as the two subsystem tabs', () => {
    expect(SYSTEMS_TABS.map((t) => t.id)).toEqual(['COMMUNICATION', 'SENSORS'])
    expect(SYSTEMS_TABS.map((t) => t.label)).toEqual(['Communication', 'Sensors'])
  })

  it('every tab id is unique in both tab sets', () => {
    for (const tabs of [DESIGN_TABS, SYSTEMS_TABS]) {
      expect(new Set(tabs.map((t) => t.id)).size).toBe(tabs.length)
    }
  })
})

describe('the left panel keeps Layers reachable and independent (§6)', () => {
  const left = read(join(LAYOUT, 'LeftPanel.tsx'))
  const layers = read(join(HERE, 'LayerPanel.tsx'))

  it('Layers sits outside the workflow tabs, at the bottom of the panel', () => {
    expect(left).toContain('<LayerPanel />')
    expect(left.indexOf('<LayerPanel />')).toBeGreaterThan(left.indexOf('Workspace />'))
    expect(read(join(LAYOUT, 'DesignWorkspace.tsx'))).not.toContain('LayerPanel')
    expect(read(join(LAYOUT, 'SystemsWorkspace.tsx'))).not.toContain('LayerPanel')
  })

  it('the layer store contract is untouched: toggleLayer only', () => {
    expect(layers).toContain('s.toggleLayer')
    expect(layers).toContain('onChange={() => toggle(r.id)}')
    expect(layers).not.toContain('setLayerVisible')
  })

  it('the slice query stays mounted while the section is collapsed', () => {
    expect(layers).toContain('<SliceControls active={open} />')
    expect(layers).toContain('if (!scene || !active) return null')
  })

  it('the panel is wide enough for the consolidated readouts (§15)', () => {
    expect(left).toContain('w-[320px]')
  })
})

describe('the mode labels are presentation only (§3)', () => {
  const top = read(join(LAYOUT, 'TopBar.tsx'))

  it('INFRASTRUCTURE reads Systems while the enum value is unchanged', () => {
    expect(top).toContain("INFRASTRUCTURE: 'Systems'")
    expect(top).toContain('APP_MODES.map')
    expect(top).not.toContain("'Infra'")
  })

  it('every mode keeps a full-word label', () => {
    for (const label of ['Design', 'Systems', '4D', 'Walkthrough', 'Analysis']) {
      expect(top).toContain(`'${label}'`)
    }
    expect(top).not.toContain("'Walk'")
  })
})
