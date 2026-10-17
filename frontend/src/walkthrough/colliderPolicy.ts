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

/** how the development GLB is mounted: every emitted primitive (final
 * layout) or only the pieces the temporal plan marks ACTIVE */
export type DevelopmentPhysicsMode = 'STATIC_ALL' | 'TEMPORAL_ACTIVE'

/**
 * Phase 20D.2 (rule 187): whether the walkthrough mounts the development
 * (LEVEL_ACCESS / DRIFT / CROSSCUT) excavation physics. Both contexts mount
 * it exactly when the scene advertises a SUCCESS development mesh with a
 * meshUrl — a missing/failed development artifact keeps the ramp-only
 * walkthrough (Case A), an advertised one is mandatory and its runtime
 * geometry is validated on load (Case C fails closed, never a silent
 * ramp-only fallback). STATIC_FINAL mounts every primitive; a
 * TIMELINE_SNAPSHOT (PR-4 W1a) mounts only the pieces whose development is
 * ACTIVE at the snapshot day (`temporalDevelopmentPlan.ts`) — final
 * development geometry still never leaks into a historical snapshot.
 */
export function resolveDevelopmentPhysics(
  context: WalkthroughContext,
  developmentMesh: { status: string; meshUrl?: string | null } | null | undefined,
): { mount: boolean; meshUrl: string | null; mode: DevelopmentPhysicsMode } {
  const mode: DevelopmentPhysicsMode = context === 'STATIC_FINAL' ? 'STATIC_ALL' : 'TEMPORAL_ACTIVE'
  if (!developmentMesh || developmentMesh.status !== 'SUCCESS' || !developmentMesh.meshUrl) {
    return { mount: false, meshUrl: null, mode }
  }
  return { mount: true, meshUrl: developmentMesh.meshUrl, mode }
}

/** load / validation state of the development runtime geometry */
export type DevelopmentRuntimeState = 'NOT_MOUNTED' | 'VALID' | 'MALFORMED'

export interface WalkthroughComposition {
  /** the ramp tunnel trimesh colliders are always mounted */
  tunnelCollider: true
  /** the development trimesh colliders are mounted */
  developmentCollider: boolean
  /** the walkthrough must fail closed: an advertised development GLB
   * violates the runtime contract (never a silent ramp-only fallback) */
  failClosed: boolean
}

/**
 * Phase 20D.2 (rule 187) physics-world composition. Case A (no development
 * artifact) keeps the ramp-only baseline; Case B (advertised + valid
 * runtime geometry) mounts ramp AND development colliders in ONE physics
 * world; Case C (advertised but malformed) fails closed. The same three
 * cases hold for a TIMELINE_SNAPSHOT (PR-4 W1a), whose development
 * colliders are the ACTIVE pieces and whose openings onto not-yet-active
 * developments are closed by plugs and the aperture barrier.
 */
export function resolveWalkthroughComposition(
  context: WalkthroughContext,
  developmentMesh: { status: string; meshUrl?: string | null } | null | undefined,
  runtime: DevelopmentRuntimeState,
): WalkthroughComposition {
  const physics = resolveDevelopmentPhysics(context, developmentMesh)
  if (!physics.mount) return { tunnelCollider: true, developmentCollider: false, failClosed: false }
  if (runtime === 'VALID')
    return { tunnelCollider: true, developmentCollider: true, failClosed: false }
  // NOT_MOUNTED with an advertised mesh is a caller bug, MALFORMED is the
  // authoritative GLB's fault: neither may become a ramp-only walkthrough
  return { tunnelCollider: true, developmentCollider: false, failClosed: true }
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
