import type { AnalysisTab } from '@/components/panels/workflowTabs'
import { ANALYSIS_TABS } from '@/components/panels/workflowTabs'
import type { IconName } from '@/components/ui/icons'
import type { StageId, ViewMode, WorkflowStep } from '@/types/workflow'
import { resettable, STAGE_LABEL, stepOf, type StageGlyph, WORKFLOW_STEPS } from './workflow'

/**
 * Hardening PR-3 — the ribbon model (pure).
 *
 *   ┌ MineGen-AI · File ▾ │ 1 Setup │ 2 Design │ … │ 7 Export │ View │ ┐  ← tabs
 *   │ [New][Open][Demos] │ [Scenario ✓][Method ✓][Access ●] │  ↺ Reset… ⟳ │  ← band
 *
 * Like an Office / CAD ribbon, clicking a TAB reveals the functions of that
 * step in a BAND of grouped tool buttons. The seven step tabs keep the
 * guided order (rule 191: order is the screen); the band of a step tab
 * carries that step's STAGES as navigation tools — each with the stage's
 * status glyph (the same presentation the stepper showed: a backend artifact
 * status, never a new vocabulary) — plus the step's commands. The VIEW tab
 * (3D / 4D / Walk, camera presets, panes, the flow dock) is a viewport tab,
 * not a workflow step: selecting it changes no stage. The QUICK ACCESS area
 * at the right of the band is the same in every tab: "Reset from <stage>"
 * and "Reset mine" — the two ways back, always one click away.
 *
 * Nothing here decides whether an ACTION is enabled (every feature keeps its
 * own prerequisite logic, and a stage's one primary action stays in the
 * controls column); the band's tools navigate, switch views or open the
 * backend-plan reset confirmations. The model is a pure function of the
 * viewer state it is given, so it is tested as data.
 */

export type RibbonTab = WorkflowStep | 'VIEW'

export interface RibbonTabSpec {
  id: RibbonTab
  /** the step number, null for the View tab */
  index: number | null
  label: string
}

export const RIBBON_TABS: readonly RibbonTabSpec[] = [
  ...WORKFLOW_STEPS.map((s) => ({ id: s.id, index: s.index, label: s.label })),
  { id: 'VIEW', index: null, label: 'View' },
]

/** the tab the band shows: an explicit View selection, else the current
 * stage's step (a stage change always returns the band to its step) */
export function effectiveTab(selected: RibbonTab | null, stage: StageId): RibbonTab {
  return selected ?? stepOf(stage)
}

export type CameraPreset = 'ISO' | 'TOP' | 'FIT'
export type Pane = 'controls' | 'results'

/** what a command tool does — dispatched by the ribbon to store actions only */
export type RibbonCommand =
  | { type: 'GO'; stage: StageId }
  | { type: 'NEW_MINE' }
  | { type: 'FILE_MENU'; section: 'OPEN' | 'DEMOS' }
  | { type: 'RESET_MINE' }
  | { type: 'RESET_FROM'; stage: StageId }
  | { type: 'VIEW'; view: ViewMode }
  | { type: 'CAMERA'; preset: CameraPreset }
  | { type: 'PANE'; pane: Pane; visible: boolean }
  | { type: 'FLOW_DOCK'; visible: boolean }
  | { type: 'ANALYSIS_TAB'; tab: AnalysisTab }
  | { type: 'ANALYSIS_3D'; show: boolean }
  | { type: 'IMPORT_RESULTS' }

export interface StageTool {
  kind: 'STAGE'
  id: string
  label: string
  icon: IconName
  hint: string
  stage: StageId
  glyph: StageGlyph
  current: boolean
}

export interface CommandTool {
  kind: 'COMMAND'
  id: string
  label: string
  icon: IconName
  hint: string
  command: RibbonCommand
  /** a toggle / selection tool shows its pressed state */
  active?: boolean | undefined
  disabled: boolean
  /** why the tool is disabled (shown as its title) */
  reason?: string | undefined
  /** a destructive tool (the reset confirmations) is drawn in the danger tone */
  danger?: boolean | undefined
}

export type RibbonTool = StageTool | CommandTool

export interface RibbonGroup {
  id: string
  label: string
  tools: readonly RibbonTool[]
}

export interface RibbonContext {
  stage: StageId
  glyphs: Record<StageId, StageGlyph>
  view: ViewMode
  /** the walkthrough readiness message, null when Walk is ready */
  walkBlocked: string | null
  hasScenario: boolean
  hasScene: boolean
  /** a baked demo is open (viewer-only: no reset, no generation) */
  demo: boolean
  /** a mounted card reports a running job (a reset waits for it) */
  jobRunning: boolean
  flowDock: boolean
  panes: Record<Pane, boolean>
  analysisTab: AnalysisTab
  analysisShow3d: boolean
}

