/**
 * Hardening PR-2 H2-SH — the shaft declaration editor's draft helpers (pure,
 * no React). The draft is the explicit `scenario.shafts` section the user
 * edits; the backend plans every shaft from it (rule 182) and the frontend
 * never derives a collar, a station or a drive. The ONLY backend-derived
 * value that enters the draft is the collar suggestion the user asks for
 * (`POST …/design/shafts/suggest-collar`), copied verbatim on their click.
 */
import type { ShaftPlanningConfig, ShaftSpec } from '@/types/api'

/** the backend schema defaults of one new declared shaft (core/models.py
 * `ShaftSpec`): role PRODUCTION, 6 m diameter, default collar, every level,
 * 10 m sump, 40 m collar stand-off, role-default capabilities (`null`) */
export const SHAFT_SPEC_DEFAULTS: Omit<ShaftSpec, 'shaftId'> = {
  role: 'PRODUCTION',
  collar: null,
  diameter: 6,
  levelIds: [],
  bottomSumpDepth: 10,
  collarStandoff: 40,
  capabilities: null,
}

/** `scenario.shafts` as persisted, or the schema default (no shaft) */
export function persistedShafts(
  config: ShaftPlanningConfig | null | undefined,
): ShaftPlanningConfig {
  return config
    ? {
        specs: config.specs.map((s) => ({ ...s, levelIds: [...s.levelIds] })),
        maximumStationAccessLength: config.maximumStationAccessLength,
        minimumShaftSeparation: config.minimumShaftSeparation ?? null,
      }
    : { specs: [], maximumStationAccessLength: 200, minimumShaftSeparation: null }
}

/** the next free `SHAFT-nn` id (ids must be unique and match the backend pattern) */
export function nextShaftId(specs: readonly ShaftSpec[]): string {
  const taken = new Set(specs.map((s) => s.shaftId))
  for (let n = 1; n < 100; n += 1) {
    const id = `SHAFT-${String(n).padStart(2, '0')}`
    if (!taken.has(id)) return id
  }
  return `SHAFT-${String(specs.length + 1)}`
}

export function shaftDraftIsDirty(
  draft: ShaftPlanningConfig,
  persisted: ShaftPlanningConfig,
): boolean {
  return JSON.stringify(draft) !== JSON.stringify(persisted)
}

/** a draft is scoped to ONE scenario revision (`scenarioId:epoch`), exactly
 * like the mining-method draft: another identity restarts at the persisted
 * declaration and never leaks the previous edits */
export interface ShaftDraftState {
  identity: string
  draft: ShaftPlanningConfig
}

export function reconcileShaftDraft(
  state: ShaftDraftState,
  identity: string,
  persisted: ShaftPlanningConfig,
): ShaftDraftState {
  return state.identity === identity ? state : { identity, draft: persisted }
}

/** client-side shape guard mirroring the backend pattern `^[A-Z0-9][A-Z0-9\-]{0,31}$`
 * and the uniqueness rule — a hint before the PUT, never a substitute for the
 * backend's 422 */
export function shaftDraftProblems(draft: ShaftPlanningConfig): string[] {
  const problems: string[] = []
  const ids = new Set<string>()
  for (const s of draft.specs) {
    if (!/^[A-Z0-9][A-Z0-9-]{0,31}$/.test(s.shaftId)) {
      problems.push(`"${s.shaftId}": shaft ids are upper-case letters, digits and dashes`)
    }
    if (ids.has(s.shaftId)) problems.push(`"${s.shaftId}" is declared twice`)
    ids.add(s.shaftId)
    if (!(s.diameter > 0 && s.diameter <= 15))
      problems.push(`${s.shaftId}: diameter must be 0–15 m`)
    if (!(s.bottomSumpDepth > 0)) problems.push(`${s.shaftId}: sump depth must be positive`)
    if (!(s.collarStandoff > 0)) problems.push(`${s.shaftId}: collar stand-off must be positive`)
  }
  if (!(draft.maximumStationAccessLength > 0)) {
    problems.push('maximum station access length must be positive')
  }
  if (draft.minimumShaftSeparation !== null && !(draft.minimumShaftSeparation > 0)) {
    problems.push('minimum shaft separation must be positive or left empty')
  }
  return problems
}
