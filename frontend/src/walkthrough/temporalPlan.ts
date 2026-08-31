/**
 * Temporal walkthrough plan resolver (rules 111–117).
 *
 * Maps the authoritative Phase 10 timeline onto Phase 05/06 decline
 * segments for a captured snapshot day. Timeline is the ONLY time source:
 * each RAMP DevelopmentTimeline resolves through geometryRef
 * (artifact 'decline_smoothed.json', segmentIndex) — positional or lexical
 * inference is forbidden (rule 113). Walkability is conservative
 * (rule 114): NOT_BUILT / DEVELOPING are not walkable; a segment becomes
 * physically traversable exactly at its ACTIVE transition via the Phase 10
 * exact-boundary stateAt(). Any missing, malformed, duplicate,
 * out-of-range or identity-inconsistent mapping fails CLOSED (rule 117) —
 * the frontend never guesses a temporal segment association.
 */
import { stateAt } from '@/timeline/evaluate'
import type { SmoothedDeclinePayload, TimelinePayload } from '@/types/scene'
import type { TunnelRuntimeGeometry } from './tunnelRuntimeGeometry'

export const SMOOTHED_ARTIFACT = 'decline_smoothed.json'

export interface TemporalFrontier {
  /** last ACTIVE segment id owning the barrier */
  segmentId: string
  segmentIndex: number
}

export interface TemporalWalkthroughPlan {
  status: 'VALID' | 'INVALID'
  reason: string | null
  snapshotDay: number
  activeSegmentIds: string[]
  activeSegmentIndices: number[]
  allSegmentsActive: boolean
  lastActiveSegmentIndex: number | null
  frontier: TemporalFrontier | null
}

function invalid(snapshotDay: number, reason: string): TemporalWalkthroughPlan {
  return {
    status: 'INVALID',
    reason,
    snapshotDay,
    activeSegmentIds: [],
    activeSegmentIndices: [],
    allSegmentsActive: false,
    lastActiveSegmentIndex: null,
    frontier: null,
  }
}

/**
 * Validate the RAMP timeline → smoothed-segment mapping and return the
 * ACTIVE segment indices at `day` (ascending), or a string reason.
 * Shared by readiness (no GLB needed) and the full runtime plan.
 */
export function resolveActiveRampIndices(
  timeline: TimelinePayload | null | undefined,
  smoothed: SmoothedDeclinePayload | null | undefined,
  day: number,
): { indices: number[]; total: number } | string {
  if (!Number.isFinite(day)) return 'snapshot day is not finite'
  if (!timeline || timeline.status !== 'SUCCESS') return 'timeline is not available'
  const segments = smoothed?.segments
  if (!segments || segments.length === 0) return 'smoothed decline is not available'
  const ramps = timeline.developments.filter((d) => d.edgeType === 'RAMP')
  if (ramps.length !== segments.length) {
    return `RAMP development count ${ramps.length} != smoothed segment count ${segments.length}`
  }
  const seen = new Set<number>()
  const active: number[] = []
  for (const dev of ramps) {
    const ref = dev.geometryRef
    if (ref.artifact !== SMOOTHED_ARTIFACT) {
      return `RAMP ${dev.edgeId} owns artifact ${ref.artifact}, expected ${SMOOTHED_ARTIFACT}`
    }
    const i = ref.segmentIndex
    if (!Number.isInteger(i) || i < 0 || i >= segments.length) {
      return `RAMP ${dev.edgeId} segmentIndex ${i} out of range`
    }
    if (seen.has(i)) return `duplicate segmentIndex ${i}`
    seen.add(i)
    if (stateAt(dev.initialState, dev.transitions, day) === 'ACTIVE') active.push(i)
  }
  // every index exactly once is implied by count equality + uniqueness
  active.sort((a, b) => a - b)
  // ACTIVE indices must form a contiguous prefix [0..k] (rule/§10)
  for (let k = 0; k < active.length; k++) {
    if (active[k] !== k) {
      return `ACTIVE segments are not a portal-prefix: [${active.join(',')}]`
    }
  }
  return { indices: active, total: segments.length }
}

/** Active segment IDS (levelId) without needing the loaded GLB — used by
 * the temporal VISUAL layer; runtime identity is validated separately. */
export function temporalActiveSegmentIds(
  timeline: TimelinePayload | null | undefined,
  smoothed: SmoothedDeclinePayload | null | undefined,
  day: number,
): string[] | null {
  const r = resolveActiveRampIndices(timeline, smoothed, day)
  if (typeof r === 'string') return null
  return r.indices.map((i) => smoothed!.segments[i]!.levelId)
}

export function resolveTemporalWalkthroughPlan(
  timeline: TimelinePayload | null | undefined,
  smoothed: SmoothedDeclinePayload | null | undefined,
  runtime: TunnelRuntimeGeometry,
  snapshotDay: number,
): TemporalWalkthroughPlan {
  const mapped = resolveActiveRampIndices(timeline, smoothed, snapshotDay)
  if (typeof mapped === 'string') return invalid(snapshotDay, mapped)
  const segments = smoothed!.segments
  if (runtime.segments.length !== segments.length) {
    return invalid(
      snapshotDay,
      `runtime segment count ${runtime.segments.length} != smoothed ${segments.length}`,
    )
  }
  // exact runtime identity validation (rule 113): GLB primitive segmentId
  // is the Phase 05 levelId, index-aligned
  for (let i = 0; i < segments.length; i++) {
    if (runtime.segments[i]!.segmentId !== segments[i]!.levelId) {
      return invalid(
        snapshotDay,
        `runtime segment ${i} id ${runtime.segments[i]!.segmentId} != smoothed levelId ${segments[i]!.levelId}`,
      )
    }
  }
  const ids = runtime.segments.map((s) => s.segmentId)
  if (new Set(ids).size !== ids.length) return invalid(snapshotDay, 'duplicate runtime segmentId')
  const { indices, total } = mapped
  const allSegmentsActive = indices.length === total
  const lastActiveSegmentIndex = indices.length > 0 ? indices[indices.length - 1]! : null
  const frontier =
    !allSegmentsActive && lastActiveSegmentIndex !== null
      ? { segmentId: ids[lastActiveSegmentIndex]!, segmentIndex: lastActiveSegmentIndex }
      : null
  return {
    status: 'VALID',
    reason: null,
    snapshotDay,
    activeSegmentIds: indices.map((i) => ids[i]!),
    activeSegmentIndices: indices,
    allSegmentsActive,
    lastActiveSegmentIndex,
    frontier,
  }
}