export const STAGE_ICON: Record<StageId, IconName> = {
  SCENARIO: 'scenario',
  METHOD: 'method',
  ACCESS: 'access',
  LAYOUT: 'layout',
  LEVELS: 'levels',
  EXCAVATION: 'excavation',
  SHAFTS: 'shafts',
  NETWORK: 'network',
  CAPABILITY: 'capability',
  PRODUCTION: 'production',
  SCHEDULE: 'schedule',
  COMMUNICATION: 'communication',
  SENSORS: 'sensors',
  ANALYSIS: 'analysis',
  EXPORT: 'export',
}

/** one line per stage: what the stage does (the tool's title) */
export const STAGE_HINT: Record<StageId, string> = {
  SCENARIO: 'Create or open a mine: preset, seed, faults — the world is generated in one step',
  METHOD: 'Mining method and its parameters, decided before the layout',
  ACCESS: 'Access strategy: ramp only, or ramp + declared shafts',
  LAYOUT: 'Layout v2 candidates: enumerate, select and activate a ramp',
  LEVELS: 'Level development: accesses, drifts and crosscuts on the active ramp',
  EXCAVATION: 'Excavation meshes: ramp tunnel and level development sweeps',
  SHAFTS: 'Plan the declared shafts and sweep their mesh (optional without a declaration)',
  NETWORK: 'Mine network: nodes, edges and surface-path advisory',
  CAPABILITY: 'Capability graph over the network: required paths and egress advisory',
  PRODUCTION: 'Production geometry of the active mining method',
  SCHEDULE: 'Schedule: the development and production timeline (4D)',
  COMMUNICATION: 'Communication placement and coverage planning',
  SENSORS: 'Gas sensor placement and coverage planning',
  ANALYSIS: 'Analysis workspace: quantities, planning economics, rules, layouts',
  EXPORT: 'Export: MineExchange bundle and the external adapter packages',
}

const ANALYSIS_ICON: Record<AnalysisTab, IconName> = {
  OVERVIEW: 'overview',
  ECONOMICS: 'economics',
  SENSITIVITY: 'sensitivity',
  SCHEDULE: 'schedule',
  RULES: 'rules',
  LAYOUT_COMPARISON: 'layouts',
  SIMULATION: 'simulation',
}

function stageTools(stages: readonly StageId[], ctx: RibbonContext): StageTool[] {
  return stages.map((stage) => ({
    kind: 'STAGE',
    id: `stage-${stage}`,
    label: STAGE_LABEL[stage],
    icon: STAGE_ICON[stage],
    hint: STAGE_HINT[stage],
    stage,
    glyph: ctx.glyphs[stage],
    current: ctx.stage === stage,
  }))
}

function command(
  id: string,
  label: string,
  icon: IconName,
  hint: string,
  cmd: RibbonCommand,
  extra: Partial<Pick<CommandTool, 'active' | 'disabled' | 'reason' | 'danger'>> = {},
): CommandTool {
  return {
    kind: 'COMMAND',
    id,
    label,
    icon,
    hint,
    command: cmd,
    disabled: false,
    ...extra,
  }
}

/** the band of a tab: its groups of tools, in display order */
export function ribbonBand(tab: RibbonTab, ctx: RibbonContext): RibbonGroup[] {
  if (tab === 'VIEW') return viewBand(ctx)
  const step = WORKFLOW_STEPS.find((s) => s.id === tab) ?? WORKFLOW_STEPS[0]!
  const stages: RibbonGroup = {
    id: `${step.id}-stages`,
    label: `${String(step.index)} ${step.label}`,
    tools: stageTools(step.stages, ctx),
  }
  switch (step.id) {
    case 'SETUP':
      return [
        {
          id: 'mine',
          label: 'Mine',
          tools: [
            command('new-mine', 'New mine', 'newMine', 'Create a new mine (Setup › Scenario)', {
              type: 'NEW_MINE',
            }),
            command('open-mine', 'Open…', 'open', 'Open a saved mine', {
              type: 'FILE_MENU',
              section: 'OPEN',
            }),
            command('demos', 'Demos', 'demos', 'Open a baked demo mine (read-only)', {
              type: 'FILE_MENU',
              section: 'DEMOS',
            }),
          ],
        },
        stages,
      ]
    case 'ANALYSIS':
      return [
        stages,
        {
          id: 'analysis-tabs',
          label: 'Workspace',
          tools: ANALYSIS_TABS.map((t) =>
            command(
              `analysis-${t.id}`,
              t.label,
              ANALYSIS_ICON[t.id],
              `Analysis › ${t.label}`,
              { type: 'ANALYSIS_TAB', tab: t.id },
              {
                active: ctx.analysisTab === t.id,
                disabled: !ctx.hasScenario,
                reason: ctx.hasScenario ? undefined : 'Open a mine first',
              },
            ),
          ),
        },
        {
          id: 'analysis-view',
          label: 'Context',
          tools: [
            command(
              'analysis-3d',
              '3D context',
              'view3d',
              'Show the 3D scene beside the Analysis workspace',
              { type: 'ANALYSIS_3D', show: !ctx.analysisShow3d },
              { active: ctx.analysisShow3d, disabled: !ctx.hasScene },
            ),
          ],
        },
      ]
    case 'EXPORT':
      return [
        stages,
        {
          id: 'results',
          label: 'Results',
          tools: [
            command(
              'import-results',
              'Import results…',
              'import',
              'Import external simulation results (Analysis › Simulation Results)',
              { type: 'IMPORT_RESULTS' },
              {
                disabled: !ctx.hasScenario,
                reason: ctx.hasScenario ? undefined : 'Open a mine first',
              },
            ),
          ],
        },
      ]
    default:
      return [stages]
  }
}

