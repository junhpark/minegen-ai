/**
 * PR-4 W1a: temporal development traversal plan. A synthetic layout-v2 mine:
 * a north-running ramp with one turnout at y = 40 (RAMP_JUNCTION:L01), an
 * access running east to the LEVEL_ENTRY at (30, 56, −4), a drift along y
 * through the entry split into a −y piece and a +y piece, and one crosscut
 * east from the +y piece's end station. The network, levels, level accesses
 * and timeline are built consistently with the backend id conventions.
 */
import { describe, expect, it } from 'vitest'
import type {
  LevelAccessesPayload,
  LevelsPayload,
  NetworkPayload,
  SmoothedDeclinePayload,
  TimelinePayload,
} from '@/types/scene'
import {
  PLUG_HALF_DEPTH_M,
  PLUG_MARGIN_M,
  resolveTemporalDevelopmentPlan,
  temporalActiveDevelopment,
} from './temporalDevelopmentPlan'

const Z = -4
const ENTRY: [number, number, number] = [30, 56, Z]
const STATION: [number, number, number] = [30, 96, Z]
const line = (...pts: number[][]) => pts.flat()

const SMOOTHED = {
  status: 'SUCCESS',
  owningArtifact: 'layout_v2_selected.json',
  segments: [
    {
      segmentId: 'RAMP_JUNCTION:L01',
      levelId: 'L01',
      rampJunction: { levelId: 'L01', chainage: 40 },
      effectiveCenterline: { points: line([0, 0, 0], [0, 40, Z]), pointCount: 2 },
      boundaryTangents: { start: [0, 1, -0.1], end: [0, 1, -0.1] },
    },
    {
      segmentId: 'RAMP_END',
      levelId: null,
      terminalKind: 'RAMP_END',
      effectiveCenterline: { points: line([0, 40, Z], [0, 120, Z - 8]), pointCount: 2 },
      boundaryTangents: { start: [0, 1, -0.1], end: [0, 1, -0.1] },
    },
  ],
} as unknown as SmoothedDeclinePayload

const ACCESS_PTS = line([0, 40, Z], [6, 44, Z], [16, 50, Z], ENTRY)
const ACCESSES = {
  status: 'SUCCESS',
  accesses: [
    {
      levelId: 'L01',
      status: 'OK',
      rampJunction: [0, 40, Z],
      levelEntry: ENTRY,
      centerline: { points: ACCESS_PTS, pointCount: 4 },
    },
  ],
} as unknown as LevelAccessesPayload

const LEVELS = {
  status: 'SUCCESS',
  developments: [
    {
      id: 'DRIFT:L01:01',
      kind: 'DRIFT',
      levelId: 'L01',
      centerline: { points: line([30, 16, Z], ENTRY) },
    },
    {
      id: 'DRIFT:L01:02',
      kind: 'DRIFT',
      levelId: 'L01',
      centerline: { points: line(ENTRY, STATION) },
    },
    {
      id: 'CROSSCUT:L01:S+01',
      kind: 'CROSSCUT',
      levelId: 'L01',
      stationIndex: 1,
      centerline: { points: line(STATION, [50, 96, Z]) },
    },
  ],
} as unknown as LevelsPayload

