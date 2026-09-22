/**
 * Temporal aperture containment (Phase 20D.2, rule 187 — TIMELINE_SNAPSHOT).
 *
 * Since Phase 20D.1 the emitted ramp GLB carries a typed RAMP_ACCESS
 * aperture in its wall at every level-access turnout. The temporal
 * walkthrough mounts the ramp colliders only (development physics and
 * geometry are not modelled in time), so without a barrier a player could
 * step through an aperture into uncollided void. This module closes every
 * aperture with EPHEMERAL runtime barrier pieces — the same navigation
 * safety construct as the frontier barrier (rule 115): access-control
 * geometry, never engineering excavation geometry, never persisted.
 *
 * Authority: the apertures are declared by the tunnel report (junction
 * summary, `byType.RAMP_ACCESS`) and located by the authoritative level
 * accesses (`rampJunction` welded onto the effective ramp centerline, the
 * access centerline deciding the branch side). The barrier follows the ramp
 * WALL LINE — one thin cuboid per centerline interval inside the aperture
 * window, offset half a tunnel width toward the branch, gravity-aligned —
 * exactly the chord the swept wall itself follows between its rings (rule
 * 65: refinement rings lie on the validated polyline), so a curved ramp is
 * covered without a straight-line approximation across the whole window.
 * The window mirrors the backend cut locality (`JUNCTION_WINDOW_WIDTHS` = 2
 * tunnel widths about the junction) plus one width of margin on each side.
 *
 * Fail closed (rule 117 analogue): apertures declared but no usable level
 * accesses, a count mismatch, or a junction not welded to the ramp
 * centerline make the temporal walkthrough unavailable — the frontend
 * never guesses where an aperture is.
 */
import { Matrix4, Quaternion, Vector3 } from 'three'
import { mineToThree } from '@/geometry/coordinateTransform'
import {
  rampSegmentId,
  type LevelAccessPayload,
  type SmoothedDeclinePayload,
  type TunnelJunctionSummary,
} from '@/types/scene'

/** backend parent-cut locality (`JUNCTION_WINDOW_WIDTHS`), in tunnel widths */
export const APERTURE_WINDOW_WIDTHS = 2
/** extra chainage on each side of the cut window, in tunnel widths */
export const APERTURE_MARGIN_WIDTHS = 1
/** half-length extension of every piece so pieces overlap at polyline corners */
export const APERTURE_PIECE_OVERLAP_M = 1.25
export const APERTURE_HALF_DEPTH_M = 0.125
export const APERTURE_HEIGHT_MARGIN_M = 0.25
/** a junction must sit on the ramp centerline within this distance */
export const APERTURE_WELD_TOLERANCE_M = 1e-3

type Vec3 = [number, number, number]

export interface ApertureBarrierPiece {
  colliderId: string
  levelId: string
  segmentId: string
  /** cuboid CENTER, Three coordinates */
  positionThree: Vec3
  /** orientation quaternion [x, y, z, w], Three coordinates */
  quaternion: [number, number, number, number]
  /** [length/2 + overlap, height/2 + margin, half depth] */
  halfExtents: Vec3
  /** authoritative mine-space fields (tests) */
  wallStartMine: Vec3
  wallEndMine: Vec3
  /** unit vector from the ramp centerline TOWARD the branch */
  lateralMine: Vec3
  upMine: Vec3
}

export interface ApertureContainment {
  /** NONE: the ramp GLB declares no aperture; VALID: every declared aperture
   * is located; INVALID: fail closed (temporal walkthrough unavailable) */
  status: 'NONE' | 'VALID' | 'INVALID'
  reason: string | null
  expectedApertures: number
  pieces: ApertureBarrierPiece[]
}

function norm(v: Vec3): Vec3 | null {
  const l = Math.hypot(v[0], v[1], v[2])
  if (!(l > 1e-9)) return null
  return [v[0] / l, v[1] / l, v[2] / l]
}

function cross(a: Vec3, b: Vec3): Vec3 {
  return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
}

function gravityUp(forward: Vec3): Vec3 | null {
  const dz = forward[2]
  return norm([-dz * forward[0], -dz * forward[1], 1 - dz * forward[2]])
}

interface RampPolyline {
  points: Vec3[]
  chainage: number[]
  /** segment id owning interval i → i + 1 */
  intervalSegment: string[]
}

function invalid(expected: number, reason: string): ApertureContainment {
  return { status: 'INVALID', reason, expectedApertures: expected, pieces: [] }
}

/** Concatenate the effective ramp segments into one polyline (shared
 * boundary points de-duplicated); returns null on malformed geometry. */
