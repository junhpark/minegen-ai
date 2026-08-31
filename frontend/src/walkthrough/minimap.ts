/**
 * Pure minimap model + projection math (§12–19). Top-down NORTH-UP
 * mine-space X/Y projection of the authoritative effective smoothed
 * centerline — nothing is reconstructed from screen coordinates and
 * nothing here is persisted. In TIMELINE_SNAPSHOT only the ACTIVE prefix
 * is emitted; future segments are hidden entirely so the map can never
 * imply they are traversable (§14).
 */
import type { SmoothedDeclinePayload } from '@/types/scene'

export interface MinimapPolyline {
  segmentId: string
  /** mine-space XY pairs, metres: [x0,y0, x1,y1, ...] */
  xy: number[]
}

export interface MinimapModel {
  polylines: MinimapPolyline[]
  /** portal = first point of the first emitted segment */
  portal: [number, number] | null
  /** deep end of the last emitted segment */
  end: [number, number] | null
  /** flattened 3D points of the emitted centerline for chainage lookup */
  chainagePoints: number[]
}

export function buildMinimapModel(
  smoothed: SmoothedDeclinePayload | null | undefined,
  activeSegmentIds: readonly string[] | null,
): MinimapModel {
  const empty: MinimapModel = { polylines: [], portal: null, end: null, chainagePoints: [] }
  const segments = smoothed?.segments
  if (!segments || segments.length === 0) return empty
  const active = activeSegmentIds === null ? null : new Set(activeSegmentIds)
  const polylines: MinimapPolyline[] = []
  const chainagePoints: number[] = []
  for (const seg of segments) {
    if (active !== null && !active.has(seg.levelId)) break // ACTIVE prefix only
    const pts = seg.effectiveCenterline?.points
    if (!Array.isArray(pts) || pts.length < 6) continue
    const xy: number[] = []
    for (let i = 0; i + 2 < pts.length; i += 3) {
      xy.push(pts[i]!, pts[i + 1]!)
      chainagePoints.push(pts[i]!, pts[i + 1]!, pts[i + 2]!)
    }
    polylines.push({ segmentId: seg.levelId, xy })
  }
  const first = polylines[0]
  const last = polylines[polylines.length - 1]
  return {
    polylines,
    portal: first ? [first.xy[0]!, first.xy[1]!] : null,
    end: last ? [last.xy[last.xy.length - 2]!, last.xy[last.xy.length - 1]!] : null,
    chainagePoints,
  }
}

/**
 * North-up SVG mapping: metres → map units with +X (east) to the right
 * and +Y (north) UP, i.e. SVG y is negated. Scale 1 keeps metres.
 */
export function mineXYToMap(x: number, y: number): [number, number] {
  return [x, -y]
}

/** Compass bearing (deg, clockwise from north) of a Three-yaw heading:
 * yaw 0 looks down −Z = mine +Y (north) → bearing 0; yaw +90° (left,
 * −X = west) → bearing 270°. Drives the minimap heading arrow. */
export function bearingDegFromYaw(yaw: number): number {
  const deg = ((-yaw * 180) / Math.PI) % 360
  return (deg + 360) % 360 // also normalizes -0
}

export interface ChainageResult {
  chainageM: number
  distanceM: number
}

/**
 * Approximate decline chainage (§18–19): nearest point on the emitted
 * effective centerline via an O(N) segment scan, run at telemetry rate
 * (~8 Hz), never per render frame. Navigation information only.
 */
export function approximateChainage(
  pointMine: readonly [number, number, number],
  chainagePoints: readonly number[],
): ChainageResult | null {
  const n = Math.floor(chainagePoints.length / 3)
  if (n < 2) return null
  let acc = 0
  let best: ChainageResult | null = null
  for (let i = 0; i + 1 < n; i++) {
    const ax = chainagePoints[i * 3]!
    const ay = chainagePoints[i * 3 + 1]!
    const az = chainagePoints[i * 3 + 2]!
    const bx = chainagePoints[(i + 1) * 3]!
    const by = chainagePoints[(i + 1) * 3 + 1]!
    const bz = chainagePoints[(i + 1) * 3 + 2]!
    const dx = bx - ax
    const dy = by - ay
    const dz = bz - az
    const len2 = dx * dx + dy * dy + dz * dz
    if (len2 < 1e-18) continue
    const t = Math.max(
      0,
      Math.min(
        1,
        ((pointMine[0] - ax) * dx + (pointMine[1] - ay) * dy + (pointMine[2] - az) * dz) / len2,
      ),
    )
    const px = ax + dx * t
    const py = ay + dy * t
    const pz = az + dz * t
    const d = Math.hypot(pointMine[0] - px, pointMine[1] - py, pointMine[2] - pz)
    const seg = Math.sqrt(len2)
    if (best === null || d < best.distanceM) {
      best = { chainageM: acc + seg * t, distanceM: d }
    }
    acc += seg
  }
  return best
}

/** FOLLOW-mode visible radius, metres (§17). */
export const MINIMAP_RADIUS_M = 150