const XS = { width: 5, height: 5, analyticArea: 22 }
const NETWORK = {
  status: 'SUCCESS',
  nodes: [
    { id: 'PORTAL', type: 'PORTAL', position: [0, 0, 0] },
    { id: 'RAMP_JUNCTION:L01', type: 'RAMP_JUNCTION', position: [0, 40, Z], levelId: 'L01' },
    { id: 'RAMP_END', type: 'RAMP_END', position: [0, 120, Z - 8] },
    { id: 'LEVEL_ENTRY:L01', type: 'LEVEL_ENTRY', position: ENTRY, levelId: 'L01' },
    { id: 'JUNCTION:L01:U-40', type: 'JUNCTION', position: [30, 16, Z], levelId: 'L01' },
    { id: 'JUNCTION:L01:S+01', type: 'JUNCTION', position: STATION, levelId: 'L01' },
    { id: 'STOPE_ACCESS:L01:S+01', type: 'STOPE_ACCESS', position: [50, 96, Z], levelId: 'L01' },
  ],
  edges: [
    {
      id: 'RAMP:RAMP_JUNCTION:L01',
      type: 'RAMP',
      fromNode: 'PORTAL',
      toNode: 'RAMP_JUNCTION:L01',
      crossSection: XS,
    },
    {
      id: 'RAMP:RAMP_END',
      type: 'RAMP',
      fromNode: 'RAMP_JUNCTION:L01',
      toNode: 'RAMP_END',
      crossSection: XS,
    },
    {
      id: 'LEVEL_ACCESS:L01',
      type: 'LEVEL_ACCESS',
      fromNode: 'RAMP_JUNCTION:L01',
      toNode: 'LEVEL_ENTRY:L01',
      crossSection: XS,
    },
    {
      id: 'DRIFT:L01:01',
      type: 'DRIFT',
      fromNode: 'JUNCTION:L01:U-40',
      toNode: 'LEVEL_ENTRY:L01',
      crossSection: XS,
    },
    {
      id: 'DRIFT:L01:02',
      type: 'DRIFT',
      fromNode: 'LEVEL_ENTRY:L01',
      toNode: 'JUNCTION:L01:S+01',
      crossSection: XS,
    },
    {
      id: 'CROSSCUT:L01:S+01',
      type: 'CROSSCUT',
      fromNode: 'JUNCTION:L01:S+01',
      toNode: 'STOPE_ACCESS:L01:S+01',
      crossSection: XS,
    },
  ],
} as unknown as NetworkPayload

/** ACTIVE days: ramp 100 / 200, access 300, drift −y 400, drift +y 500, crosscut 600 */
function timeline(overrides: Record<string, number> = {}): TimelinePayload {
  const dev = (edgeId: string, edgeType: string, artifact: string, i: number, end: number) => ({
    edgeId,
    edgeType,
    geometryRef: { artifact, segmentIndex: i },
    taskId: `T:${edgeId}`,
    initialState: 'NOT_BUILT',
    transitions: [
      { day: end - 50, state: 'DEVELOPING' },
      { day: overrides[edgeId] ?? end, state: 'ACTIVE' },
    ],
    progressStartDay: end - 50,
    progressEndDay: overrides[edgeId] ?? end,
    pointChainageFractions: [],
  })
  return {
    status: 'SUCCESS',
    developments: [
      dev('RAMP:RAMP_JUNCTION:L01', 'RAMP', 'layout_v2_selected.json', 0, 100),
      dev('RAMP:RAMP_END', 'RAMP', 'layout_v2_selected.json', 1, 200),
      dev('LEVEL_ACCESS:L01', 'LEVEL_ACCESS', 'level_accesses.json', 0, 300),
      dev('DRIFT:L01:01', 'DRIFT', 'levels.json', 0, 400),
      dev('DRIFT:L01:02', 'DRIFT', 'levels.json', 1, 500),
      dev('CROSSCUT:L01:S+01', 'CROSSCUT', 'levels.json', 2, 600),
    ],
  } as unknown as TimelinePayload
}

const PIECES = [
  { pieceId: 'LEVEL_ACCESS:L01', kind: 'LEVEL_ACCESS' as const },
  { pieceId: 'DRIFT:L01:01', kind: 'DRIFT' as const },
  { pieceId: 'DRIFT:L01:02', kind: 'DRIFT' as const },
  { pieceId: 'CROSSCUT:L01:S+01', kind: 'CROSSCUT' as const },
]
const RAMP_ALL = ['RAMP_JUNCTION:L01', 'RAMP_END']

