/**
 * Hardening H1 §4.1–4.3 — the guided workflow vocabulary.
 *
 * A STEP is a ribbon entry (1 Setup … 7 Export); a STAGE is one chip of the
 * stepper and one unit of "Reset from here". Both are frontend-local viewer
 * state: never persisted to a scenario, never a backend concept. The backend
 * stage ids of the reset endpoint (`WorkflowStage`, `types/scene.ts`) are a
 * separate vocabulary and are mapped explicitly in `components/layout/workflow.ts`.
 */
export const WORKFLOW_STEP_IDS = [
  'SETUP',
  'DESIGN',
  'NETWORK',
  'MINING',
  'SYSTEMS',
  'ANALYSIS',
  'EXPORT',
] as const
export type WorkflowStep = (typeof WORKFLOW_STEP_IDS)[number]

export const STAGE_IDS = [
  'SCENARIO',
  'METHOD',
  'ACCESS',
  'LAYOUT',
  'LEVELS',
  'EXCAVATION',
  'SHAFTS',
  'NETWORK',
  'CAPABILITY',
  'PRODUCTION',
  'SCHEDULE',
  'COMMUNICATION',
  'SENSORS',
  'ANALYSIS',
  'EXPORT',
] as const
export type StageId = (typeof STAGE_IDS)[number]

/** the three VIEW modes of the viewport — never workflow steps */
export type ViewMode = '3D' | '4D' | 'WALK'
