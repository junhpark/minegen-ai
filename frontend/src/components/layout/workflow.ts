import type { AnalysisTab, DesignTab, SystemsTab } from '@/components/panels/workflowTabs'
import type { AppMode } from '@/types/enums'
import type { WorkflowStage, WorldScene } from '@/types/scene'
import { STAGE_IDS, type StageId, type WorkflowStep } from '@/types/workflow'

/**
 * Hardening H1 §4.1–4.3 — the guided workflow model (pure).
 *
 *   1 Setup · 2 Design · 3 Network · 4 Mining · 5 Systems · 6 Analysis · 7 Export
 *   [Scenario ✓][Method ✓][Layout ●][Levels ○][Excavation ○][Shafts –] …
 *
 * "Order is the screen": the stepper shows how far the mine has come and
 * what is next, from the scene manifest alone. Nothing here decides whether
 * an action is ENABLED (every feature keeps its own prerequisite logic) and
 * nothing here is a backend concept: the glyph of a stage is a presentation
 * of the artifact it owns (rule 191 — `StatusBadge` semantics, no new status
 * vocabulary), and the backend reset stage of a stage is an explicit map.
 */

export interface WorkflowStepSpec {
  id: WorkflowStep
  index: number
  label: string
  stages: readonly StageId[]
}

export const WORKFLOW_STEPS: readonly WorkflowStepSpec[] = [
  { id: 'SETUP', index: 1, label: 'Setup', stages: ['SCENARIO', 'METHOD'] },
  { id: 'DESIGN', index: 2, label: 'Design', stages: ['LAYOUT', 'LEVELS', 'EXCAVATION', 'SHAFTS'] },
  { id: 'NETWORK', index: 3, label: 'Network', stages: ['NETWORK', 'CAPABILITY'] },
  { id: 'MINING', index: 4, label: 'Mining', stages: ['PRODUCTION', 'SCHEDULE'] },
  { id: 'SYSTEMS', index: 5, label: 'Systems', stages: ['COMMUNICATION', 'SENSORS'] },
  { id: 'ANALYSIS', index: 6, label: 'Analysis', stages: ['ANALYSIS'] },
  { id: 'EXPORT', index: 7, label: 'Export', stages: ['EXPORT'] },
]

export const STAGE_LABEL: Record<StageId, string> = {
  SCENARIO: 'Scenario',
  METHOD: 'Method',
  LAYOUT: 'Layout',
  LEVELS: 'Levels',
  EXCAVATION: 'Excavation',
  SHAFTS: 'Shafts',
  NETWORK: 'Network',
  CAPABILITY: 'Capability',
  PRODUCTION: 'Production',
  SCHEDULE: 'Schedule',
  COMMUNICATION: 'Communication',
  SENSORS: 'Sensors',
  ANALYSIS: 'Analysis',
  EXPORT: 'Export',
}

const STEP_OF: Record<StageId, WorkflowStep> = Object.fromEntries(
  WORKFLOW_STEPS.flatMap((s) => s.stages.map((st) => [st, s.id])),
) as Record<StageId, WorkflowStep>

export function stepOf(stage: StageId): WorkflowStep {
  return STEP_OF[stage]
}

export function stepSpec(step: WorkflowStep): WorkflowStepSpec {
  return WORKFLOW_STEPS.find((s) => s.id === step) ?? WORKFLOW_STEPS[0]!
}

export function stagesOfStep(step: WorkflowStep): readonly StageId[] {
  return stepSpec(step).stages
}

/** the application mode a stage's CONTROLS belong to (the 4D / Walk VIEW
 * modes are chosen separately and never by a stage) */
export function modeForStage(stage: StageId): AppMode {
  switch (stepOf(stage)) {
    case 'SYSTEMS':
      return 'INFRASTRUCTURE'
    case 'ANALYSIS':
      return 'ANALYSIS'
    default:
      return 'DESIGN'
  }
}

