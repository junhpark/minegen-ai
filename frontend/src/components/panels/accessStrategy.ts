/**
 * PR #54 review B3 — Setup › Access helpers (pure, no React): the access
 * strategy is READ from the declared `scenario.shafts.specs` and a strategy
 * switch edits that declaration only.
 */
import type { ShaftPlanningConfig } from '@/types/api'
import { SHAFT_SPEC_DEFAULTS, nextShaftId } from './shaftDraft'

/** the two declared access strategies of the Setup › Access stage */
export type AccessStrategy = 'RAMP_ONLY' | 'RAMP_AND_SHAFT'

export function accessStrategyOf(config: ShaftPlanningConfig): AccessStrategy {
  return config.specs.length > 0 ? 'RAMP_AND_SHAFT' : 'RAMP_ONLY'
}

/** the draft under the chosen strategy: Ramp only clears the specs, Ramp +
 * Shaft keeps the declared specs or seeds ONE schema-default shaft */
export function withAccessStrategy(
  draft: ShaftPlanningConfig,
  strategy: AccessStrategy,
): ShaftPlanningConfig {
  if (strategy === 'RAMP_ONLY') return { ...draft, specs: [] }
  if (draft.specs.length > 0) return draft
  return { ...draft, specs: [{ shaftId: nextShaftId([]), ...SHAFT_SPEC_DEFAULTS }] }
}
