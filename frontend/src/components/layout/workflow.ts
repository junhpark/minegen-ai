import { developmentMeshScope } from '@/components/panels/developmentMeshScope'
import type { AnalysisTab, DesignTab, SystemsTab } from '@/components/panels/workflowTabs'
import type { AppMode } from '@/types/enums'
import type { WorkflowStage, WorldScene } from '@/types/scene'
import { STAGE_IDS, type StageId, type WorkflowStep } from '@/types/workflow'

/**
 * Hardening H1 §4.1–4.3 — the guided workflow model (pure).
 *
 *   1 Setup · 2 Design · 3 Network · 4 Mining · 5 Systems · 6 Analysis · 7 Export
 *   [Scenario ✓][Method ✓][Access ✓][Layout ●][Levels ○][Excavation ○][Shafts –] …
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
  { id: 'SETUP', index: 1, label: 'Setup', stages: ['SCENARIO', 'METHOD', 'ACCESS'] },
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
  ACCESS: 'Access',
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
    case 'ACCESS':
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

/** ✓ done · ● next · ○ waiting · ✗ failed · ↻ running · – optional */
export type StageGlyph = 'DONE' | 'NEXT' | 'WAITING' | 'FAILED' | 'RUNNING' | 'OPTIONAL'

export const GLYPH_TEXT: Record<StageGlyph, string> = {
  DONE: '✓',
  NEXT: '●',
  WAITING: '○',
  FAILED: '✗',
  RUNNING: '↻',
  OPTIONAL: '–',
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
  /**
   * Review round 2 S2 — the two stages that own no artifact (Analysis is a
   * read-only projection, Export a download) are completed by the VIEWER:
   * Analysis once it was opened, Export once a package was downloaded.
   * Viewer-local, cleared on every scenario transition, never persisted.
   */
  completed: ReadonlySet<StageId>
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
    case 'ACCESS':
      // the method and the access strategy (PR #54 review B3: the shaft
      // declaration) are part of the scenario document; the stage reads done
      // once the world of that document exists — "Ramp only" is a decision too
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
      // review S1: an ACCESS-ONLY development sweep (no level development
      // geometry — levels failed or absent) is not a completed Excavation
      // for the stepper; the results column still reports it as ACCESS-ONLY
      const accessOnly = developmentMeshScope(
        scene?.developmentMesh ?? null,
        scene?.levels ?? null,
      ).accessOnly
      return t === 'SUCCESS' && d === 'SUCCESS' && !accessOnly ? 'SUCCESS' : 'ABSENT'
    }
    case 'SHAFTS': {
      // PR #54 review B3: the Shafts stage PLANS the declared shafts and sweeps
      // their mesh; it is done only when both exist (either failure is the
      // stage's failure). The declaration itself lives in Setup › Access.
      const plan = stateOf(scene?.shafts)
      const mesh = stateOf(scene?.shaftMesh)
      if (plan === 'FAILED' || mesh === 'FAILED') return 'FAILED'
      return plan === 'SUCCESS' && mesh === 'SUCCESS' ? 'SUCCESS' : 'ABSENT'
    }
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
      // viewer-completed stages (S2): no artifact, so no backend status
      return input.completed.has(stage) ? 'SUCCESS' : 'ABSENT'
  }
}

/** the stages whose completion is viewer-local (S2) — their DONE counts only
 * while their prerequisite chain is done, since the mine they were completed
 * on may have been reset since */
const VIEWER_COMPLETED: ReadonlySet<StageId> = new Set<StageId>(['ANALYSIS', 'EXPORT'])

/**
 * The stage whose completion a stage waits for (workflow prerequisite — a
 * presentation of the dependency chain, never the enabled condition).
 * Review round 2: Excavation waits for Levels (S1 — a failed Levels stage is
 * the focus, not an Excavation it cannot complete); Analysis follows the
 * last Systems stage and Export follows Analysis (S2 — the guided flow has
 * no dead end: once the mine is built, Analysis is next, then Export).
 */
const PREREQUISITE: Partial<Record<StageId, StageId>> = {
  METHOD: 'SCENARIO',
  ACCESS: 'METHOD',
  LAYOUT: 'ACCESS',
  LEVELS: 'LAYOUT',
  EXCAVATION: 'LEVELS',
  SHAFTS: 'LEVELS',
  NETWORK: 'LEVELS',
  CAPABILITY: 'NETWORK',
  PRODUCTION: 'LEVELS',
  SCHEDULE: 'PRODUCTION',
  COMMUNICATION: 'NETWORK',
  SENSORS: 'NETWORK',
  ANALYSIS: 'SENSORS',
  EXPORT: 'ANALYSIS',
}

/**
 * One glyph per stage. At most one stage is NEXT: the first stage (in
 * stepper order) that is neither done, optional nor failed and whose
 * prerequisite is done. When a FAILED stage blocks the chain no stage is
 * NEXT — the failed stage is the focus (`entryStageOf` opens it).
 */
export function stageStatuses(input: StageInput): Record<StageId, StageGlyph> {
  const states = Object.fromEntries(
    STAGE_IDS.map((s) => [s, stageArtifactState(s, input)]),
  ) as Record<StageId, ArtifactState>
  const done = (stage: StageId): boolean => {
    if (states[stage] !== 'SUCCESS') return false
    if (!VIEWER_COMPLETED.has(stage)) return true
    const pre = PREREQUISITE[stage]
    return pre === undefined || done(pre)
  }
  const ready = (stage: StageId): boolean => {
    const pre = PREREQUISITE[stage]
    return pre === undefined || done(pre)
  }
  const out = {} as Record<StageId, StageGlyph>
  let nextTaken = false
  for (const stage of STAGE_IDS) {
    if (input.running.has(stage)) {
      out[stage] = 'RUNNING'
      continue
    }
    if (stage === 'SHAFTS' && input.shaftSpecCount === 0 && states.SHAFTS === 'ABSENT') {
      out[stage] = 'OPTIONAL'
      continue
    }
    if (done(stage)) {
      out[stage] = 'DONE'
      continue
    }
    if (states[stage] === 'FAILED') {
      out[stage] = 'FAILED'
      continue
    }
    if (ready(stage) && !nextTaken) {
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
