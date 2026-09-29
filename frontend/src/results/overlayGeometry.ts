/**
 * Phase 23C — overlay geometry assembly (pure, testable): the backend edge
 * centerlines of a result's SOURCE snapshot become line segments in Three.js
 * coordinates, coloured per edge by the frame value (missing = neutral), and
 * airflow arrows are placed at the arc-length midpoint of each edge with the
 * sign of the value. Visualization assembly only — no engineering geometry
 * is derived here and nothing is persisted.
 */
import { mineToThree } from '@/geometry/coordinateTransform'
import type { ResultEdgeGeometry } from '@/types/results'
import { type DisplayRange, NEUTRAL_COLOR, rgbToHex, valueRgb } from './colorScale'

/** vertical lift of the overlay above the centerline (metres, mine Z) so it
 * does not z-fight with the design centerline layers */
export const OVERLAY_LIFT_M = 1.2

export interface OverlaySegments {
  /** flat xyz (Three.js) of segment end points, 2 vertices per segment */
  positions: Float32Array
  /** edge index of each VERTEX */
  edgeOfVertex: Int32Array
  /** segment count per edge, in `edges` order */
  segmentsPerEdge: number[]
}

export function buildSegments(edges: ResultEdgeGeometry[]): OverlaySegments {
  let total = 0
  const per: number[] = []
  for (const e of edges) {
    const n = Math.max(e.points.length - 1, 0)
    per.push(n)
    total += n
  }
  const positions = new Float32Array(total * 6)
  const edgeOfVertex = new Int32Array(total * 2)
  let v = 0
  edges.forEach((e, ei) => {
    for (let i = 0; i + 1 < e.points.length; i++) {
      const a = e.points[i] as number[]
      const b = e.points[i + 1] as number[]
      const pa = mineToThree(a[0] ?? 0, a[1] ?? 0, (a[2] ?? 0) + OVERLAY_LIFT_M)
      const pb = mineToThree(b[0] ?? 0, b[1] ?? 0, (b[2] ?? 0) + OVERLAY_LIFT_M)
      positions.set(pa, v * 3)
      positions.set(pb, v * 3 + 3)
      edgeOfVertex[v] = ei
      edgeOfVertex[v + 1] = ei
      v += 2
    }
  })
  return { positions, edgeOfVertex, segmentsPerEdge: per }
}

const NEUTRAL_RGB: [number, number, number] = [
  parseInt(NEUTRAL_COLOR.slice(1, 3), 16) / 255,
  parseInt(NEUTRAL_COLOR.slice(3, 5), 16) / 255,
  parseInt(NEUTRAL_COLOR.slice(5, 7), 16) / 255,
]

/** Per-vertex RGB for the segments: the edge's value colour, or neutral when
 * the frame carries no value for it (never zero-coloured). */
export function buildVertexColors(
  segments: OverlaySegments,
  edges: ResultEdgeGeometry[],
  valueByEdge: ReadonlyMap<string, number>,
  range: DisplayRange | null,
): Float32Array {
  const colors = new Float32Array(segments.edgeOfVertex.length * 3)
  const rgbByEdge: [number, number, number][] = edges.map((e) => {
    const value = valueByEdge.get(e.edgeId)
    if (value === undefined || range === null || !Number.isFinite(value)) return NEUTRAL_RGB
    return valueRgb(value, range)
  })
  for (let v = 0; v < segments.edgeOfVertex.length; v++) {
    const rgb = rgbByEdge[segments.edgeOfVertex[v] as number] ?? NEUTRAL_RGB
    colors[v * 3] = rgb[0]
    colors[v * 3 + 1] = rgb[1]
    colors[v * 3 + 2] = rgb[2]
  }
  return colors
}

export function edgeHex(
  value: number | undefined,
  range: DisplayRange | null,
): string {
  if (value === undefined || range === null || !Number.isFinite(value)) return NEUTRAL_COLOR
  return rgbToHex(valueRgb(value, range))
}

export interface ArrowPlacement {
  edgeId: string
  /** Three.js position at the arc-length midpoint */
  position: [number, number, number]
  /** Three.js unit direction: along sourceNode → targetNode for a positive
   * value, reversed for a negative one */
  direction: [number, number, number]
  value: number
}

/** Mid-edge point and tangent (mine frame) by arc length. */
export function midpointAndTangent(
  points: number[][],
): { point: [number, number, number]; tangent: [number, number, number] } | null {
  if (points.length < 2) return null
  const seg: number[] = []
  let total = 0
  for (let i = 0; i + 1 < points.length; i++) {
    const a = points[i] as number[]
    const b = points[i + 1] as number[]
    const d = Math.hypot(
      (b[0] ?? 0) - (a[0] ?? 0),
      (b[1] ?? 0) - (a[1] ?? 0),
      (b[2] ?? 0) - (a[2] ?? 0),
    )
    seg.push(d)
    total += d
  }
  if (total <= 0) return null
  let target = total / 2
  for (let i = 0; i < seg.length; i++) {
    const d = seg[i] as number
    if (target <= d || i === seg.length - 1) {
      const a = points[i] as number[]
      const b = points[i + 1] as number[]
      const u = d <= 0 ? 0 : target / d
      const dir: [number, number, number] = [
        ((b[0] ?? 0) - (a[0] ?? 0)) / (d || 1),
        ((b[1] ?? 0) - (a[1] ?? 0)) / (d || 1),
        ((b[2] ?? 0) - (a[2] ?? 0)) / (d || 1),
      ]
      return {
        point: [
          (a[0] ?? 0) + u * ((b[0] ?? 0) - (a[0] ?? 0)),
          (a[1] ?? 0) + u * ((b[1] ?? 0) - (a[1] ?? 0)),
          (a[2] ?? 0) + u * ((b[2] ?? 0) - (a[2] ?? 0)),
        ],
        tangent: dir,
      }
    }
    target -= d
  }
  return null
}

/** Airflow arrows: one per edge WITH a finite value; the sign decides the
 * sense along the MineNetwork edge axis (sourceNodeId → targetNodeId). */
export function buildArrows(
  edges: ResultEdgeGeometry[],
  valueByEdge: ReadonlyMap<string, number>,
): ArrowPlacement[] {
  const out: ArrowPlacement[] = []
  for (const e of edges) {
    const value = valueByEdge.get(e.edgeId)
    if (value === undefined || !Number.isFinite(value) || value === 0) continue
    const mt = midpointAndTangent(e.points)
    if (!mt) continue
    const s = value > 0 ? 1 : -1
    const t = mineToThree(mt.tangent[0] * s, mt.tangent[1] * s, mt.tangent[2] * s)
    out.push({
      edgeId: e.edgeId,
      position: mineToThree(mt.point[0], mt.point[1], mt.point[2] + OVERLAY_LIFT_M),
      direction: t,
      value,
    })
  }
  return out
}

/** Quantize the requested time so the frame query key is stable while the
 * clock scrubs / plays (≤ `steps` distinct requests per pass). */
export function quantizeTime(t: number, start: number, end: number, steps = 400): number {
  if (!(end > start)) return start
  const step = (end - start) / steps
  const k = Math.round((Math.min(Math.max(t, start), end) - start) / step)
  return Number((start + k * step).toPrecision(12))
}
