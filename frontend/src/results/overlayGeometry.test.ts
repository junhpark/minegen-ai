import { describe, expect, it } from 'vitest'
import { NEUTRAL_COLOR } from './colorScale'
import {
  buildArrows,
  buildSegments,
  buildVertexColors,
  edgeHex,
  midpointAndTangent,
  OVERLAY_LIFT_M,
  quantizeTime,
} from './overlayGeometry'
import { GEOMETRY } from './results.fixture'

describe('overlay segments', () => {
  it('are the source-snapshot polylines in Three.js coordinates, lifted, one segment per pair', () => {
    const seg = buildSegments(GEOMETRY.edges)
    expect(seg.segmentsPerEdge).toEqual([2, 1])
    expect(seg.positions.length).toBe(3 * 6)
    // mineToThree(x, y, z) = [x, z, -y]; first point (0, 0, 100) lifted
    const near = (xs: ArrayLike<number>) => Array.from(xs, (v) => Number((v + 0).toFixed(3)))
    expect(near(seg.positions.slice(0, 3))).toEqual([0, 100 + OVERLAY_LIFT_M, 0])
    expect(near(seg.positions.slice(3, 6))).toEqual([30, 100 + OVERLAY_LIFT_M, 0])
    expect([...seg.edgeOfVertex]).toEqual([0, 0, 0, 0, 1, 1])
  })

  it('colours a MISSING edge neutral — never as zero', () => {
    const seg = buildSegments(GEOMETRY.edges)
    const range = { min: 0, max: 10 }
    const colors = buildVertexColors(seg, GEOMETRY.edges, new Map([['RAMP:L01', 0]]), range)
    const neutral = [0x5a / 255, 0x64 / 255, 0x70 / 255]
    // RAMP:L01 has the value 0 → the ramp colour of t = 0 (NOT neutral)
    expect([...colors.slice(0, 3)].map((v) => Number(v.toFixed(3)))).toEqual([0.267, 0.005, 0.329])
    // DRIFT:L01:00 is missing → neutral
    expect([...colors.slice(12, 15)].map((v) => Number(v.toFixed(3)))).toEqual(
      neutral.map((v) => Number(v.toFixed(3))),
    )
    expect(edgeHex(undefined, range)).toBe(NEUTRAL_COLOR)
    expect(edgeHex(5, null)).toBe(NEUTRAL_COLOR)
    expect(edgeHex(5, range)).not.toBe(NEUTRAL_COLOR)
  })
})

describe('airflow arrows', () => {
  it('sit at the arc-length midpoint and follow the sign along sourceNode → targetNode', () => {
    const mt = midpointAndTangent(GEOMETRY.edges[0]!.points)
    expect(mt?.point).toEqual([30, 5, 100]) // 70 m polyline: 30 along +x, then 5 along +y
    expect(mt?.tangent).toEqual([0, 1, 0])
    const arrows = buildArrows(GEOMETRY.edges, new Map([['RAMP:L01', -3], ['DRIFT:L01:00', 2]]))
    expect(arrows.map((a) => a.edgeId)).toEqual(['RAMP:L01', 'DRIFT:L01:00'])
    // negative airflow → reversed tangent (mine −y) → Three.js +z
    const plain = (v: readonly number[]) => v.map((x) => x + 0)
    expect(plain(arrows[0]!.direction)).toEqual([0, 0, 1])
    expect(plain(arrows[0]!.position)).toEqual([30, 100 + OVERLAY_LIFT_M, -5])
    // positive along the vertical drift (mine −z) → Three.js −y
    expect(plain(arrows[1]!.direction)).toEqual([0, -1, 0])
    // zero / missing values get no arrow
    expect(buildArrows(GEOMETRY.edges, new Map([['RAMP:L01', 0]]))).toEqual([])
    expect(midpointAndTangent([[0, 0, 0]])).toBeNull()
  })
})

describe('clock quantization', () => {
  it('keeps the frame query key stable while scrubbing', () => {
    expect(quantizeTime(0, 0, 100)).toBe(0)
    expect(quantizeTime(100, 0, 100)).toBe(100)
    expect(quantizeTime(50.1, 0, 100)).toBe(50) // 400 steps of 0.25
    expect(quantizeTime(50.2, 0, 100)).toBe(50.25)
    expect(quantizeTime(50.1, 0, 100, 100)).toBe(quantizeTime(50.4, 0, 100, 100))
    expect(quantizeTime(-5, 0, 100)).toBe(0)
    expect(quantizeTime(500, 0, 100)).toBe(100)
    expect(quantizeTime(7, 3, 3)).toBe(3)
  })
})
