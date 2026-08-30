/**
 * Phase 13 walkthrough runtime configuration (rule 99): navigation/runtime
 * assumptions only — NOT mining engineering parameters. Never persisted.
 */
export interface WalkthroughConfig {
  /** total upright body height, m */
  bodyHeightM: number
  /** capsule radius, m */
  bodyRadiusM: number
  /** walking speed, m/s */
  walkSpeedMps: number
  /** gravity magnitude, m/s² (Three/Rapier -Y) */
  gravityMps2: number
  /** deterministic spawn chainage from the portal end, m */
  spawnChainageM: number
  /** small clearance between capsule bottom and floor at spawn, m */
  spawnFloorClearanceM: number
  /** eye height above the floor, m (camera offset from body center is derived) */
  eyeHeightM: number
  /** headlamp reach, m */
  headlampRangeM: number
}

export const WALKTHROUGH_CONFIG: WalkthroughConfig = {
  bodyHeightM: 1.7,
  bodyRadiusM: 0.3,
  walkSpeedMps: 2.0,
  gravityMps2: 9.81,
  spawnChainageM: 2.5,
  spawnFloorClearanceM: 0.05,
  eyeHeightM: 1.6,
  headlampRangeM: 60,
}

/** Rapier capsule half-height of the cylindrical part (total = 2*(h+r)). */
export function capsuleHalfHeight(config: WalkthroughConfig): number {
  return config.bodyHeightM / 2 - config.bodyRadiusM
}

/** Camera Y offset from the rigid-body center (eye height vs body center). */
export function eyeOffsetFromBodyCenter(config: WalkthroughConfig): number {
  return config.eyeHeightM - config.bodyHeightM / 2
}
