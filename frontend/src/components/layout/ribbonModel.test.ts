import { describe, expect, it } from 'vitest'
import { ANALYSIS_TABS } from '@/components/panels/workflowTabs'
import { STAGE_IDS, type StageId } from '@/types/workflow'
import {
  effectiveTab,
  quickAccess,
  RIBBON_TABS,
  ribbonBand,
  type CommandTool,
  type RibbonContext,
  type RibbonTab,
  type StageTool,
} from './ribbonModel'
import { STAGE_LABEL, WORKFLOW_STEPS, type StageGlyph } from './workflow'

const WAITING = Object.fromEntries(STAGE_IDS.map((s) => [s, 'WAITING'])) as Record<
  StageId,
  StageGlyph
>

const ctx = (over: Partial<RibbonContext> = {}): RibbonContext => ({
  stage: 'LAYOUT',
  glyphs: {
    ...WAITING,
    SCENARIO: 'DONE',
    METHOD: 'DONE',
    ACCESS: 'DONE',
    LAYOUT: 'NEXT',
    SHAFTS: 'OPTIONAL',
  },
  view: '3D',
  walkBlocked: 'The ramp tunnel mesh is not generated',
  hasScenario: true,
  hasScene: true,
  demo: false,
  jobRunning: false,
  flowDock: true,
  panes: { controls: true, results: true },
  analysisTab: 'OVERVIEW',
  analysisShow3d: false,
  ...over,
})

const tools = (tab: RibbonTab, c: RibbonContext, groupId: string) => {
  const group = ribbonBand(tab, c).find((g) => g.id === groupId)
  if (!group) throw new Error(`no group ${groupId} in ${tab}`)
  return group.tools
}
const command = (tab: RibbonTab, c: RibbonContext, id: string): CommandTool => {
  const tool = ribbonBand(tab, c)
    .flatMap((g) => g.tools)
    .find((t) => t.id === id)
  if (!tool || tool.kind !== 'COMMAND') throw new Error(`no command ${id} in ${tab}`)
  return tool
}

describe('ribbon tabs (hardening PR-3)', () => {
  it('are the seven guided steps in order, then the View tab', () => {
    expect(RIBBON_TABS.map((t) => t.id)).toEqual([...WORKFLOW_STEPS.map((s) => s.id), 'VIEW'])
    expect(RIBBON_TABS.map((t) => t.index)).toEqual([1, 2, 3, 4, 5, 6, 7, null])
  })

  it('the band follows the current stage unless the View tab is selected', () => {
    expect(effectiveTab(null, 'LEVELS')).toBe('DESIGN')
    expect(effectiveTab(null, 'SENSORS')).toBe('SYSTEMS')
    expect(effectiveTab('VIEW', 'LEVELS')).toBe('VIEW')
    expect(effectiveTab('MINING', 'LEVELS')).toBe('MINING')
  })
})

describe('ribbon band — the step tabs', () => {
  it('every step tab carries exactly its stages, as navigation tools with the stage glyph', () => {
    const c = ctx()
    for (const step of WORKFLOW_STEPS) {
      const stageTools = tools(step.id, c, `${step.id}-stages`) as readonly StageTool[]
      expect(stageTools.map((t) => t.kind)).toEqual(step.stages.map(() => 'STAGE'))
      expect(stageTools.map((t) => t.stage)).toEqual([...step.stages])
      expect(stageTools.map((t) => t.label)).toEqual(step.stages.map((s) => STAGE_LABEL[s]))
      expect(stageTools.map((t) => t.glyph)).toEqual(step.stages.map((s) => c.glyphs[s]))
      expect(stageTools.filter((t) => t.current).map((t) => t.stage)).toEqual(
        step.stages.filter((s) => s === c.stage),
      )
    }
  })

  it('tool ids are unique within every band', () => {
    const c = ctx()
    for (const tab of RIBBON_TABS) {
      const ids = ribbonBand(tab.id, c).flatMap((g) => g.tools.map((t) => t.id))
      expect(new Set(ids).size).toBe(ids.length)
    }
  })

  it('Setup opens with the Mine group: new mine, open, demos — then its stages', () => {
    const groups = ribbonBand('SETUP', ctx())
    expect(groups.map((g) => g.id)).toEqual(['mine', 'SETUP-stages'])
    const mine = groups[0]!.tools as readonly CommandTool[]
    expect(mine.map((t) => t.id)).toEqual(['new-mine', 'open-mine', 'demos'])
    expect(mine.map((t) => t.command)).toEqual([
      { type: 'NEW_MINE' },
      { type: 'FILE_MENU', section: 'OPEN' },
      { type: 'FILE_MENU', section: 'DEMOS' },
    ])
    expect(mine.every((t) => !t.disabled)).toBe(true)
  })

  it('Analysis carries the workspace tabs (active = the current one) and the 3D-context toggle', () => {
    const c = ctx({ stage: 'ANALYSIS', analysisTab: 'ECONOMICS', analysisShow3d: true })
    const tabs = tools('ANALYSIS', c, 'analysis-tabs') as readonly CommandTool[]
    expect(tabs.map((t) => t.id)).toEqual(ANALYSIS_TABS.map((t) => `analysis-${t.id}`))
    expect(tabs.map((t) => t.command)).toEqual(
      ANALYSIS_TABS.map((t) => ({ type: 'ANALYSIS_TAB', tab: t.id })),
    )
    expect(tabs.filter((t) => t.active).map((t) => t.id)).toEqual(['analysis-ECONOMICS'])
    const three = command('ANALYSIS', c, 'analysis-3d')
    expect(three.active).toBe(true)
    expect(three.command).toEqual({ type: 'ANALYSIS_3D', show: false })
    // without a mine the workspace tabs are disabled with a reason
    const none = tools('ANALYSIS', ctx({ hasScenario: false, hasScene: false }), 'analysis-tabs')
    expect(
      none.every((t) => t.kind === 'COMMAND' && t.disabled && t.reason === 'Open a mine first'),
    ).toBe(true)
  })

  it('Export offers the results import (Analysis › Simulation Results)', () => {
    const tool = command('EXPORT', ctx({ stage: 'EXPORT' }), 'import-results')
    expect(tool.command).toEqual({ type: 'IMPORT_RESULTS' })
    expect(tool.disabled).toBe(false)
    expect(command('EXPORT', ctx({ hasScenario: false }), 'import-results').disabled).toBe(true)
  })
})