export function rampPolyline(smoothed: SmoothedDeclinePayload): RampPolyline | null {
  const points: Vec3[] = []
  const intervalSegment: string[] = []
  for (const seg of smoothed.segments) {
    const flat = seg.effectiveCenterline?.points
    if (!Array.isArray(flat) || flat.length < 6 || flat.length % 3 !== 0) return null
    const id = rampSegmentId(seg)
    for (let i = 0; i < flat.length; i += 3) {
      const p: Vec3 = [flat[i]!, flat[i + 1]!, flat[i + 2]!]
      if (!p.every((v) => Number.isFinite(v))) return null
      const last = points[points.length - 1]
      if (last && Math.hypot(p[0] - last[0], p[1] - last[1], p[2] - last[2]) < 1e-9) continue
      if (points.length > 0) intervalSegment.push(id)
      points.push(p)
    }
  }
  if (points.length < 2) return null
  const chainage = [0]
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1]!
    const b = points[i]!
    chainage.push(chainage[i - 1]! + Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]))
  }
  return { points, chainage, intervalSegment }
}

function piecePose(
  p0: Vec3,
  p1: Vec3,
  side: number,
  ramp: { tunnelWidth: number; tunnelHeight: number },
  levelId: string,
  segmentId: string,
  index: number,
): ApertureBarrierPiece | null {
  const forward = norm([p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]])
  if (!forward) return null
  const up = gravityUp(forward)
  if (!up) return null
  const lateral = cross(up, forward) // (lateral, up, forward) right-handed
  const off = side * (ramp.tunnelWidth / 2)
  const wallStart: Vec3 = [
    p0[0] + off * lateral[0],
    p0[1] + off * lateral[1],
    p0[2] + off * lateral[2],
  ]
  const wallEnd: Vec3 = [
    p1[0] + off * lateral[0],
    p1[1] + off * lateral[1],
    p1[2] + off * lateral[2],
  ]
  const halfH = ramp.tunnelHeight / 2
  const center: Vec3 = [
    0.5 * (wallStart[0] + wallEnd[0]) + up[0] * halfH,
    0.5 * (wallStart[1] + wallEnd[1]) + up[1] * halfH,
    0.5 * (wallStart[2] + wallEnd[2]) + up[2] * halfH,
  ]
  const length = Math.hypot(p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
  // local x = forward (piece length), y = up, z = forward × up (thin depth)
  const zAxis = cross(forward, up)
  const fT = new Vector3(...mineToThree(...forward))
  const uT = new Vector3(...mineToThree(...up))
  const zT = new Vector3(...mineToThree(...zAxis))
  const q = new Quaternion().setFromRotationMatrix(new Matrix4().makeBasis(fT, uT, zT))
  if (![q.x, q.y, q.z, q.w].every((v) => Number.isFinite(v))) return null
  return {
    colliderId: `WALK:TEMPORAL:APERTURE:${levelId}:${index}`,
    levelId,
    segmentId,
    positionThree: mineToThree(...center),
    quaternion: [q.x, q.y, q.z, q.w],
    halfExtents: [
      length / 2 + APERTURE_PIECE_OVERLAP_M,
      ramp.tunnelHeight / 2 + APERTURE_HEIGHT_MARGIN_M,
      APERTURE_HALF_DEPTH_M,
    ],
    wallStartMine: wallStart,
    wallEndMine: wallEnd,
    lateralMine: [side * lateral[0], side * lateral[1], side * lateral[2]],
    upMine: up,
  }
}

/**
 * Locate every declared RAMP_ACCESS aperture and close it on the ACTIVE
 * segments with wall-line barrier pieces. Pure and snapshot-stable.
 */
