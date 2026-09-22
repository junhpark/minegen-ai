import { describe, expect, it } from 'vitest'
import type {
  LevelAccessPayload,
  SmoothedDeclinePayload,
  TunnelJunctionSummary,
} from '@/types/scene'
import {
  APERTURE_HALF_DEPTH_M,
  APERTURE_HEIGHT_MARGIN_M,
  APERTURE_MARGIN_WIDTHS,
  APERTURE_PIECE_OVERLAP_M,
  APERTURE_WINDOW_WIDTHS,
  rampPolyline,
  resolveApertureContainment,
} from './apertureBarrier'

const RAMP = { tunnelWidth: 5, tunnelHeight: 5.5 }

/** north-heading ramp, 10 % down, points every 5 m: A 0–40, B 40–80, C 80–120 */
function segment(id: string, levelId: string | null, y0: number, y1: number) {
  const points: number[] = []
  for (let y = y0; y <= y1; y += 5) points.push(0, y, -0.1 * y)
  return {
    segmentId: id,
    levelId,
    effectiveCenterline: { points, pointCount: points.length / 3 },
    boundaryTangents: { start: [0, 1, -0.1], end: [0, 1, -0.1] },
  } as unknown as SmoothedDeclinePayload['segments'][number]
}
const SMOOTHED = {
  status: 'SUCCESS',
  segments: [
    segment('RAMP_JUNCTION:L01', 'L01', 0, 40),
    segment('RAMP_JUNCTION:L02', 'L02', 40, 80),
    segment('RAMP_END', null, 80, 120),
  ],
} as unknown as SmoothedDeclinePayload
const ALL = ['RAMP_JUNCTION:L01', 'RAMP_JUNCTION:L02', 'RAMP_END']

function access(levelId: string, junctionY: number, sideX: number): LevelAccessPayload {
  const J = [0, junctionY, -0.1 * junctionY]
  // leaves the ramp at a shallow angle toward ±x
  const pts = [
    ...J,
    sideX * 0.6,
    junctionY + 4,
    J[2]!,
    sideX * 2.5,
    junctionY + 9,
    J[2]!,
    sideX * 8,
    junctionY + 16,
    J[2]!,
  ]
  return {
    levelId,
    status: 'OK',
    rampJunction: J,
    centerline: { points: pts, pointCount: pts.length / 3 },
  } as unknown as LevelAccessPayload
}
const ACCESSES = {
  status: 'SUCCESS',
  accesses: [access('L01', 40, +1), access('L02', 80, -1)],
}
const JUNCTIONS: TunnelJunctionSummary = {
  count: 2,
  byType: { RAMP_ACCESS: 2 },
  openedEndpointCount: 2,
  removedTriangles: 40,
}
const HALF_WINDOW = (APERTURE_WINDOW_WIDTHS + APERTURE_MARGIN_WIDTHS) * RAMP.tunnelWidth
/** the window is measured along the 3-D chainage; on the 10 % ramp one metre of
 * chainage spans this much northing */
const HALF_WINDOW_Y = HALF_WINDOW / Math.hypot(1, 0.1)

