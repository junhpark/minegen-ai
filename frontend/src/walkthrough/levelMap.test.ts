import { describe, expect, it } from 'vitest'
import type { WorldScene } from '@/types/scene'
import {
  buildLadderModel,
  buildLevelMapModel,
  collectLevels,
  DEFAULT_LEVEL_HALF_BAND_M,
  levelHalfBand,
  MIN_MAP_HALF_EXTENT_M,
  pickLevel,
  portalRl,
  projectToMap,
} from './levelMap'

const line = (...pts: number[][]) => pts.flat()

/** two levels 25 m apart under a north-running 10 % ramp */
function scene(over: Partial<WorldScene> = {}): WorldScene {
  return {
    smoothedDecline: {
      status: 'SUCCESS',
      segments: [
        {
          segmentId: 'RAMP_JUNCTION:L01',
          levelId: 'L01',
          rampJunction: { levelId: 'L01', chainage: 250 },
          effectiveCenterline: {
            points: line([0, 0, 300], [0, 100, 290], [0, 200, 280], [0, 250, 275]),
            pointCount: 4,
          },
        },
        {
          segmentId: 'RAMP_JUNCTION:L02',
          levelId: 'L02',
          rampJunction: { levelId: 'L02', chainage: 500 },
          effectiveCenterline: {
            points: line([0, 250, 275], [0, 400, 260], [0, 500, 250]),
            pointCount: 3,
          },
        },
      ],
    },
    levelAccesses: {
      status: 'SUCCESS',
      accesses: [
        {
          levelId: 'L01',
          elevation: 275,
          status: 'OK',
          rampJunctionChainage: 250,
          centerline: { points: line([0, 250, 275], [20, 262, 275]), pointCount: 2 },
        },
        {
          levelId: 'L02',
          elevation: 250,
          status: 'OK',
          rampJunctionChainage: 500,
          centerline: { points: line([0, 500, 250], [20, 512, 250]), pointCount: 2 },
        },
      ],
    },
    levels: {
      status: 'SUCCESS',
      developments: [
        {
          id: 'DRIFT:L01:01',
          kind: 'DRIFT',
          levelId: 'L01',
          centerline: { points: line([20, 200, 275], [20, 262, 275]) },
        },
        {
          id: 'DRIFT:L01:02',
          kind: 'DRIFT',
          levelId: 'L01',
          centerline: { points: line([20, 262, 275], [20, 330, 275]) },
        },
        {
          id: 'CROSSCUT:L01:S+01',
          kind: 'CROSSCUT',
          levelId: 'L01',
          stationIndex: 1,
          centerline: { points: line([20, 300, 275], [45, 300, 275]) },
        },
        {
          id: 'DRIFT:L02:01',
          kind: 'DRIFT',
          levelId: 'L02',
          centerline: { points: line([20, 450, 250], [20, 560, 250]) },
        },
      ],
    },
    network: {
      status: 'SUCCESS',
      nodes: [
        { id: 'PORTAL', type: 'PORTAL', position: [0, 0, 300] },
        { id: 'RAMP_JUNCTION:L01', type: 'RAMP_JUNCTION', position: [0, 250, 275], levelId: 'L01' },
        { id: 'LEVEL_ENTRY:L01', type: 'LEVEL_ENTRY', position: [20, 262, 275], levelId: 'L01' },
        {
          id: 'STOPE_ACCESS:L01:S+01',
          type: 'STOPE_ACCESS',
          position: [45, 300, 275],
          levelId: 'L01',
        },
        { id: 'LEVEL_ENTRY:L02', type: 'LEVEL_ENTRY', position: [20, 512, 250], levelId: 'L02' },
      ],
      edges: [],
    },
    ...over,
  } as unknown as WorldScene
}

describe('level collection and pick (PR-4 W3)', () => {
  it('reads levels from the level accesses, highest first, and derives the half band', () => {
    const levels = collectLevels(scene())
    expect(levels).toEqual([
      { levelId: 'L01', elevation: 275 },
      { levelId: 'L02', elevation: 250 },
    ])
    expect(levelHalfBand(levels)).toBe(12.5)
    expect(levelHalfBand([levels[0]!])).toBe(DEFAULT_LEVEL_HALF_BAND_M)
  })

  it('falls back to the catalogue, then the ramp references, then legacy segment ends; never invents', () => {
    const noAccess = scene({
      levelAccesses: null,
      layoutV2: { requiredLevels: [{ levelId: 'L07', elevation: 100 }] },
    } as never)
    expect(collectLevels(noAccess)).toEqual([{ levelId: 'L07', elevation: 100 }])
    const legacy = scene({ levelAccesses: null, layoutV2: null })
    expect(collectLevels(legacy).map((l) => l.levelId)).toEqual(['L01', 'L02'])
    expect(collectLevels(null)).toEqual([])
  })

  it('picks the nearest level inside the half band, none between levels', () => {
    const levels = collectLevels(scene())
    expect(pickLevel(276, levels, 12.5)?.levelId).toBe('L01')
    expect(pickLevel(262.5, levels, 12.5)?.levelId).toBe('L01') // tie → first (nearest equal)
    expect(pickLevel(262.4, levels, 12.5)?.levelId).toBe('L02')
    expect(pickLevel(295, levels, 12.5)).toBeNull()
  })
})

