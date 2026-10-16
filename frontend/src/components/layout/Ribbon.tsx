import { useCallback, useMemo } from 'react'
import { Icon } from '@/components/ui/icons'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useTimelineStore } from '@/stores/timelineStore'
import { useViewerStore } from '@/stores/viewerStore'
import type { StageId } from '@/types/workflow'
import {
  temporalReadinessMessage,
  temporalWalkthroughReadiness,
  walkthroughReadiness,
} from '@/walkthrough/readiness'
import {
  effectiveTab,
  quickAccess,
  RIBBON_TABS,
  ribbonBand,
  type CommandTool,
  type RibbonCommand,
  type RibbonContext,
  type RibbonGroup,
  type RibbonTab,
  type RibbonTool,
  type StageTool,
} from './ribbonModel'
import { runningStages, useShellStore } from './shellStore'
import { useStageGlyphs } from './useStageGlyphs'
import { entryStageOf, GLYPH_TEXT } from './workflow'

/**
 * Hardening PR-3 — the Office / CAD ribbon: a TAB row in the top bar and a
 * tool BAND under it (`ribbonModel.ts` decides the content; this file only
 * renders it and dispatches each tool to a store action).
 *
 * A step tab opens its NEXT / failed stage (else its first stage) exactly as
 * the PR-1 ribbon did; the View tab selects the viewport tools without
 * changing the stage. Every tool is navigation, a view choice or a request
 * for one of the backend-plan reset confirmations (`ResetDialogs`): the band
 * runs no generation, no mutation and no layer reset, so a stage's ONE
 * primary action stays in the controls column and the "one enabled primary
 * button" invariant is untouched (the band's buttons carry no
 * `data-variant`).
 */

export function RibbonTabs() {
  const stage = useViewerStore((s) => s.stage)
  const setStage = useViewerStore((s) => s.setStage)
  const ribbonTab = useViewerStore((s) => s.ribbonTab)
  const setRibbonTab = useViewerStore((s) => s.setRibbonTab)
  const glyphs = useStageGlyphs()
  const active = effectiveTab(ribbonTab, stage)
  return (
    <nav className="ml-4 flex gap-0.5" aria-label="ribbon tabs" data-testid="ribbon-tabs">
      {RIBBON_TABS.map((tab) => {
        const current = tab.id === active
        return (
          <button
            key={tab.id}
            type="button"
            onClick={() => {
              if (tab.id === 'VIEW') setRibbonTab('VIEW')
              else setStage(entryStageOf(tab.id, glyphs))
            }}
            aria-current={current ? 'step' : undefined}
            data-step={tab.id}
            className={[
              'plate whitespace-nowrap rounded-sm px-2 py-1 text-[12px] transition-colors',
              current
                ? 'bg-rock-700 text-lamp shadow-[inset_0_-2px_0_0_var(--color-lamp)]'
                : 'text-chalk-dim hover:bg-rock-700/60 hover:text-chalk',
              tab.id === 'VIEW' ? 'ml-2 border-l border-rock-700 pl-3' : '',
            ].join(' ')}
          >
            {tab.index !== null ? (
              <span className="readout mr-1 text-[10px] text-mute">{tab.index}</span>
            ) : null}
            {tab.label}
          </button>
        )
      })}
    </nav>
  )
}