function viewBand(ctx: RibbonContext): RibbonGroup[] {
  const views: { view: ViewMode; label: string; icon: IconName; hint: string }[] = [
    { view: '3D', label: '3D', icon: 'view3d', hint: 'The static final layout' },
    { view: '4D', label: '4D', icon: 'view4d', hint: 'The scheduled development over time' },
    {
      view: 'WALK',
      label: 'Walk',
      icon: 'walk',
      hint: 'First-person walkthrough of the excavation',
    },
  ]
  const inWalk = ctx.view === 'WALK'
  return [
    {
      id: 'view-mode',
      label: 'View',
      tools: views.map((v) =>
        command(
          `view-${v.view}`,
          v.label,
          v.icon,
          v.view === 'WALK' && ctx.walkBlocked ? ctx.walkBlocked : v.hint,
          { type: 'VIEW', view: v.view },
          {
            active: ctx.view === v.view,
            disabled: v.view === 'WALK' && ctx.walkBlocked !== null && ctx.view !== 'WALK',
            reason: v.view === 'WALK' && ctx.walkBlocked ? ctx.walkBlocked : undefined,
          },
        ),
      ),
    },
    {
      id: 'camera',
      label: 'Camera',
      tools: (
        [
          ['ISO', 'Iso', 'iso', 'Isometric view of the orebody'],
          ['TOP', 'Top', 'top', 'Plan view from above'],
          ['FIT', 'Fit', 'fit', 'Fit the whole world'],
        ] as const
      ).map(([preset, label, icon, hint]) =>
        command(
          `camera-${preset}`,
          label,
          icon,
          hint,
          { type: 'CAMERA', preset },
          {
            disabled: !ctx.hasScene || inWalk,
            reason: !ctx.hasScene ? 'Generate a world first' : inWalk ? 'Not in Walk' : undefined,
          },
        ),
      ),
    },
    {
      id: 'panels',
      label: 'Panels',
      tools: [
        command(
          'pane-controls',
          'Controls',
          'paneLeft',
          'Show or hide the Controls column',
          { type: 'PANE', pane: 'controls', visible: !ctx.panes.controls },
          { active: ctx.panes.controls, disabled: inWalk },
        ),
        command(
          'pane-results',
          'Results',
          'paneRight',
          'Show or hide the Status & results column',
          { type: 'PANE', pane: 'results', visible: !ctx.panes.results },
          { active: ctx.panes.results, disabled: inWalk },
        ),
        command(
          'flow-dock',
          'Flow',
          'flow',
          'Show or hide the mine development flow (stage nodes)',
          { type: 'FLOW_DOCK', visible: !ctx.flowDock },
          { active: ctx.flowDock, disabled: inWalk },
        ),
      ],
    },
  ]
}

/**
 * The quick-access tools shown at the right of EVERY band: the two ways
 * back. "Reset from <stage>" asks the backend plan of the current stage
 * (rule 219); "Reset mine" asks the from=WORLD plan and regenerates the
 * world from the same seed (rules 40 / 46 / 119). A demo is viewer-only, so
 * neither exists there; both wait for a running job.
 */
export function quickAccess(ctx: RibbonContext): CommandTool[] {
  if (ctx.demo) return []
  const stageResettable = ctx.hasScene && resettable(ctx.stage)
  const stageReason = !ctx.hasScene
    ? 'Generate a world first'
    : !resettable(ctx.stage)
      ? 'This stage owns no design artifact'
      : ctx.jobRunning
        ? 'A job is running — Reset waits until it finishes'
        : undefined
  const mineReason = !ctx.hasScene
    ? 'Generate a world first'
    : ctx.jobRunning
      ? 'A job is running — Reset waits until it finishes'
      : undefined
  return [
    command(
      'reset-from-here',
      `Reset from ${STAGE_LABEL[ctx.stage]}`,
      'resetStage',
      stageReason ?? `Delete the ${STAGE_LABEL[ctx.stage]} result and everything derived from it`,
      { type: 'RESET_FROM', stage: ctx.stage },
      { disabled: !stageResettable || ctx.jobRunning, reason: stageReason, danger: true },
    ),
    command(
      'reset-mine',
      'Reset mine',
      'resetMine',
      mineReason ??
        'Back to the generated world: every design artifact is cleared and the world is regenerated from the same seed',
      { type: 'RESET_MINE' },
      { disabled: !ctx.hasScene || ctx.jobRunning, reason: mineReason, danger: true },
    ),
  ]
}
