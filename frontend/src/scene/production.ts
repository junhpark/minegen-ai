/**
 * Phase 21B/C — method-generic PRESENTATION adapter over the ACTIVE production
 * payload (`scene.stopes`, one artifact typed by `method`) and the timeline's
 * production block.
 *
 * Pure and geometry-free: it only re-shapes backend records (ids, kinds,
 * vertices + indices, validity, state machines) so one layer can render
 * stopes, cuts, benches and pillars alike. No engineering quantity is
 * computed here (rule 80 / 124); the discriminator is the backend's own
 * `method` field, never a guess from the shape of the data.
 */
import type {
  ObjectStateId,
  ProductionKind,
  ProductionPayload,
  SolidGeometry,
  StateTransition,
  TimelinePayload,
} from '@/types/scene'

export type ProductionSolidKind = 'STOPE' | 'CUT' | 'BENCH' | 'PILLAR'

export interface ProductionSolid {
  /** the backend record id (also the timeline unit id for scheduled solids) */
  id: string
  kind: ProductionSolidKind
  geometry: SolidGeometry
  /** the backend hard-QA verdict of this solid */
  valid: boolean
  /** false for retained pillars — they never carry a temporal state */
  scheduled: boolean
}

export interface ProductionUnitState {
  unitId: string
  initialState: ObjectStateId
  transitions: StateTransition[]
}

export const PRODUCTION_KIND_OF_METHOD: Record<string, ProductionKind> = {
  LONGHOLE_OPEN_STOPING: 'STOPES',
  CUT_AND_FILL: 'CUT_FILL',
  ROOM_AND_PILLAR: 'ROOM_PILLAR',
}

/** The production kind of a payload — from its own `method` discriminator.
 * A reserved method persists the Longhole-SHAPED typed FAILED boundary but
 * has NO production kind (null): it is never presented as stopes. */
export function productionKindOf(payload: ProductionPayload): ProductionKind | null {
  return PRODUCTION_KIND_OF_METHOD[payload.method] ?? null
}

/** Every solid of the ACTIVE production payload, in persisted order. */
export function productionSolids(payload: ProductionPayload): ProductionSolid[] {
  if (payload.method === 'CUT_AND_FILL') {
    return payload.cuts.map((c) => ({
      id: c.id,
      kind: 'CUT',
      geometry: c.geometry,
      valid: c.report.valid,
      scheduled: true,
    }))
  }
  if (payload.method === 'ROOM_AND_PILLAR') {
    return [
      ...payload.extractionUnits.map((u): ProductionSolid => ({
        id: u.id,
        kind: 'BENCH',
        geometry: u.geometry,
        valid: u.report.valid,
        scheduled: true,
      })),
      ...payload.pillars.map((p): ProductionSolid => ({
        id: p.id,
        kind: 'PILLAR',
        geometry: p.geometry,
        valid: p.report.valid,
        scheduled: false,
      })),
    ]
  }
  return payload.stopes.map((s) => ({
    id: s.id,
    kind: 'STOPE',
    geometry: s.geometry,
    valid: s.report.valid,
    scheduled: true,
  }))
}

/** The temporal state machines the timeline carries for production units:
 * the Longhole `stopes` block or the generic `production.units` block. */
export function productionUnitStates(timeline: TimelinePayload): ProductionUnitState[] {
  if (timeline.production && timeline.production.units.length > 0) {
    return timeline.production.units.map((u) => ({
      unitId: u.unitId,
      initialState: u.initialState,
      transitions: u.transitions,
    }))
  }
  return timeline.stopes.map((s) => ({
    unitId: s.stopeId,
    initialState: s.initialState,
    transitions: s.transitions,
  }))
}

/** User-facing noun of the production units of a kind. */
export const PRODUCTION_UNIT_NOUN: Record<ProductionKind, string> = {
  STOPES: 'stopes',
  CUT_FILL: 'cuts',
  ROOM_PILLAR: 'extraction units',
}

/** The generation action label per production kind (§ generic action). */
export const PRODUCTION_ACTION: Record<ProductionKind, string> = {
  STOPES: 'Generate Stopes',
  CUT_FILL: 'Generate Cut & Fill',
  ROOM_PILLAR: 'Generate Room & Pillar',
}

/** One-line summary of a SUCCESS production payload from its own metrics. */
export function productionSummary(payload: ProductionPayload): string | null {
  if (payload.method === 'CUT_AND_FILL') {
    const m = payload.metrics
    return m ? `${m.cutCount} cuts · ${m.liftCount} lifts · ${m.backfillCount} backfills` : null
  }
  if (payload.method === 'ROOM_AND_PILLAR') {
    const m = payload.metrics
    return m
      ? `${m.roomCount} rooms · ${m.extractionUnitCount} extraction units · ${m.pillarCount} pillars`
      : null
  }
  const m = payload.metrics
  return m
    ? `${m.stopeCount} stopes · ${m.levelIntervalCount} intervals × ${m.stationsPerInterval} stations`
    : null
}

/** Count of scheduled production units in a payload (pillars excluded). */
export function productionUnitCount(payload: ProductionPayload): number {
  return productionSolids(payload).filter((s) => s.scheduled).length
}