describe('temporal aperture containment (Phase 20D.2, rule 187)', () => {
  it('NONE when the ramp GLB declares no RAMP_ACCESS aperture (legacy ramp-only contract)', () => {
    expect(resolveApertureContainment(undefined, ACCESSES, SMOOTHED, ALL, RAMP).status).toBe('NONE')
    expect(
      resolveApertureContainment({ ...JUNCTIONS, byType: {} }, ACCESSES, SMOOTHED, ALL, RAMP)
        .status,
    ).toBe('NONE')
  })

  it('closes every declared aperture on the branch side of the ramp wall, inside the cut window', () => {
    const c = resolveApertureContainment(JUNCTIONS, ACCESSES, SMOOTHED, ALL, RAMP)
    expect(c.status).toBe('VALID')
    expect(c.expectedApertures).toBe(2)
    const l01 = c.pieces.filter((p) => p.levelId === 'L01')
    const l02 = c.pieces.filter((p) => p.levelId === 'L02')
    expect(l01.length).toBeGreaterThan(0)
    expect(l02.length).toBeGreaterThan(0)
    for (const p of l01) {
      // east wall line: x = +width/2, y inside [40 − 15, 40 + 15]
      expect(p.wallStartMine[0]).toBeCloseTo(RAMP.tunnelWidth / 2, 9)
      expect(p.wallEndMine[0]).toBeCloseTo(RAMP.tunnelWidth / 2, 9)
      expect(p.wallStartMine[1]).toBeGreaterThanOrEqual(40 - HALF_WINDOW_Y - 1e-9)
      expect(p.wallEndMine[1]).toBeLessThanOrEqual(40 + HALF_WINDOW_Y + 1e-9)
      expect(p.lateralMine[0]).toBeGreaterThan(0.99)
      expect(p.upMine[2]).toBeGreaterThan(0.99)
    }
    for (const p of l02) {
      expect(p.wallStartMine[0]).toBeCloseTo(-RAMP.tunnelWidth / 2, 9)
      expect(p.wallStartMine[1]).toBeGreaterThanOrEqual(80 - HALF_WINDOW_Y - 1e-9)
      expect(p.wallEndMine[1]).toBeLessThanOrEqual(80 + HALF_WINDOW_Y + 1e-9)
    }
    // the pieces tile the whole window contiguously on the wall line
    const ys = l01.flatMap((p) => [p.wallStartMine[1], p.wallEndMine[1]])
    expect(Math.min(...ys)).toBeCloseTo(40 - HALF_WINDOW_Y, 9)
    expect(Math.max(...ys)).toBeCloseTo(40 + HALF_WINDOW_Y, 9)
    const sorted = [...l01].sort((a, b) => a.wallStartMine[1] - b.wallStartMine[1])
    for (let i = 1; i < sorted.length; i++) {
      expect(sorted[i]!.wallStartMine[1]).toBeCloseTo(sorted[i - 1]!.wallEndMine[1], 9)
    }
    // pose: center at wall midpoint + up·h/2 through the canonical rotation,
    // extents = half length + overlap, half height + margin, thin depth
    const p = sorted[1]!
    const h2 = RAMP.tunnelHeight / 2
    const mid = [
      0.5 * (p.wallStartMine[0] + p.wallEndMine[0]) + p.upMine[0] * h2,
      0.5 * (p.wallStartMine[1] + p.wallEndMine[1]) + p.upMine[1] * h2,
      0.5 * (p.wallStartMine[2] + p.wallEndMine[2]) + p.upMine[2] * h2,
    ]
    expect(p.positionThree[0]).toBeCloseTo(mid[0]!, 6)
    expect(p.positionThree[1]).toBeCloseTo(mid[2]!, 6)
    expect(p.positionThree[2]).toBeCloseTo(-mid[1]!, 6)
    const len = Math.hypot(
      p.wallEndMine[0] - p.wallStartMine[0],
      p.wallEndMine[1] - p.wallStartMine[1],
      p.wallEndMine[2] - p.wallStartMine[2],
    )
    expect(p.halfExtents).toEqual([
      len / 2 + APERTURE_PIECE_OVERLAP_M,
      RAMP.tunnelHeight / 2 + APERTURE_HEIGHT_MARGIN_M,
      APERTURE_HALF_DEPTH_M,
    ])
    p.quaternion.forEach((v) => expect(Number.isFinite(v)).toBe(true))
    expect(new Set(c.pieces.map((x) => x.colliderId)).size).toBe(c.pieces.length)
  })

  it('mounts pieces only on ACTIVE segments — an inactive branch side is closed by the frontier', () => {
    // only segment A active: the L01 aperture window straddles A|B at y = 40
    const c = resolveApertureContainment(JUNCTIONS, ACCESSES, SMOOTHED, ['RAMP_JUNCTION:L01'], RAMP)
    expect(c.status).toBe('VALID')
    expect(c.pieces.every((p) => p.segmentId === 'RAMP_JUNCTION:L01')).toBe(true)
    expect(c.pieces.every((p) => p.levelId === 'L01')).toBe(true)
    const ys = c.pieces.flatMap((p) => [p.wallStartMine[1], p.wallEndMine[1]])
    expect(Math.max(...ys)).toBeCloseTo(40, 9)
    expect(Math.min(...ys)).toBeCloseTo(40 - HALF_WINDOW_Y, 9)
    // a snapshot with nothing active mounts nothing, and is still VALID
    expect(resolveApertureContainment(JUNCTIONS, ACCESSES, SMOOTHED, [], RAMP)).toMatchObject({
      status: 'VALID',
      pieces: [],
    })
  })

  it('M7 / fail closed: declared apertures without usable level accesses never become uncollided void', () => {
    for (const bad of [
      null,
      undefined,
      { status: 'FAILED', accesses: [] },
      { status: 'SUCCESS', accesses: [] },
    ]) {
      const c = resolveApertureContainment(JUNCTIONS, bad, SMOOTHED, ALL, RAMP)
      expect(c.status).toBe('INVALID')
      expect(c.pieces).toEqual([])
    }
    // count mismatch (one aperture unlocated) is an identity failure
    const one = { status: 'SUCCESS', accesses: [access('L01', 40, +1)] }
    expect(resolveApertureContainment(JUNCTIONS, one, SMOOTHED, ALL, RAMP).status).toBe('INVALID')
    // a junction that is not welded onto the ramp centerline is never guessed
    const off = {
      status: 'SUCCESS',
      accesses: [{ ...access('L01', 40, +1), rampJunction: [0.5, 40, -4] }, access('L02', 80, -1)],
    }
    expect(resolveApertureContainment(JUNCTIONS, off as never, SMOOTHED, ALL, RAMP).status).toBe(
      'INVALID',
    )
    // unusable ramp dimensions fail closed too
    expect(
      resolveApertureContainment(JUNCTIONS, ACCESSES, SMOOTHED, ALL, {
        tunnelWidth: 0,
        tunnelHeight: 5.5,
      }).status,
    ).toBe('INVALID')
  })

  it('polyline: shared boundary points are de-duplicated and intervals belong to the later segment', () => {
    const poly = rampPolyline(SMOOTHED)!
    expect(poly.points.length).toBe(25)
    expect(poly.chainage[poly.chainage.length - 1]).toBeCloseTo(24 * Math.hypot(5, 0.5), 9)
    expect(poly.intervalSegment[7]).toBe('RAMP_JUNCTION:L01')
    expect(poly.intervalSegment[8]).toBe('RAMP_JUNCTION:L02')
    expect(poly.intervalSegment[16]).toBe('RAMP_END')
  })
})
