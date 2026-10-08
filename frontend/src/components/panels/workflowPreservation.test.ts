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
import { ANALYSIS_TABS, DESIGN_TABS, SYSTEMS_TABS } from './workflowTabs'

const HERE = join(__dirname)
const LAYOUT = join(__dirname, '..', 'layout')
const read = (p: string) => readFileSync(p, 'utf8')
const unique = (src: string, re: RegExp) => [...new Set(src.match(re) ?? [])].sort()

const designPanel = read(join(HERE, 'DesignPanel.tsx'))
const accessPanel = read(join(HERE, 'AccessPanel.tsx'))

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
      'api.generateShaftMesh',
      'api.generateShafts',
      'api.generateTimeline',
      'api.generateWorld',
      'api.getScene',
      'api.replaceScenario',
      'api.submitDevelopmentMesh',
      'api.submitTunnel',
    ])
    // PR #54 review B3: the shaft DECLARATION (scenario PUT + world
    // regeneration + scene reload, the collar suggestion) moved to Setup ›
    // Access — the Design › Shafts card only plans and sweeps
    expect(unique(accessPanel, /api\.[a-zA-Z0-9]+/g)).toEqual([
      'api.generateWorld',
      'api.getScene',
      'api.replaceScenario',
      'api.suggestShaftCollar',
    ])
  })

  it('keeps the whole scene invalidation chain', () => {
    expect(unique(designPanel, /after[A-Za-z]+Regen/g)).toEqual([
      'afterCapabilityGraphRegen',
      'afterDevelopmentMeshRegen',
      'afterLevelsRegen',
      'afterNetworkRegen',
      'afterShaftMeshRegen',
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
      "setLayerVisible('shaftMesh', true)",
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
      ['onGenerateShaftMesh', 'api.generateShaftMesh'],
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

describe('switching a stage is presentation only (§19, hardening H1 §4.2)', () => {
  const design = read(join(LAYOUT, 'DesignWorkspace.tsx'))
  const systems = read(join(LAYOUT, 'SystemsWorkspace.tsx'))
  const analysis = read(join(LAYOUT, 'AnalysisWorkspace.tsx'))
  const stepper = read(join(LAYOUT, 'StepperBar.tsx'))

  it('every panel stays mounted and is gated on its own tab, never unmounted', () => {
    expect(design).toContain("<LayoutPanel active={tab === 'LAYOUT'} />")
    expect(design).toContain('<DesignPanel view={tab} />')
    expect(design).toContain("<LegacyDeclinePanel active={tab === 'LAYOUT'} />")
    expect(systems).toContain("<CommunicationPanel active={tab === 'COMMUNICATION'} />")
    expect(systems).toContain("<SensorPanel active={tab === 'SENSORS'} />")
    // Phase 22A/B: the analysis panel renders one tab's context, stays mounted
    expect(analysis).toContain('<AnalysisPanel view={tab} />')
    // a conditional mount would drop a running job poll
    for (const src of [design, systems, analysis]) {
      expect(src).not.toMatch(/tab === '[A-Z_]+' \?\s*</)
      expect(src).not.toMatch(/&&\s*<[A-Z]/)
    }
  })

  it('the stepper and the workspaces only set viewer state — they run no mutation', () => {
    expect(stepper).toContain('setStage(st)')
    expect(analysis).toContain('onSelect={setTab}')
    for (const src of [design, systems, analysis, stepper]) {
      expect(src).not.toContain('mutate')
      expect(src).not.toContain('setLayerVisible')
      expect(src).not.toContain('api.')
    }
  })

  it('the stage keeps the panel tab in step (the panels keep their view contract)', () => {
    const store = read(join(__dirname, '..', '..', 'stores', 'viewerStore.ts'))
    expect(store).toContain('designTab: designTabFor(stage)')
    expect(store).toContain('systemsTabFor(stage)')
  })
})

describe('Systems navigation (§26 E)', () => {
  it('exposes Communication and Sensors as the two subsystem tabs', () => {
    expect(SYSTEMS_TABS.map((t) => t.id)).toEqual(['COMMUNICATION', 'SENSORS'])
    expect(SYSTEMS_TABS.map((t) => t.label)).toEqual(['Communication', 'Sensors'])
  })

  it('every tab id is unique in every tab set', () => {
    for (const tabs of [DESIGN_TABS, SYSTEMS_TABS, ANALYSIS_TABS]) {
      expect(new Set(tabs.map((t) => t.id)).size).toBe(tabs.length)
    }
  })
})

describe('the View panel keeps Layers reachable and independent (§6, hardening H1 §4.2)', () => {
  const left = read(join(LAYOUT, 'LeftPanel.tsx'))
  const right = read(join(LAYOUT, 'RightPanel.tsx'))
  const view = read(join(HERE, 'ViewPanel.tsx'))
  const layers = read(join(HERE, 'LayerPanel.tsx'))

  it('the Visibility tree sits in the right column, outside every workflow panel', () => {
    expect(right).toContain('<ViewPanel />')
    expect(view).toContain('<LayerTree />')
    for (const f of ['DesignWorkspace.tsx', 'SystemsWorkspace.tsx', 'AnalysisWorkspace.tsx']) {
      expect(read(join(LAYOUT, f))).not.toContain('LayerTree')
    }
    expect(left).not.toContain('LayerTree')
  })

  it('the layer store contract is untouched: toggleLayer only', () => {
    expect(layers).toContain('s.toggleLayer')
    expect(layers).toContain('onChange={() => toggle(r.id)}')
    expect(layers).not.toContain('setLayerVisible')
  })

  it('the slice query stays mounted while the section is collapsed', () => {
    expect(view).toContain('<SliceControls active={open} />')
    expect(layers).toContain('if (!scene || !active) return null')
  })

  it('the controls column is wide enough for the consolidated readouts (§15)', () => {
    expect(left).toContain('w-[320px]')
  })
})

describe('view modes are not workflow steps (hardening H1 §4.1)', () => {
  const top = read(join(LAYOUT, 'TopBar.tsx'))
  const switcher = read(join(LAYOUT, 'ViewSwitcher.tsx'))

  it('the ribbon lists the seven steps and no view mode', () => {
    expect(top).toContain('WORKFLOW_STEPS.map')
    expect(top).not.toContain('APP_MODES')
    expect(top).not.toContain("'WALKTHROUGH'")
  })

  it('3D | 4D | Walk live in the view switcher and keep the walkthrough readiness gate', () => {
    for (const label of ['3D', '4D', 'Walk']) expect(switcher).toContain(`label: '${label}'`)
    expect(switcher).toContain('temporalWalkthroughReadiness(')
    expect(switcher).toContain('walkthroughReadiness(scene)')
    expect(switcher).not.toContain('setStage')
  })

  it('INFRASTRUCTURE reads Systems while the enum value is unchanged', () => {
    const workflow = read(join(LAYOUT, 'workflow.ts'))
    expect(workflow).toContain("label: 'Systems'")
    expect(workflow).toContain("return 'INFRASTRUCTURE'")
  })
})
