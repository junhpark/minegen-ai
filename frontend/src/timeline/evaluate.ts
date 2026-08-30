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

/**
 * Clip a flat [x,y,z,…] centerline to chainage [0, progress] using the
 * backend pointChainageFractions (aligned 1:1 with the points). Returns the
 * kept vertices plus ONE linearly interpolated cut point between the two
 * bracketing backend vertices — never a vertex beyond the cut (rule 31).
 */
export function clipPolylineByFractions(
  points: number[],
  fractions: number[],
  progress: number,
): number[] {
  const n = fractions.length
  if (n < 2 || points.length !== n * 3) return []
  if (progress <= 0) return []
  if (progress >= 1) return points.slice()
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