/** which pre-shell Design tab holds a stage's cards (the panel containers
 * keep their `view` contract) */
export function designTabFor(stage: StageId): DesignTab {
  switch (stage) {
    case 'LEVELS':
    case 'EXCAVATION':
    case 'SHAFTS':
      return 'DEVELOP'
    case 'NETWORK':
    case 'CAPABILITY':
      return 'NETWORK'
    case 'METHOD':
    case 'PRODUCTION':
    case 'SCHEDULE':
      return 'MINING'
    default:
      return 'LAYOUT'
  }
}

export function systemsTabFor(stage: StageId): SystemsTab | null {
  if (stage === 'COMMUNICATION' || stage === 'SENSORS') return stage
  return null
}

export function analysisTabFor(stage: StageId): AnalysisTab | null {
  return stage === 'ANALYSIS' ? 'OVERVIEW' : null
}

/**
 * The backend reset stage a stepper stage maps to (hardening H1 §4.4).
 * `WORLD` is preview-only (the Setup stages are scenario-document edits);
 * Analysis and Export own no artifact and are never reset.
 */
export function resetStageFor(stage: StageId): WorkflowStage | null {
  switch (stage) {
    case 'SCENARIO':
    case 'METHOD':
      return 'WORLD'
    case 'LAYOUT':
    case 'LEVELS':
    case 'EXCAVATION':
    case 'SHAFTS':
    case 'NETWORK':
    case 'CAPABILITY':
    case 'PRODUCTION':
    case 'SCHEDULE':
    case 'COMMUNICATION':
    case 'SENSORS':
      return stage
    default:
      return null
  }
}

/** a stage whose own artifacts the user can delete from the stepper */
export function resettable(stage: StageId): boolean {
  const target = resetStageFor(stage)
  return target !== null && target !== 'WORLD'
}

// --------------------------------------------------------------------------- //
// stage status glyphs
// --------------------------------------------------------------------------- //

/** ✓ done · ● next · ○ waiting · ✗ failed · ↻ running · – optional / not applicable */
export type StageGlyph = 'DONE' | 'NEXT' | 'WAITING' | 'FAILED' | 'RUNNING' | 'OPTIONAL' | 'NA'

export const GLYPH_TEXT: Record<StageGlyph, string> = {
  DONE: '✓',
  NEXT: '●',
  WAITING: '○',
  FAILED: '✗',
  RUNNING: '↻',
  OPTIONAL: '–',
  NA: '–',
}

export interface StageInput {
  /** a scenario document is loaded */
  scenario: boolean
  /** the scene manifest (null = no world yet) */
  scene: WorldScene | null
  /** declared shaft specs of the scenario (0 → Shafts is an optional stage) */
  shaftSpecCount: number
  /** stages with a running job / pending request */
  running: ReadonlySet<StageId>
}

type ArtifactState = 'ABSENT' | 'SUCCESS' | 'FAILED'

const stateOf = (a: { status: string } | null | undefined): ArtifactState =>
  a == null ? 'ABSENT' : a.status === 'FAILED' ? 'FAILED' : 'SUCCESS'

/** the artifact state each stage OWNS, read from the scene (presentation of
 * backend status only — never computed on the client) */
