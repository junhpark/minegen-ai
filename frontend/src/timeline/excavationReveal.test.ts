import { describe, expect, it } from 'vitest'
import {
  planIndexGroups,
  readPieceRanges,
  readRevealMeta,
  resolveExcavationReveal,
  revealedIndexCount,
  type PieceRange,
  type RevealMeta,
} from '@/timeline/excavationReveal'
import type {
  DevelopmentTimeline,
  LevelAccessesPayload,
  LevelsPayload,
  SmoothedDeclinePayload,
  TimelinePayload,
} from '@/types/scene'

const META: RevealMeta = {
  indexStride: 6 * 4,
  ringIntervalCount: 4,
  ringChainageFractions: [0, 0.2, 0.5, 0.8, 1],
}

describe('reveal metadata (Phase 20B.2-F)', () => {
  it('reads valid backend extras and rejects malformed ones (fail closed)', () => {
    expect(readRevealMeta(META)).toEqual(META)
    expect(readRevealMeta(null)).toBeNull()
    expect(readRevealMeta({ ...META, indexStride: 0 })).toBeNull()
    expect(readRevealMeta({ ...META, ringChainageFractions: [0, 0.5, 1] })).toBeNull()
    expect(readRevealMeta({ ...META, ringChainageFractions: [0, 0.5, 0.4, 0.8, 1] })).toBeNull()
    expect(readRevealMeta({ ...META, ringChainageFractions: [0.1, 0.2, 0.5, 0.8, 1] })).toBeNull()
  })

  it('reveals the prefix of COMPLETED ring intervals only (rule 31, conservative)', () => {
    expect(revealedIndexCount(META, 0)).toBe(0)
    expect(revealedIndexCount(META, 0.1)).toBe(0)
    expect(revealedIndexCount(META, 0.2)).toBe(24) // first interval complete
    expect(revealedIndexCount(META, 0.49)).toBe(24)
    expect(revealedIndexCount(META, 0.5)).toBe(48)
    expect(revealedIndexCount(META, 0.99)).toBe(72)
    expect(revealedIndexCount(META, 1)).toBe(96)
    expect(revealedIndexCount(META, 7)).toBe(96)
    expect(revealedIndexCount(META, Number.NaN)).toBe(0)
  })
})

function dev(
  edgeId: string,
  edgeType: string,
  artifact: string,
  segmentIndex: number,
  start = 0,
  end = 10,
): DevelopmentTimeline {
  return {
    edgeId,
    edgeType,
    geometryRef: { artifact, segmentIndex },
    taskId: `TASK:${edgeId}`,
    initialState: 'NOT_BUILT',
    transitions: [
      { day: start, state: 'DEVELOPING' },
      { day: end, state: 'ACTIVE' },
    ],
    progressStartDay: start,
    progressEndDay: end,
    pointChainageFractions: [0, 1],
  }
}

const smoothed = {
  owningArtifact: 'layout_v2_selected.json',
  segments: [
    { segmentId: 'S0', levelId: 'L01' },
    { segmentId: 'S1', levelId: 'L02' },
  ],
} as unknown as SmoothedDeclinePayload
const levels = {
  status: 'SUCCESS',
  developments: [
    { id: 'DRIFT:L01:0', kind: 'DRIFT', levelId: 'L01' },
    { id: 'XC:L01:0', kind: 'CROSSCUT', levelId: 'L01' },
  ],
} as unknown as LevelsPayload
const accesses = {
  status: 'SUCCESS',
  accesses: [
    { levelId: 'L01', status: 'OK' },
    { levelId: 'L02', status: 'INFEASIBLE' },
  ],
} as unknown as LevelAccessesPayload