export function resolveApertureContainment(
  tunnelJunctions: TunnelJunctionSummary | null | undefined,
  levelAccesses: { status: string; accesses: LevelAccessPayload[] } | null | undefined,
  smoothed: SmoothedDeclinePayload,
  activeSegmentIds: readonly string[],
  ramp: { tunnelWidth: number; tunnelHeight: number },
): ApertureContainment {
  const expected = tunnelJunctions?.byType?.RAMP_ACCESS ?? 0
  if (!Number.isInteger(expected) || expected < 0) {
    return invalid(0, 'tunnel junction summary is malformed')
  }
  if (expected === 0) return { status: 'NONE', reason: null, expectedApertures: 0, pieces: [] }
  if (
    !levelAccesses ||
    levelAccesses.status !== 'SUCCESS' ||
    !Array.isArray(levelAccesses.accesses)
  ) {
    return invalid(expected, 'ramp apertures are declared but the level accesses are unavailable')
  }
  const declared = levelAccesses.accesses.filter(
    (a) => a.status === 'OK' && a.rampJunction !== null && a.centerline !== null,
  )
  if (declared.length !== expected) {
    return invalid(
      expected,
      `ramp declares ${expected} RAMP_ACCESS apertures but ${declared.length} level accesses locate one`,
    )
  }
  if (
    !Number.isFinite(ramp.tunnelWidth) ||
    ramp.tunnelWidth <= 0 ||
    !Number.isFinite(ramp.tunnelHeight) ||
    ramp.tunnelHeight <= 0
  ) {
    return invalid(expected, 'scenario ramp dimensions are unusable')
  }
  const poly = rampPolyline(smoothed)
  if (!poly) return invalid(expected, 'effective ramp centerline is malformed')
  const active = new Set(activeSegmentIds)
  const width = ramp.tunnelWidth
  const half = (APERTURE_WINDOW_WIDTHS + APERTURE_MARGIN_WIDTHS) * width
  const pieces: ApertureBarrierPiece[] = []
  const seen = new Set<string>()
  for (const access of declared) {
    if (seen.has(access.levelId))
      return invalid(expected, `duplicate level access ${access.levelId}`)
    seen.add(access.levelId)
    const J = access.rampJunction as Vec3
    // the junction is welded onto the ramp centerline (a shared boundary point)
    let iJ = -1
    let best = Infinity
    poly.points.forEach((p, i) => {
      const d = Math.hypot(p[0] - J[0], p[1] - J[1], p[2] - J[2])
      if (d < best) {
        best = d
        iJ = i
      }
    })
    if (iJ < 0 || best > APERTURE_WELD_TOLERANCE_M) {
      return invalid(expected, `junction of ${access.levelId} is not on the ramp centerline`)
    }
    const prev = poly.points[Math.max(iJ - 1, 0)]!
    const next = poly.points[Math.min(iJ + 1, poly.points.length - 1)]!
    const tJ = norm([next[0] - prev[0], next[1] - prev[1], next[2] - prev[2]])
    if (!tJ) return invalid(expected, `degenerate ramp tangent at ${access.levelId}`)
    const upJ = gravityUp(tJ)
    if (!upJ) return invalid(expected, `vertical ramp tangent at ${access.levelId}`)
    const latJ = cross(upJ, tJ)
    // branch side from the access centerline: the first station that has
    // left the junction in plan by a quarter width (else the last station)
    const flat = access.centerline!.points
    if (!Array.isArray(flat) || flat.length < 6 || flat.length % 3 !== 0) {
      return invalid(expected, `access centerline of ${access.levelId} is malformed`)
    }
    let side = 0
    for (let i = 3; i < flat.length; i += 3) {
      const d: Vec3 = [flat[i]! - J[0], flat[i + 1]! - J[1], flat[i + 2]! - J[2]]
      const dot = d[0] * latJ[0] + d[1] * latJ[1] + d[2] * latJ[2]
      if (Math.hypot(d[0], d[1]) >= 0.25 * width || i + 3 >= flat.length) {
        side = dot > 0 ? 1 : dot < 0 ? -1 : 0
        break
      }
    }
    if (side === 0) return invalid(expected, `branch side of ${access.levelId} is undecidable`)
    const sJ = poly.chainage[iJ]!
    const lo = sJ - half
    const hi = sJ + half
    for (let i = 0; i < poly.points.length - 1; i++) {
      if (!active.has(poly.intervalSegment[i]!)) continue
      const a = poly.chainage[i]!
      const b = poly.chainage[i + 1]!
      const s0 = Math.max(a, lo)
      const s1 = Math.min(b, hi)
      if (!(s1 - s0 > 1e-6)) continue
      const pa = poly.points[i]!
      const pb = poly.points[i + 1]!
      const t0 = (s0 - a) / (b - a)
      const t1 = (s1 - a) / (b - a)
      const p0: Vec3 = [
        pa[0] + t0 * (pb[0] - pa[0]),
        pa[1] + t0 * (pb[1] - pa[1]),
        pa[2] + t0 * (pb[2] - pa[2]),
      ]
      const p1: Vec3 = [
        pa[0] + t1 * (pb[0] - pa[0]),
        pa[1] + t1 * (pb[1] - pa[1]),
        pa[2] + t1 * (pb[2] - pa[2]),
      ]
      const piece = piecePose(p0, p1, side, ramp, access.levelId, poly.intervalSegment[i]!, i)
      if (!piece) return invalid(expected, `degenerate ramp interval ${i} at ${access.levelId}`)
      pieces.push(piece)
    }
  }
  const ids = pieces.map((p) => p.colliderId)
  if (new Set(ids).size !== ids.length) return invalid(expected, 'aperture barrier ids collide')
  return { status: 'VALID', reason: null, expectedApertures: expected, pieces }
}
