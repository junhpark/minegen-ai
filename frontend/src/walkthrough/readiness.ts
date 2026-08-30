/**
 * Walkthrough availability gate (rules 99/103): first-person mode requires
 * the authoritative Phase 06 tunnel mesh and a usable effective decline for
 * the deterministic spawn. Pure and directly testable.
 */
import type { WorldScene } from '@/types/scene'
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
