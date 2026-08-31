/**
 * Physical collider policy per walkthrough context (rules 112/115/118).
 * Pure, snapshot-stable: the returned topology never mutates during a
 * walkthrough session.
 */
import type { TemporalWalkthroughPlan } from './temporalPlan'

export type WalkthroughContext = 'STATIC_FINAL' | 'TIMELINE_SNAPSHOT'

export interface ColliderPolicy {
  segmentIds: string[]
  includePortalCap: boolean
  includeTerminalCap: boolean
  /** last-active segment id owning the temporal frontier, or null */
  frontierSegmentId: string | null
}

export function resolveColliderPolicy(
  context: WalkthroughContext,
  allSegmentIds: readonly string[],
  plan: TemporalWalkthroughPlan | null,
): ColliderPolicy {
  if (context === 'STATIC_FINAL') {
    return {
      segmentIds: [...allSegmentIds],
      includePortalCap: true,
      includeTerminalCap: true,
      frontierSegmentId: null,
    }
  }
  if (!plan || plan.status !== 'VALID') {
    // fail closed (rule 117): nothing walkable
    return {
      segmentIds: [],
      includePortalCap: true,
      includeTerminalCap: false,
      frontierSegmentId: null,
    }
  }
  return {
    segmentIds: [...plan.activeSegmentIds],
    includePortalCap: true,
    includeTerminalCap: plan.allSegmentsActive,
    frontierSegmentId: plan.frontier?.segmentId ?? null,
  }
}
