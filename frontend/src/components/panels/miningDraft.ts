/**
 * Phase 21B/C — the mining-method card's draft helpers (pure, no React).
 * Defaults always come from the backend registry table carried by the scene
 * (`availableMethods[].defaultParameters`); nothing here invents a value.
 */
import type { MiningConfig } from '@/types/api'
import type { MiningMethodType } from '@/types/enums'
import type { MiningMethodSummary } from '@/types/scene'

/**
 * The persisted mining configuration as the card's editable draft. Defaults
 * for a method the scenario does not currently use come from the backend
 * registry table (`availableMethods[].defaultParameters`) — the frontend
 * never invents a parameter value (rule 124).
 */
export function miningDraftFor(
  summary: MiningMethodSummary,
  method: MiningMethodType,
  current?: MiningConfig,
): MiningConfig {
  const base: MiningConfig = {
    method,
    sublevelInterval: current?.sublevelInterval ?? summary.sublevelInterval,
    stopeLength: current?.stopeLength ?? summary.stopeLength,
    minimumPillar: current?.minimumPillar ?? summary.minimumPillar,
  }
  if (method === summary.method && summary.methodParameters) {
    return { ...base, methodParameters: summary.methodParameters }
  }
  const row = summary.availableMethods.find((m) => m.method === method)
  return row?.defaultParameters ? { ...base, methodParameters: row.defaultParameters } : base
}

/** The persisted configuration the card starts from. */
export function persistedMining(summary: MiningMethodSummary): MiningConfig {
  return miningDraftFor(summary, summary.method as MiningMethodType)
}

export function miningDraftIsDirty(draft: MiningConfig, persisted: MiningConfig): boolean {
  return JSON.stringify(draft) !== JSON.stringify(persisted)
}

export const IMPLEMENTATION_LABEL = {
  IMPLEMENTED: 'Implemented',
  UNSUPPORTED_METHOD: 'Not implemented',
} as const

/**
 * The card's draft is scoped to ONE scenario revision (Phase 21B/C review
 * blocker 3). `identity` is `scenarioId:epoch`; when it changes — another
 * scenario was loaded, or the document was replaced by a PUT — the pending
 * edits of the previous identity are discarded and the draft restarts at the
 * new persisted configuration. Same identity → the edits are kept.
 */
export interface MiningDraftState {
  identity: string
  draft: MiningConfig
}

export function reconcileMiningDraft(
  state: MiningDraftState,
  identity: string,
  persisted: MiningConfig,
): MiningDraftState {
  return state.identity === identity ? state : { identity, draft: persisted }
}