export function stageArtifactState(stage: StageId, input: StageInput): ArtifactState {
  const { scene } = input
  switch (stage) {
    case 'SCENARIO':
      return input.scenario ? 'SUCCESS' : 'ABSENT'
    case 'METHOD':
      // the method is part of the scenario document; the stage reads done once
      // the world of that document exists
      return scene ? 'SUCCESS' : 'ABSENT'
    case 'LAYOUT': {
      if (!scene) return 'ABSENT'
      if (scene.rampSource.available) return 'SUCCESS'
      return scene.layoutV2?.status === 'NO_FEASIBLE_CANDIDATE' ? 'FAILED' : 'ABSENT'
    }
    case 'LEVELS':
      return stateOf(scene?.levels)
    case 'EXCAVATION': {
      const t = stateOf(scene?.tunnelMesh)
      const d = stateOf(scene?.developmentMesh)
      if (t === 'FAILED' || d === 'FAILED') return 'FAILED'
      return t === 'SUCCESS' && d === 'SUCCESS' ? 'SUCCESS' : 'ABSENT'
    }
    case 'SHAFTS':
      return stateOf(scene?.shafts)
    case 'NETWORK':
      return stateOf(scene?.network)
    case 'CAPABILITY':
      return stateOf(scene?.capabilityGraph)
    case 'PRODUCTION':
      return stateOf(scene?.stopes)
    case 'SCHEDULE':
      return stateOf(scene?.timeline)
    case 'COMMUNICATION':
      return stateOf(scene?.communication)
    case 'SENSORS':
      return stateOf(scene?.sensors)
    case 'ANALYSIS':
    case 'EXPORT':
      return 'ABSENT'
  }
}

/** the stage whose completion a stage waits for (workflow prerequisite — a
 * presentation of the dependency chain, never the enabled condition) */
const PREREQUISITE: Partial<Record<StageId, StageId>> = {
  METHOD: 'SCENARIO',
  LAYOUT: 'METHOD',
  LEVELS: 'LAYOUT',
  EXCAVATION: 'LAYOUT',
  SHAFTS: 'LEVELS',
  NETWORK: 'LEVELS',
  CAPABILITY: 'NETWORK',
  PRODUCTION: 'LEVELS',
  SCHEDULE: 'PRODUCTION',
  COMMUNICATION: 'NETWORK',
  SENSORS: 'NETWORK',
}

/**
 * One glyph per stage. Exactly one stage is NEXT: the first stage (in
 * stepper order) that is neither done, optional nor failed and whose
 * prerequisite is done.
 */
export function stageStatuses(input: StageInput): Record<StageId, StageGlyph> {
  const states = Object.fromEntries(
    STAGE_IDS.map((s) => [s, stageArtifactState(s, input)]),
  ) as Record<StageId, ArtifactState>
  const out = {} as Record<StageId, StageGlyph>
  let nextTaken = false
  for (const stage of STAGE_IDS) {
    if (input.running.has(stage)) {
      out[stage] = 'RUNNING'
      continue
    }
    if (stage === 'ANALYSIS' || stage === 'EXPORT') {
      out[stage] = 'NA'
      continue
    }
    if (stage === 'SHAFTS' && input.shaftSpecCount === 0 && states.SHAFTS === 'ABSENT') {
      out[stage] = 'OPTIONAL'
      continue
    }
    const state = states[stage]
    if (state === 'SUCCESS') {
      out[stage] = 'DONE'
      continue
    }
    if (state === 'FAILED') {
      out[stage] = 'FAILED'
      continue
    }
    const pre = PREREQUISITE[stage]
    const ready = pre === undefined || states[pre] === 'SUCCESS'
    if (ready && !nextTaken) {
      out[stage] = 'NEXT'
      nextTaken = true
    } else {
      out[stage] = 'WAITING'
    }
  }
  return out
}

/** the stage to open when the user clicks a ribbon step: its NEXT / FAILED /
 * RUNNING stage if it has one, else its first stage */
export function entryStageOf(step: WorkflowStep, glyphs: Record<StageId, StageGlyph>): StageId {
  const stages = stagesOfStep(step)
  return (
    stages.find((s) => glyphs[s] === 'NEXT' || glyphs[s] === 'FAILED' || glyphs[s] === 'RUNNING') ??
    stages[0]!
  )
}

/** the next stage after `stage` in stepper order (null at the end) */
export function nextStage(stage: StageId): StageId | null {
  const i = STAGE_IDS.indexOf(stage)
  return i >= 0 && i + 1 < STAGE_IDS.length ? STAGE_IDS[i + 1]! : null
}