describe('ribbon band — the View tab', () => {
  it('has the view modes, the camera presets and the panel toggles', () => {
    expect(ribbonBand('VIEW', ctx()).map((g) => g.id)).toEqual(['view-mode', 'camera', 'panels'])
  })

  it('marks the active view and applies the Walk readiness gate', () => {
    const c = ctx()
    expect(command('VIEW', c, 'view-3D').active).toBe(true)
    expect(command('VIEW', c, 'view-4D').active).toBe(false)
    const walk = command('VIEW', c, 'view-WALK')
    expect(walk.disabled).toBe(true)
    expect(walk.reason).toBe('The ramp tunnel mesh is not generated')
    expect(walk.command).toEqual({ type: 'VIEW', view: 'WALK' })
    // ready → enabled; already walking → never disabled (it is the way out)
    expect(command('VIEW', ctx({ walkBlocked: null }), 'view-WALK').disabled).toBe(false)
    const inWalk = command('VIEW', ctx({ view: 'WALK' }), 'view-WALK')
    expect(inWalk.disabled).toBe(false)
    expect(inWalk.active).toBe(true)
  })

  it('camera presets need a world and are not offered in Walk', () => {
    const c = ctx()
    expect(command('VIEW', c, 'camera-ISO').command).toEqual({ type: 'CAMERA', preset: 'ISO' })
    expect(command('VIEW', c, 'camera-FIT').disabled).toBe(false)
    expect(command('VIEW', ctx({ hasScene: false }), 'camera-TOP').reason).toBe(
      'Generate a world first',
    )
    expect(command('VIEW', ctx({ view: 'WALK' }), 'camera-TOP').disabled).toBe(true)
  })

  it('panel toggles show their state and toggle it', () => {
    const c = ctx({ panes: { controls: true, results: false }, flowDock: false })
    const controls = command('VIEW', c, 'pane-controls')
    expect(controls.active).toBe(true)
    expect(controls.command).toEqual({ type: 'PANE', pane: 'controls', visible: false })
    const results = command('VIEW', c, 'pane-results')
    expect(results.active).toBe(false)
    expect(results.command).toEqual({ type: 'PANE', pane: 'results', visible: true })
    const flow = command('VIEW', c, 'flow-dock')
    expect(flow.active).toBe(false)
    expect(flow.command).toEqual({ type: 'FLOW_DOCK', visible: true })
  })
})

describe('quick access — the two ways back', () => {
  it('is "Reset from <stage>" and "Reset mine" on a resettable stage with a world', () => {
    const quick = quickAccess(ctx())
    expect(quick.map((t) => t.id)).toEqual(['reset-from-here', 'reset-mine'])
    expect(quick.map((t) => t.label)).toEqual(['Reset from Layout', 'Reset mine'])
    expect(quick.map((t) => t.command)).toEqual([
      { type: 'RESET_FROM', stage: 'LAYOUT' },
      { type: 'RESET_MINE' },
    ])
    expect(quick.every((t) => !t.disabled && t.danger === true)).toBe(true)
  })

  it('a Setup stage owns no design artifact: only Reset mine is offered enabled', () => {
    const [from, mine] = quickAccess(ctx({ stage: 'SCENARIO' }))
    expect(from?.disabled).toBe(true)
    expect(from?.reason).toBe('This stage owns no design artifact')
    expect(mine?.disabled).toBe(false)
  })

  it('needs a world, waits for a running job, and never exists in a demo', () => {
    for (const t of quickAccess(ctx({ hasScene: false }))) {
      expect(t.disabled).toBe(true)
      expect(t.reason).toBe('Generate a world first')
    }
    for (const t of quickAccess(ctx({ jobRunning: true }))) {
      expect(t.disabled).toBe(true)
      expect(t.reason).toBe('A job is running — Reset waits until it finishes')
    }
    expect(quickAccess(ctx({ demo: true }))).toEqual([])
  })
})