/** the live ribbon context from the stores (presentation inputs only) */
function useRibbonContext(): RibbonContext {
  const stage = useViewerStore((s) => s.stage)
  const mode = useViewerStore((s) => s.mode)
  const view = useViewerStore((s) => s.viewMode())
  const flowDock = useViewerStore((s) => s.flowDock)
  const panes = useViewerStore((s) => s.panes)
  const analysisTab = useViewerStore((s) => s.analysisTab)
  const analysisShow3d = useViewerStore((s) => s.analysisShow3d)
  const scenario = useScenarioStore((s) => s.scenario)
  const scene = useScenarioStore((s) => s.scene)
  const demo = useScenarioStore((s) => s.demo !== null)
  const currentDay = useTimelineStore((s) => s.currentDay)
  const tones = useShellStore((s) => s.stageTones)
  const glyphs = useStageGlyphs()
  // the same readiness gate the view switcher applies (rules 111–118)
  const readiness =
    mode === '4D'
      ? temporalWalkthroughReadiness(scene, currentDay, scenario?.ramp ?? null)
      : walkthroughReadiness(scene)
  const walkBlocked = readiness === 'READY' ? null : (temporalReadinessMessage(readiness) ?? null)
  const jobRunning = runningStages(tones).size > 0
  return useMemo(
    () => ({
      stage,
      glyphs,
      view,
      walkBlocked,
      hasScenario: scenario !== null,
      hasScene: scene !== null,
      demo,
      jobRunning,
      flowDock,
      panes,
      analysisTab,
      analysisShow3d,
    }),
    [
      stage,
      glyphs,
      view,
      walkBlocked,
      scenario,
      scene,
      demo,
      jobRunning,
      flowDock,
      panes,
      analysisTab,
      analysisShow3d,
    ],
  )
}

/** every ribbon command is a store action — never a request or a mutation */
function useRibbonDispatch(): (command: RibbonCommand) => void {
  const setStage = useViewerStore((s) => s.setStage)
  const setViewMode = useViewerStore((s) => s.setViewMode)
  const requestCameraPreset = useViewerStore((s) => s.requestCameraPreset)
  const setPane = useViewerStore((s) => s.setPane)
  const setFlowDock = useViewerStore((s) => s.setFlowDock)
  const setAnalysisTab = useViewerStore((s) => s.setAnalysisTab)
  const setAnalysisShow3d = useViewerStore((s) => s.setAnalysisShow3d)
  const openResetDialog = useShellStore((s) => s.openResetDialog)
  const requestFileMenu = useShellStore((s) => s.requestFileMenu)
  return useCallback(
    (command: RibbonCommand) => {
      switch (command.type) {
        case 'GO':
          setStage(command.stage)
          return
        case 'NEW_MINE':
          setStage('SCENARIO')
          return
        case 'FILE_MENU':
          requestFileMenu(command.section)
          return
        case 'RESET_MINE':
          openResetDialog({ kind: 'MINE' })
          return
        case 'RESET_FROM':
          openResetDialog({ kind: 'STAGE', stage: command.stage })
          return
        case 'VIEW':
          setViewMode(command.view)
          return
        case 'CAMERA':
          requestCameraPreset(command.preset)
          return
        case 'PANE':
          setPane(command.pane, command.visible)
          return
        case 'FLOW_DOCK':
          setFlowDock(command.visible)
          return
        case 'ANALYSIS_TAB':
          setStage('ANALYSIS')
          setAnalysisTab(command.tab)
          return
        case 'ANALYSIS_3D':
          setAnalysisShow3d(command.show)
          return
        case 'IMPORT_RESULTS':
          setStage('ANALYSIS')
          setAnalysisTab('SIMULATION')
          return
      }
    },
    [
      setStage,
      setViewMode,
      requestCameraPreset,
      setPane,
      setFlowDock,
      setAnalysisTab,
      setAnalysisShow3d,
      openResetDialog,
      requestFileMenu,
    ],
  )
}

export function RibbonBand() {
  const stage = useViewerStore((s) => s.stage)
  const setStage = useViewerStore((s) => s.setStage)
  const ribbonTab = useViewerStore((s) => s.ribbonTab)
  const ctx = useRibbonContext()
  const dispatch = useRibbonDispatch()
  const tab = effectiveTab(ribbonTab, stage)
  const groups = useMemo(() => ribbonBand(tab, ctx), [tab, ctx])
  const quick = useMemo(() => quickAccess(ctx), [ctx])
  return (
    <RibbonBandBody
      tab={tab}
      groups={groups}
      quick={quick}
      onStage={setStage}
      onCommand={dispatch}
    />
  )
}

interface BandProps {
  tab: RibbonTab
  groups: readonly RibbonGroup[]
  quick: readonly CommandTool[]
  onStage: (stage: StageId) => void
  onCommand: (command: RibbonCommand) => void
}