describe('level map model (PR-4 W3)', () => {
  const sc = scene()
  const levels = collectLevels(sc)

  it('a level shows its drifts, crosscuts, access, the ramp band and its nodes, fitted to the level', () => {
    const m = buildLevelMapModel({
      scene: sc,
      level: levels[0]!,
      rl: 276,
      halfBand: 12.5,
      activeRampSegmentIds: null,
      activePieceIds: null,
    })
    expect(m.level?.levelId).toBe('L01')
    expect(m.polylines.map((p) => p.id).sort()).toEqual(
      ['ACCESS:L01', 'CROSSCUT:L01:S+01', 'DRIFT:L01:01', 'DRIFT:L01:02', 'RAMP:0'].sort(),
    )
    // the ramp band keeps only samples within ± 12.5 m of RL 275
    const ramp = m.polylines.find((p) => p.id === 'RAMP:0')!
    expect(ramp.xy).toEqual([0, 200, 0, 250])
    expect(m.markers.map((k) => k.kind).sort()).toEqual(['ENTRY', 'STOPE_ACCESS', 'TURNOUT'])
    // square bounds containing every drawn point, padded
    for (const p of m.polylines) {
      for (let i = 0; i + 1 < p.xy.length; i += 2) {
        expect(p.xy[i]!).toBeGreaterThanOrEqual(m.bounds.minX)
        expect(p.xy[i]!).toBeLessThanOrEqual(m.bounds.maxX)
        expect(p.xy[i + 1]!).toBeGreaterThanOrEqual(m.bounds.minY)
        expect(p.xy[i + 1]!).toBeLessThanOrEqual(m.bounds.maxY)
      }
    }
    expect(m.bounds.maxX - m.bounds.minX).toBeCloseTo(m.bounds.maxY - m.bounds.minY, 9)
    // a ramp-only view between levels: the band around the RL plus the portal when in band
    const band = buildLevelMapModel({
      scene: sc,
      level: null,
      rl: 295,
      halfBand: 12.5,
      activeRampSegmentIds: null,
      activePieceIds: null,
    })
    expect(band.level).toBeNull()
    expect(band.polylines.map((p) => p.kind)).toEqual(['RAMP'])
    expect(band.markers.map((k) => k.kind)).toEqual(['PORTAL'])
    expect(band.bounds.maxX - band.bounds.minX).toBeGreaterThanOrEqual(2 * MIN_MAP_HALF_EXTENT_M)
  })

  it('temporal: only the ACTIVE ramp prefix and ACTIVE pieces are drawn; their nodes follow', () => {
    const m = buildLevelMapModel({
      scene: sc,
      level: levels[0]!,
      rl: 276,
      halfBand: 12.5,
      activeRampSegmentIds: ['RAMP_JUNCTION:L01'],
      activePieceIds: new Set(['LEVEL_ACCESS:L01', 'DRIFT:L01:01']),
    })
    expect(m.polylines.map((p) => p.id).sort()).toEqual(['ACCESS:L01', 'DRIFT:L01:01', 'RAMP:0'])
    expect(m.polylines.find((p) => p.id === 'RAMP:0')!.xy).toEqual([0, 200, 0, 250])
    // the stope access of the not-yet-active crosscut is not shown
    expect(m.markers.map((k) => k.kind).sort()).toEqual(['ENTRY', 'TURNOUT'])
    const empty = buildLevelMapModel({
      scene: sc,
      level: levels[0]!,
      rl: 276,
      halfBand: 12.5,
      activeRampSegmentIds: ['RAMP_JUNCTION:L01'],
      activePieceIds: new Set(),
    })
    expect(empty.polylines.map((p) => p.kind)).toEqual(['RAMP'])
    expect(empty.markers.map((k) => k.kind)).toEqual(['TURNOUT'])
  })

  it('projection is north-up inside the fitted bounds; the ladder places the RL among the levels', () => {
    const b = { minX: 0, minY: 0, maxX: 100, maxY: 100 }
    expect(projectToMap(b, 0, 100)).toEqual([0, 0]) // north-west corner at the top-left
    expect(projectToMap(b, 100, 0)).toEqual([1, 1])
    expect(portalRl(sc.smoothedDecline)).toBe(300)
    const ladder = buildLadderModel(levels, 262.5, 300)!
    expect(ladder.zTop).toBe(300)
    expect(ladder.zBottom).toBe(250)
    expect(ladder.ticks.map((t) => [t.levelId, t.t])).toEqual([
      ['L01', 0.5],
      ['L02', 1],
    ])
    expect(ladder.avatarT).toBeCloseTo(0.75)
    expect(buildLadderModel([], 0, null)).toBeNull()
  })
})
