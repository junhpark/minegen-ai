/**
 * Phase 14 interaction runtime configuration (rule 105): usability/runtime
 * values only — never engineering parameters, never persisted in Scenario.
 */
export interface WalkthroughInteractionConfig {
  /** center-ray interaction reach, m */
  maxInteractionDistanceM: number
  /**
   * invisible pick-target radius around an asset point, m. UI interaction
   * geometry ONLY (§12): it is analytic ray math, never rendered, never a
   * Rapier collider, never persisted, and never implies real device size.
   */
  hitProxyRadiusM: number
  /** ray-intersection tolerance for the wall-occlusion comparison, m */
  occlusionEpsilonM: number
  /** visible marker radius for walkthrough asset symbols, m */
  markerRadiusM: number
}

export const WALKTHROUGH_INTERACTION_CONFIG: WalkthroughInteractionConfig = {
  maxInteractionDistanceM: 10.0,
  hitProxyRadiusM: 0.65,
  occlusionEpsilonM: 0.05,
  markerRadiusM: 0.22,
}