function plan(day: number, ramp = RAMP_ALL, tl = timeline()) {
  return resolveTemporalDevelopmentPlan(tl, LEVELS, ACCESSES, NETWORK, SMOOTHED, PIECES, day, ramp)
}

describe('temporal development plan (PR-4 W1a)', () => {
  it('before any development is ACTIVE: nothing collides, nothing is open, no plug', () => {
    const p = plan(250)
    expect(p.status).toBe('VALID')
    expect(p.activePieceIds).toEqual([])
    expect(p.openAccessLevelIds).toEqual([])
    expect(p.plugs).toEqual([])
  })

  it('access ACTIVE, drifts not: the ramp aperture opens and the access end is plugged', () => {
    const p = plan(350)
    expect(p.activePieceIds).toEqual(['LEVEL_ACCESS:L01'])
    expect(p.activeKinds).toEqual(['LEVEL_ACCESS'])
    expect(p.openAccessLevelIds).toEqual(['L01'])
    expect(p.plugs.map((x) => x.kind)).toEqual(['ACCESS_END'])
    const plug = p.plugs[0]!
    expect(plug.nodeId).toBe('LEVEL_ENTRY:L01')
    expect(plug.edgeId).toBe('LEVEL_ACCESS:L01')
    // flush with the entry, pointing from the access into the drift, lifted by h/2
    const dir = [ENTRY[0] - 16, ENTRY[1] - 50, 0]
    const len = Math.hypot(dir[0]!, dir[1]!)
    expect(plug.forwardMine[0]).toBeCloseTo(dir[0]! / len, 9)
    expect(plug.forwardMine[1]).toBeCloseTo(dir[1]! / len, 9)
    expect(plug.centerMine[0]).toBeCloseTo(ENTRY[0] + plug.forwardMine[0] * PLUG_HALF_DEPTH_M, 9)
    expect(plug.centerMine[2]).toBeCloseTo(Z + XS.height / 2, 9)
    expect(plug.halfExtents).toEqual([
      XS.width / 2 + PLUG_MARGIN_M,
      XS.height / 2 + PLUG_MARGIN_M,
      PLUG_HALF_DEPTH_M,
    ])
    // Three pose through the canonical rotation: y = mine z
    expect(plug.positionThree[1]).toBeCloseTo(plug.centerMine[2], 9)
    expect(plug.positionThree[2]).toBeCloseTo(-plug.centerMine[1], 9)
  })

  it('one drift side ACTIVE: the other side is a drift face at the entry plane; the crosscut mouth is plugged flush with the drift wall', () => {
    const p = plan(550) // access, −y drift, +y drift active; crosscut not
    expect(p.activePieceIds).toEqual(['LEVEL_ACCESS:L01', 'DRIFT:L01:01', 'DRIFT:L01:02'])
    expect(p.activeKinds).toEqual(['LEVEL_ACCESS', 'DRIFT'])
    expect(p.plugs.map((x) => x.kind)).toEqual(['CROSSCUT_MOUTH'])
    const mouth = p.plugs[0]!
    expect(mouth.nodeId).toBe('JUNCTION:L01:S+01')
    expect(mouth.forwardMine[0]).toBeCloseTo(1, 9) // east, into the crosscut
    expect(mouth.centerMine[0]).toBeCloseTo(STATION[0] + XS.width / 2, 9) // at the drift wall line
    expect(mouth.centerMine[1]).toBeCloseTo(STATION[1], 9)
    const q = plan(450) // access + −y drift active, +y drift not, crosscut not
    expect(q.activePieceIds).toEqual(['LEVEL_ACCESS:L01', 'DRIFT:L01:01'])
    expect(q.plugs.map((x) => `${x.kind}:${x.edgeId}`)).toEqual(['DRIFT_FACE:DRIFT:L01:02'])
    const face = q.plugs[0]!
    expect(face.nodeId).toBe('LEVEL_ENTRY:L01')
    expect(face.forwardMine[1]).toBeCloseTo(1, 9) // north, into the inactive piece
    expect(face.centerMine[1]).toBeCloseTo(ENTRY[1] + PLUG_HALF_DEPTH_M, 9)
  })

  it('everything ACTIVE: every piece collides and no plug remains', () => {
    const p = plan(700)
    expect(p.activePieceIds.length).toBe(4)
    expect(p.activeKinds).toEqual(['LEVEL_ACCESS', 'DRIFT', 'CROSSCUT'])
    expect(p.plugs).toEqual([])
  })

  it('NONE for a ramp-only mine or a legacy chain without level accesses', () => {
    const rampOnly = {
      ...timeline(),
      developments: timeline().developments.filter((d) => d.edgeType === 'RAMP'),
    }
    expect(plan(700, RAMP_ALL, rampOnly).status).toBe('NONE')
    expect(
      resolveTemporalDevelopmentPlan(
        timeline(),
        LEVELS,
        null,
        NETWORK,
        SMOOTHED,
        PIECES,
        700,
        RAMP_ALL,
      ).status,
    ).toBe('NONE')
  })

  it('fails closed: ACTIVE piece without a GLB range, missing network, access before its ramp, unwelded centerline', () => {
    const noPiece = resolveTemporalDevelopmentPlan(
      timeline(),
      LEVELS,
      ACCESSES,
      NETWORK,
      SMOOTHED,
      PIECES.filter((x) => x.pieceId !== 'DRIFT:L01:02'),
      550,
      RAMP_ALL,
    )
    expect(noPiece.status).toBe('INVALID')
    expect(noPiece.reason).toMatch(/DRIFT:L01:02.*no DRIFT GLB piece/)
    expect(
      resolveTemporalDevelopmentPlan(
        timeline(),
        LEVELS,
        ACCESSES,
        null,
        SMOOTHED,
        PIECES,
        550,
        RAMP_ALL,
      ).status,
    ).toBe('INVALID')
    // the access is ACTIVE but the ramp segment ending at its junction is not
    const early = plan(350, [])
    expect(early.status).toBe('INVALID')
    expect(early.reason).toMatch(/access ACTIVE before its ramp segment/)
    // a centerline whose end is not on its node is never guessed
    const bent = {
      ...LEVELS,
      developments: LEVELS.developments.map((d) =>
        d.id === 'DRIFT:L01:02' ? { ...d, centerline: { points: line([31, 56, Z], STATION) } } : d,
      ),
    }
    const r = resolveTemporalDevelopmentPlan(
      timeline(),
      bent,
      ACCESSES,
      NETWORK,
      SMOOTHED,
      PIECES,
      450,
      RAMP_ALL,
    )
    expect(r.status).toBe('INVALID')
    expect(r.reason).toMatch(/not welded/)
  })
})

describe('GLB-free temporal projection (minimap / teleport inputs)', () => {
  it('agrees with the plan on ACTIVE pieces and open accesses, and is null when a development does not resolve', () => {
    for (const day of [250, 350, 450, 550, 700]) {
      const p = plan(day)
      const q = temporalActiveDevelopment(timeline(), LEVELS, ACCESSES, day)!
      expect(q.activePieceIds).toEqual(p.activePieceIds)
      expect(q.openAccessLevelIds).toEqual(p.openAccessLevelIds)
    }
    expect(temporalActiveDevelopment(timeline(), LEVELS, null, 700)).toEqual({
      activePieceIds: [],
      openAccessLevelIds: [],
    })
    const broken = {
      ...timeline(),
      developments: timeline().developments.map((d) =>
        d.edgeId === 'DRIFT:L01:02'
          ? { ...d, geometryRef: { artifact: 'levels.json', segmentIndex: 9 } }
          : d,
      ),
    }
    expect(temporalActiveDevelopment(broken, LEVELS, ACCESSES, 700)).toBeNull()
  })
})