/** pure presentation of the band (testable as static markup) */
export function RibbonBandBody({ tab, groups, quick, onStage, onCommand }: BandProps) {
  return (
    <div
      className="flex h-[68px] shrink-0 items-stretch gap-1 overflow-x-auto border-b border-rock-700 bg-rock-900 px-2"
      data-testid="ribbon-band"
      data-tab={tab}
      role="toolbar"
      aria-label={`${tab.toLowerCase()} tools`}
    >
      {groups.map((group) => (
        <div
          key={group.id}
          role="group"
          aria-label={group.label}
          data-group={group.id}
          className="mr-1 flex flex-col justify-between border-r border-rock-800 pr-1"
        >
          <div className="flex gap-0.5">
            {group.tools.map((tool) => (
              <ToolButton key={tool.id} tool={tool} onStage={onStage} onCommand={onCommand} />
            ))}
          </div>
          <div className="plate pb-0.5 text-center text-[9px] text-mute">{group.label}</div>
        </div>
      ))}
      {quick.length > 0 ? (
        <div
          className="ml-auto flex flex-col justify-between border-l border-rock-700 pl-2"
          data-testid="ribbon-quick-access"
          role="group"
          aria-label="Quick access"
        >
          <div className="flex gap-0.5">
            {quick.map((tool) => (
              <ToolButton key={tool.id} tool={tool} onStage={onStage} onCommand={onCommand} />
            ))}
          </div>
          <div className="plate pb-0.5 text-center text-[9px] text-mute">Reset</div>
        </div>
      ) : null}
    </div>
  )
}

const GLYPH_TONE: Record<StageTool['glyph'], string> = {
  DONE: 'text-lamp',
  NEXT: 'text-chalk',
  RUNNING: 'text-chalk',
  FAILED: 'text-danger',
  WAITING: 'text-mute',
  OPTIONAL: 'text-mute',
}

const BASE =
  'flex h-[52px] w-[64px] flex-col items-center justify-center gap-0.5 rounded-sm px-1 text-[10px] leading-none transition-colors disabled:cursor-not-allowed disabled:opacity-40'

function ToolButton({
  tool,
  onStage,
  onCommand,
}: {
  tool: RibbonTool
  onStage: (stage: StageId) => void
  onCommand: (command: RibbonCommand) => void
}) {
  if (tool.kind === 'STAGE') {
    return (
      <button
        type="button"
        onClick={() => onStage(tool.stage)}
        aria-current={tool.current ? 'step' : undefined}
        data-stage={tool.stage}
        data-glyph={tool.glyph}
        title={`${tool.hint} — ${tool.glyph.toLowerCase()}`}
        className={[
          BASE,
          tool.current
            ? 'bg-rock-700 text-chalk shadow-[inset_0_-2px_0_0_var(--color-lamp)]'
            : 'text-chalk-dim hover:bg-rock-800 hover:text-chalk',
        ].join(' ')}
      >
        <span className="relative">
          <Icon name={tool.icon} size={20} />
          <span
            aria-hidden
            className={`readout absolute -right-2.5 -top-1.5 text-[10px] ${GLYPH_TONE[tool.glyph]}`}
          >
            {GLYPH_TEXT[tool.glyph]}
          </span>
        </span>
        <span className="plate whitespace-nowrap">{tool.label}</span>
      </button>
    )
  }
  return (
    <button
      type="button"
      onClick={() => onCommand(tool.command)}
      disabled={tool.disabled}
      aria-pressed={tool.active}
      data-tool={tool.id}
      title={tool.reason ?? tool.hint}
      className={[
        BASE,
        tool.active
          ? 'bg-rock-700 text-lamp shadow-[inset_0_-2px_0_0_var(--color-lamp)]'
          : tool.danger
            ? 'text-chalk-dim hover:bg-rock-800 hover:text-danger'
            : 'text-chalk-dim hover:bg-rock-800 hover:text-chalk',
      ].join(' ')}
    >
      <Icon name={tool.icon} size={20} />
      <span className="plate whitespace-nowrap">{tool.label}</span>
    </button>
  )
}
