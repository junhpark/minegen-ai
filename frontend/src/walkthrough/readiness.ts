/**
 * Walkthrough availability gate (rules 99/103): first-person mode requires
 * the authoritative Phase 06 tunnel mesh and a usable effective decline for
 * the deterministic spawn. Pure and directly testable.
 */
import type { WorldScene } from '@/types/scene'
import { resolveActiveRampIndices } from './temporalPlan'
import { WALKTHROUGH_CONFIG } from './config'
import { resolveWalkthroughSpawn } from './spawn'

export type WalkthroughReadiness =
  | 'READY'
  | 'NO_SCENE'
  | 'TUNNEL_NOT_GENERATED'
  | 'TUNNEL_FAILED'
  | 'SMOOTHED_NOT_AVAILABLE'
  | 'INVALID_SPAWN_GEOMETRY'

export function walkthroughReadiness(scene: WorldScene | null | undefined): WalkthroughReadiness {
  if (!scene) return 'NO_SCENE'
  const tunnel = scene.tunnelMesh
  if (!tunnel) return 'TUNNEL_NOT_GENERATED'
  if (tunnel.status !== 'SUCCESS' || !tunnel.meshUrl) return 'TUNNEL_FAILED'
  const smoothed = scene.smoothedDecline
  // SUCCESS_WITH_FALLBACK still owns consumable effective centerlines (the
  // tunnel itself was generated from them), so it is walkable too
  if (!smoothed || smoothed.status === 'FAILED') return 'SMOOTHED_NOT_AVAILABLE'
  if (resolveWalkthroughSpawn(smoothed, WALKTHROUGH_CONFIG) === null) {
    return 'INVALID_SPAWN_GEOMETRY'
  }
  return 'READY'
}

export const READINESS_MESSAGES: Record<Exclude<WalkthroughReadiness, 'READY'>, string> = {
  NO_SCENE: 'Load a scenario first',
  TUNNEL_NOT_GENERATED: 'Generate a successful tunnel mesh first',
  TUNNEL_FAILED: 'Generate a successful tunnel mesh first',
  SMOOTHED_NOT_AVAILABLE: 'Generate a smoothed decline first',
  INVALID_SPAWN_GEOMETRY: 'Smoothed decline geometry cannot host a walkthrough spawn',
}

/** Layers that stay visible inside the immersive walkthrough view. */
const WALKTHROUGH_ALLOWED = new Set(['terrain', 'tunnelMesh'])

/**
 * Derived walkthrough visibility (§15): engineering/debug overlays are
 * suppressed WITHOUT mutating the user's stored visibleLayers.
 */
export function deriveVisibleLayers<T extends string>(mode: string, visible: Set<T>): Set<T> {
  if (mode !== 'WALKTHROUGH') return visible
  const out = new Set<T>()
  for (const layer of visible) if (WALKTHROUGH_ALLOWED.has(layer)) out.add(layer)
  return out
}

export type TemporalReadiness =
  | WalkthroughReadiness
  | 'TIMELINE_NOT_AVAILABLE'
  | 'TEMPORAL_MAPPING_INVALID'
  | 'NO_COMPLETED_SEGMENT'
  | 'SCENARIO_RAMP_UNAVAILABLE'

/**
 * TIMELINE_SNAPSHOT readiness (§11): static Phase 13 readiness first, then
 * the authoritative RAMP mapping must validate at the snapshot day with at
 * least segment 0 ACTIVE. Runtime GLB identity is re-validated on mount;
 * this gate needs no loaded mesh.
 */
export function temporalWalkthroughReadiness(
  scene: WorldScene | null | undefined,
  snapshotDay: number,
  ramp: { tunnelWidth: number; tunnelHeight: number } | null | undefined,
): TemporalReadiness {
  const base = walkthroughReadiness(scene)
  if (base !== 'READY') return base
  // PR #12 blocker 3: the temporal frontier needs Scenario-authored ramp
  // dimensions — guessed defaults are forbidden, so fail closed here
  if (
    !ramp ||
    !Number.isFinite(ramp.tunnelWidth) ||
    ramp.tunnelWidth <= 0 ||
    !Number.isFinite(ramp.tunnelHeight) ||
    ramp.tunnelHeight <= 0
  ) {
    return 'SCENARIO_RAMP_UNAVAILABLE'
  }
  if (!scene?.timeline || scene.timeline.status !== 'SUCCESS') return 'TIMELINE_NOT_AVAILABLE'
  const mapped = resolveActiveRampIndices(scene.timeline, scene.smoothedDecline, snapshotDay)
  if (typeof mapped === 'string') return 'TEMPORAL_MAPPING_INVALID'
  if (mapped.indices.length === 0) return 'NO_COMPLETED_SEGMENT'
  return 'READY'
}

export const TEMPORAL_READINESS_MESSAGES: Record<
  Exclude<TemporalReadiness, 'READY' | Exclude<WalkthroughReadiness, 'READY'>>,
  string
> = {
  TIMELINE_NOT_AVAILABLE: 'Generate a successful timeline first',
  SCENARIO_RAMP_UNAVAILABLE: 'Scenario ramp dimensions are unavailable',
  TEMPORAL_MAPPING_INVALID: 'Timeline does not map onto the decline segments',
  NO_COMPLETED_SEGMENT: 'No completed decline segment is available at this day.',
}

export function temporalReadinessMessage(r: TemporalReadiness): string | undefined {
  if (r === 'READY') return undefined
  if (r in READINESS_MESSAGES)
    return READINESS_MESSAGES[r as Exclude<WalkthroughReadiness, 'READY'>]
  return TEMPORAL_READINESS_MESSAGES[r as keyof typeof TEMPORAL_READINESS_MESSAGES]
}
