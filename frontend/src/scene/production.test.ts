/**
 * Phase 21B/C — the method-generic production adapter is a pure re-shaping
 * of backend records: kinds come from the payload's own `method`, pillars
 * are never scheduled, and the timeline block that carries the unit states
 * is the Longhole `stopes` list or the generic `production.units` list.
 */
import { describe, expect, it } from 'vitest'
import type {
  CutFillPayload,
  ProductionPayload,
  RoomPillarPayload,
  StopesPayload,
  TimelinePayload,
} from '@/types/scene'
import {
  PRODUCTION_ACTION,
  productionKindOf,
  productionSolids,
  productionSummary,
  productionUnitCount,
  productionUnitStates,
} from './production'

const geometry = { vertices: new Array<number>(24).fill(0), triangleIndices: [0, 1, 2] }
const report = {
  hardInvalidSamples: 0,
  meshClosedSolid: true,
  meshVolumeM3: 1,
  volumeAgreement: true,
  finite: true,
  valid: true,
  failureReason: null,
}

const longhole = {
  status: 'SUCCESS',
  failureReason: null,
  sourceRevision: 'r',
  method: 'LONGHOLE_OPEN_STOPING',
  stopes: [{ id: 'STOPE:A', geometry, report: { valid: true } }],
  metrics: { stopeCount: 1, levelIntervalCount: 1, stationsPerInterval: 1 },
} as unknown as StopesPayload

const cutFill = {
  status: 'SUCCESS',
  failureReason: null,
  sourceRevision: 'r',
  method: 'CUT_AND_FILL',
  lifts: [],
  cuts: [
    { id: 'CUT:1', geometry, report },
    { id: 'CUT:2', geometry, report: { ...report, valid: false } },
  ],
  backfills: [
    { id: 'BACKFILL:1', sourceCutId: 'CUT:1', volumeM3: 1, cemented: true },
    { id: 'BACKFILL:2', sourceCutId: 'CUT:2', volumeM3: 1, cemented: false },
  ],
  ribPillars: [{ id: 'PILLAR:1', geometry, report }],
  metrics: {
    cutCount: 2,
    liftCount: 1,
    backfillCount: 2,
    panelCount: 1,
    blockCount: 1,
    ribPillarCount: 1,
  },
} as unknown as CutFillPayload

const roomPillar = {
  status: 'SUCCESS',
  failureReason: null,
  sourceRevision: 'r',
  method: 'ROOM_AND_PILLAR',
  rooms: [{ id: 'ROOM:R000:C000', extractionUnitIds: ['ROOM:R000:C000:HEADING'] }],
  extractionUnits: [{ id: 'ROOM:R000:C000:HEADING', geometry, report }],
  pillars: [{ id: 'PILLAR:R000:C001', geometry, report }],
  metrics: { roomCount: 1, extractionUnitCount: 1, pillarCount: 1 },
} as unknown as RoomPillarPayload

describe('productionSolids', () => {
  it('maps every payload kind to typed solids in persisted order', () => {
    expect(productionSolids(longhole).map((s) => [s.id, s.kind, s.scheduled])).toEqual([
      ['STOPE:A', 'STOPE', true],
    ])
    expect(productionSolids(cutFill).map((s) => [s.id, s.kind, s.valid])).toEqual([
      ['CUT:1', 'CUT', true],
      ['CUT:2', 'CUT', false],
      ['PILLAR:1', 'PILLAR', true],
    ])
    expect(productionSolids(roomPillar).map((s) => [s.id, s.kind, s.scheduled])).toEqual([
      ['ROOM:R000:C000:HEADING', 'BENCH', true],
      ['PILLAR:R000:C001', 'PILLAR', false],
    ])
  })

  it('never fabricates a solid for a backfill (it IS the cut volume) or a room', () => {
    expect(productionSolids(cutFill).some((s) => s.id.startsWith('BACKFILL'))).toBe(false)
    expect(productionSolids(roomPillar).some((s) => s.id === 'ROOM:R000:C000')).toBe(false)
  })

  it('counts scheduled units only (pillars are retained, never scheduled)', () => {
    expect(productionUnitCount(roomPillar)).toBe(1)
    expect(productionUnitCount(cutFill)).toBe(2)
  })
})

describe('productionKindOf / labels', () => {
  it('reads the backend method discriminator', () => {
    expect(productionKindOf(longhole)).toBe('STOPES')
    expect(productionKindOf(cutFill)).toBe('CUT_FILL')
    expect(productionKindOf(roomPillar)).toBe('ROOM_PILLAR')
    // a reserved method persists the Longhole-SHAPED typed boundary but has
    // NO production kind: it is never presented as stopes
    const reserved = { ...longhole, method: 'SUBLEVEL_CAVING' } as unknown as ProductionPayload
    expect(productionKindOf(reserved)).toBeNull()
  })

  it('names the generic action per kind', () => {
    expect(PRODUCTION_ACTION).toEqual({
      STOPES: 'Generate Stopes',
      CUT_FILL: 'Generate Cut & Fill',
      ROOM_PILLAR: 'Generate Room & Pillar',
    })
  })

  it('summarises from the payload metrics only', () => {
    expect(productionSummary(longhole)).toBe('1 stopes · 1 intervals × 1 stations')
    expect(productionSummary(cutFill)).toBe(
      '2 cuts · 1 panels · 1 blocks · 2 backfills · 1 rib pillars',
    )
    expect(productionSummary(roomPillar)).toBe('1 rooms · 1 extraction units · 1 pillars')
    expect(productionSummary({ ...cutFill, metrics: null })).toBeNull()
  })
})

describe('productionUnitStates', () => {
  const tr = [{ day: 3, state: 'ACTIVE' as const }]
  it('uses the Longhole stopes block when no production block exists', () => {
    const tl = { stopes: [{ stopeId: 'STOPE:A', initialState: 'PLANNED', transitions: tr }] }
    expect(productionUnitStates(tl as unknown as TimelinePayload)).toEqual([
      { unitId: 'STOPE:A', initialState: 'PLANNED', transitions: tr },
    ])
  })
  it('uses the generic production block for the other methods', () => {
    const tl = {
      stopes: [],
      production: {
        method: 'CUT_AND_FILL',
        targetKind: 'CUT',
        units: [{ unitId: 'CUT:1', initialState: 'PLANNED', transitions: tr }],
      },
    }
    expect(productionUnitStates(tl as unknown as TimelinePayload)).toEqual([
      { unitId: 'CUT:1', initialState: 'PLANNED', transitions: tr },
    ])
  })
})