describe('timeline → mesh identity resolution', () => {
  const timeline = {
    status: 'SUCCESS',
    developments: [
      dev('RAMP:0', 'RAMP', 'layout_v2_selected.json', 0, 0, 10),
      dev('RAMP:1', 'RAMP', 'layout_v2_selected.json', 1, 10, 20),
      dev('LA:L01', 'LEVEL_ACCESS', 'level_accesses.json', 0, 20, 30),
      dev('LA:L02', 'LEVEL_ACCESS', 'level_accesses.json', 1, 20, 30), // not OK → unmapped
      dev('DRIFT:e', 'DRIFT', 'levels.json', 0, 30, 40),
      dev('XC:e', 'CROSSCUT', 'levels.json', 1, 40, 50),
      dev('BAD:artifact', 'DRIFT', 'decline_smoothed.json', 0, 0, 1), // wrong owner
      dev('BAD:index', 'DRIFT', 'levels.json', 9, 0, 1), // out of range
      dev('DUP', 'RAMP', 'layout_v2_selected.json', 0, 0, 1), // duplicate identity
    ],
  } as unknown as TimelinePayload

  it('maps every geometryRef through its OWNING artifact and fails closed otherwise', () => {
    const plan = resolveExcavationReveal(timeline, smoothed, levels, accesses, 35)
    expect(plan.unmappedEdgeIds).toEqual(['LA:L02', 'BAD:artifact', 'BAD:index', 'DUP'])
    expect(plan.reveals.map((r) => [r.edgeId, r.target, r.progress])).toEqual([
      ['RAMP:0', { kind: 'RAMP', segmentId: 'S0' }, 1],
      ['RAMP:1', { kind: 'RAMP', segmentId: 'S1' }, 1],
      ['LA:L01', { kind: 'DEVELOPMENT', pieceId: 'LEVEL_ACCESS:L01' }, 1],
      ['DRIFT:e', { kind: 'DEVELOPMENT', pieceId: 'DRIFT:L01:0' }, 0.5],
      ['XC:e', { kind: 'DEVELOPMENT', pieceId: 'XC:L01:0' }, 0],
    ])
  })

  it('uses the exact Phase 10 state boundaries', () => {
    const at = (day: number) =>
      resolveExcavationReveal(timeline, smoothed, levels, accesses, day).reveals.find(
        (r) => r.edgeId === 'DRIFT:e',
      )!.progress
    expect(at(29.999)).toBe(0)
    expect(at(30)).toBe(0)
    expect(at(32.5)).toBe(0.25)
    expect(at(40)).toBe(1)
  })
})

describe('batched draw groups', () => {
  const ranges: PieceRange[] = [
    { pieceId: 'a', developmentId: 'DRIFT:L01', indexOffset: 0, indexCount: 96, meta: META },
    { pieceId: 'b', developmentId: 'DRIFT:L01', indexOffset: 96, indexCount: 96, meta: META },
    { pieceId: 'c', developmentId: 'DRIFT:L02', indexOffset: 192, indexCount: 96, meta: META },
    { pieceId: 'd', developmentId: 'DRIFT:L02', indexOffset: 288, indexCount: 96, meta: META },
  ]
  it('coalesces adjacent complete pieces and cuts a DEVELOPING piece at its last ring', () => {
    const p = new Map([
      ['a', 1],
      ['b', 1],
      ['c', 0.55],
      ['d', 0],
    ])
    expect(planIndexGroups(ranges, p)).toEqual([{ start: 0, count: 192 + 48 }])
  })
  it('keeps disjoint fronts as separate groups and hides unbuilt pieces', () => {
    const p = new Map([
      ['a', 1],
      ['b', 0],
      ['c', 0.2],
      ['d', 1],
    ])
    expect(planIndexGroups(ranges, p)).toEqual([
      { start: 0, count: 96 },
      { start: 192, count: 24 },
      { start: 288, count: 96 },
    ])
  })
  it('never reveals a piece without metadata unless it is complete', () => {
    const r = [{ ...ranges[0]!, meta: null }]
    expect(planIndexGroups(r, new Map([['a', 0.9]]))).toEqual([])
    expect(planIndexGroups(r, new Map([['a', 1]]))).toEqual([{ start: 0, count: 96 }])
  })
  it('reads GLB range extras and rejects a malformed list whole', () => {
    const good = readPieceRanges(
      {
        ranges: [{ pieceId: 'a', developmentId: 'D', levelId: 'L', indexOffset: 0, indexCount: 6 }],
      },
      () => META,
    )
    expect(good).toHaveLength(1)
    expect(good[0]!.meta).toEqual(META)
    expect(readPieceRanges({ ranges: [{ pieceId: 'a' }] }, () => null)).toEqual([])
    expect(readPieceRanges(null, () => null)).toEqual([])
  })
})
