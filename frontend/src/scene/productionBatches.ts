/**
 * Phase 21B/C review item 5 — production render BATCHING (presentation only).
 *
 * The default Room & Pillar scenario carries ≈ 7,300 production solids; one
 * mesh + material per solid is thousands of draw calls. These pure helpers
 * group the ACTIVE production solids into a handful of render batches — one
 * per (kind, validity) for the static layer, one per visual state (or
 * "retained") for the 4D layer — so each batch becomes ONE merged
 * BufferGeometry and ONE material. Nothing here computes or changes
 * geometry: a batch is a list of persisted solids whose triangles are
 * concatenated verbatim (rule 80 / 124). Backend ids are kept on the batch
 * for inspection; instance order inside a batch is the persisted order.
 */
import type { ProductionSolid, ProductionSolidKind, ProductionUnitState } from './production'
import { stateAt } from '@/timeline/evaluate'
import type { ObjectStateId } from '@/types/scene'

export interface StaticBatch {
  key: string
  kind: ProductionSolidKind
  valid: boolean
  solids: ProductionSolid[]
}

/** One batch per (kind, validity) in first-seen order — at most 2 × kinds. */
export function staticBatches(solids: ProductionSolid[]): StaticBatch[] {
  const batches = new Map<string, StaticBatch>()
  for (const s of solids) {
    const key = `${s.kind}:${s.valid ? 'valid' : 'invalid'}`
    let b = batches.get(key)
    if (!b) {
      b = { key, kind: s.kind, valid: s.valid, solids: [] }
      batches.set(key, b)
    }
    b.solids.push(s)
  }
  return [...batches.values()]
}

export type TimelineBatchState = ObjectStateId | 'RETAINED'

export interface TimelineBatch {
  key: TimelineBatchState
  state: TimelineBatchState
  solids: ProductionSolid[]
}

/**
 * One batch per temporal state at `day` (rule 84 exact-boundary semantics
 * through `stateAt`), plus one RETAINED batch for solids that carry no
 * state (pillars). A scheduled solid without a unit state machine is
 * DROPPED, never guessed (rule 117 analogue) — `unmapped` reports them.
 */
export function timelineBatches(
  solids: ProductionSolid[],
  unitById: Map<string, ProductionUnitState>,
  day: number,
): { batches: TimelineBatch[]; unmapped: string[] } {
  const batches = new Map<TimelineBatchState, TimelineBatch>()
  const unmapped: string[] = []
  const push = (state: TimelineBatchState, s: ProductionSolid) => {
    let b = batches.get(state)
    if (!b) {
      b = { key: state, state, solids: [] }
      batches.set(state, b)
    }
    b.solids.push(s)
  }
  for (const s of solids) {
    if (!s.scheduled) {
      push('RETAINED', s)
      continue
    }
    const unit = unitById.get(s.id)
    if (!unit) {
      unmapped.push(s.id)
      continue
    }
    push(stateAt(unit.initialState, unit.transitions, day), s)
  }
  return { batches: [...batches.values()], unmapped }
}
