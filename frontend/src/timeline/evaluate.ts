import type { DevelopmentTimeline, ObjectStateId, StateTransition } from '@/types/scene'

/**
 * Phase 10 temporal evaluation (rules 83/84/86): the frontend EVALUATES the
 * backend-generated contracts — exact-boundary state lookup, linear progress
 * windows and chainage clipping between existing backend vertices. It never
 * recomputes engineering chainage or schedules.
 */

/** state(day) = the latest transition whose day <= day (rule 84, binding). */
export function stateAt(
  initial: ObjectStateId,
  transitions: StateTransition[],
  day: number,
): ObjectStateId {
  let state = initial
  for (const t of transitions) {
    if (t.day <= day) state = t.state
    else break
  }
  return state
}

/** Continuous development progress: 0 before start, linear while
 * DEVELOPING, 1 after completion — clamped to [0, 1]. */
export function developmentProgress(dev: DevelopmentTimeline, day: number): number {
  const { progressStartDay: s, progressEndDay: e } = dev
  if (e <= s) return day >= e ? 1 : 0
  return Math.min(1, Math.max(0, (day - s) / (e - s)))
}

/** Phase 20C.1-V: progress direction of a development along its point
 * order (rule 174); pre-20C.1 artifacts carry none and mean +1. */
export function progressDirectionOf(dev: Pick<DevelopmentTimeline, 'progressDirection'>): 1 | -1 {
  return dev.progressDirection === -1 ? -1 : 1
}

/**
 * Clip a flat [x,y,z,…] centerline to the revealed chainage window using the
 * backend pointChainageFractions (aligned 1:1 with the points): [0, progress]
 * when progress runs with the point order (direction +1), [1 − progress, 1]
 * when the excavation starts at the LAST point (direction −1, rule 174).
 * Returns the kept vertices plus ONE linearly interpolated cut point between
 * the two bracketing backend vertices — never a vertex beyond the cut
 * (rule 31). The returned polyline keeps the geometry's point order.
 */
export function clipPolylineByFractions(
  points: number[],
  fractions: number[],
  progress: number,
  direction: 1 | -1 = 1,
): number[] {
  const n = fractions.length
  if (n < 2 || points.length !== n * 3) return []
  if (progress <= 0) return []
  if (progress >= 1) return points.slice()
  if (direction === -1) {
    // mirror: reverse the point order and fractions, clip the prefix, un-mirror
    const rp: number[] = []
    const rf: number[] = []
    for (let i = n - 1; i >= 0; i -= 1) {
      rp.push(points[i * 3]!, points[i * 3 + 1]!, points[i * 3 + 2]!)
      rf.push(1 - fractions[i]!)
    }
    const clipped = clipPolylineByFractions(rp, rf, progress, 1)
    const back: number[] = []
    for (let i = clipped.length / 3 - 1; i >= 0; i -= 1) {
      back.push(clipped[i * 3]!, clipped[i * 3 + 1]!, clipped[i * 3 + 2]!)
    }
    return back
  }
  const out: number[] = []
  let i = 0
  while (i < n && fractions[i]! <= progress) {
    out.push(points[i * 3]!, points[i * 3 + 1]!, points[i * 3 + 2]!)
    i += 1
  }
  if (i === 0) {
    // progress below the first interior fraction step: cut inside segment 0
    i = 1
    out.push(points[0]!, points[1]!, points[2]!)
  }
  if (i < n) {
    const f0 = fractions[i - 1]!
    const f1 = fractions[i]!
    const t = f1 > f0 ? (progress - f0) / (f1 - f0) : 0
    for (let d = 0; d < 3; d += 1) {
      const a = points[(i - 1) * 3 + d]!
      const b = points[i * 3 + d]!
      out.push(a + (b - a) * t)
    }
  }
  return out
}

/**
 * 4D-mode static-layer suppression (§23): while a SUCCESS timeline drives
 * the scene, the full static excavation layers must not render — showing
 * future excavation as built would violate rule 31. Terrain/orebody/
 * geology/network overlays stay eligible.
 */
export function staticExcavationVisibleIn4D(timelineActive: boolean): boolean {
  return !timelineActive
}
