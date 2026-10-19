/**
 * Deterministic walkthrough spawn (rule 102): derived from the
 * backend-authored Phase 05 effective decline at the portal end, a fixed
 * runtime chainage inside the tunnel, above the floor centerline. Pure
 * navigation initialization — never persisted, never engineering geometry.
 * No arbitrary world-origin fallback exists: malformed input returns null.
 */
import { mineToThree } from '@/geometry/coordinateTransform'
import type { SmoothedDeclinePayload } from '@/types/scene'
import type { ChaseConfig } from './chaseCamera'
import type { WalkthroughConfig } from './config'
import { yawForForward } from './movement'

export interface WalkthroughSpawn {
  /** floor centerline point, mine coordinates (ENU Z-up, m) */
  floorPositionMine: [number, number, number]
  /** capsule body-center position, Three coordinates */
  bodyPositionThree: [number, number, number]
  /** horizontal unit forward, Three coordinates */
  forwardThree: [number, number, number]
  /** initial camera yaw (Three convention); initial pitch is 0 */
  yaw: number
}

function finite3(p: number[]): boolean {
  return p.length === 3 && p.every((v) => Number.isFinite(v))
}

export function resolveWalkthroughSpawn(
  smoothed: SmoothedDeclinePayload | null | undefined,
  config: WalkthroughConfig,
): WalkthroughSpawn | null {
  return resolveSpawnAtChainage(smoothed, config, config.spawnChainageM)
}

/**
 * Spawn chainage of a third-person BODY (PR-4 W2): the entry reference
 * `spawnChainageM` plus the body's chase line (`anchorBackM + distanceM`),
 * so the avatar AND its camera start inside the tunnel. Measured on the
 * acceptance tour: a truck spawned at the 6 m reference had its tail on
 * the portal plane and its camera line through the portal cap, giving a
 * cramped close-up of the bin instead of the drive ahead.
 */
export function bodySpawnChainageM(config: WalkthroughConfig, chase: ChaseConfig): number {
  return config.spawnChainageM + chase.anchorBackM + chase.distanceM
}

/** The entry spawn of a body: the chainage form at `bodySpawnChainageM`. */
export function resolveBodySpawn(
  smoothed: SmoothedDeclinePayload | null | undefined,
  config: WalkthroughConfig,
  chase: ChaseConfig,
): WalkthroughSpawn | null {
  return resolveSpawnAtChainage(smoothed, config, bodySpawnChainageM(config, chase))
}

/**
 * Deterministic body pose at an arbitrary decline chainage (hotfix 2 —
 * level teleport). Walks the CONCATENATED effective centerlines from the
 * portal; identical rules to the entry spawn (floor reference, inward
 * yaw, no fallback). Callers own eligibility (temporal contexts must not
 * pass beyond-frontier chainages).
 */
export function resolveSpawnAtChainage(
  smoothed: SmoothedDeclinePayload | null | undefined,
  config: WalkthroughConfig,
  chainageM: number,
): WalkthroughSpawn | null {
  if (!Number.isFinite(chainageM) || chainageM < 0) return null
  const segments = smoothed?.segments
  if (!segments || segments.length === 0) return null
  const flat: number[] = []
  for (const seg of segments) {
    const pts = seg.effectiveCenterline?.points
    if (!Array.isArray(pts) || pts.length % 3 !== 0) return null
    // segments share boundary points; skip the duplicated first point
    const start = flat.length > 0 ? 3 : 0
    for (let i = start; i < pts.length; i++) flat.push(pts[i]!)
  }
  return resolveSpawnOnPolyline(flat, config, chainageM)
}

/** 3-D length of a flat [x, y, z, …] mine-space polyline. */
export function polylineLength(flat: readonly number[]): number {
  let acc = 0
  for (let i = 3; i + 2 < flat.length; i += 3) {
    acc += Math.hypot(
      flat[i]! - flat[i - 3]!,
      flat[i + 1]! - flat[i - 2]!,
      flat[i + 2]! - flat[i - 1]!,
    )
  }
  return acc
}

/**
 * PR-4 W3: the same deterministic pose on ANY authoritative floor
 * centerline (a level access, a drift) at a chainage from its first point —
 * the ramp form above is this function over the concatenated ramp. Pure,
 * no fallback: malformed input or a chainage beyond the polyline is null.
 */
export function resolveSpawnOnPolyline(
  flat: readonly number[],
  config: WalkthroughConfig,
  chainageM: number,
): WalkthroughSpawn | null {
  if (!Number.isFinite(chainageM) || chainageM < 0) return null
  if (flat.length < 6 || flat.length % 3 !== 0) return null
  const n = flat.length / 3
  const pts: [number, number, number][] = []
  for (let i = 0; i < n; i++) {
    const p: number[] = [flat[i * 3]!, flat[i * 3 + 1]!, flat[i * 3 + 2]!]
    if (!finite3(p) || p.some((v) => typeof v !== 'number')) return null
    pts.push(p as [number, number, number])
  }
  // walk the polyline from the portal end (chain start) to the chainage
  const target = chainageM
  let acc = 0
  let floor: [number, number, number] | null = null
  let tangent: [number, number, number] | null = null
  for (let i = 0; i + 1 < n; i++) {
    const a = pts[i]!
    const b = pts[i + 1]!
    const seg = Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2])
    if (seg < 1e-12) continue
    if (acc + seg >= target) {
      const t = (target - acc) / seg
      floor = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]
      tangent = [(b[0] - a[0]) / seg, (b[1] - a[1]) / seg, (b[2] - a[2]) / seg]
      break
    }
    acc += seg
  }
  if (!floor || !tangent) return null // tunnel shorter than the spawn chainage
  const fThree = mineToThree(...tangent)
  const horiz = Math.hypot(fThree[0], fThree[2])
  if (horiz < 1e-6) return null // vertical tangent cannot define walking yaw
  const forwardThree: [number, number, number] = [fThree[0] / horiz, 0, fThree[2] / horiz]
  const floorThree = mineToThree(...floor)
  const bodyPositionThree: [number, number, number] = [
    floorThree[0],
    floorThree[1] + config.bodyHeightM / 2 + config.spawnFloorClearanceM,
    floorThree[2],
  ]
  if (!finite3(bodyPositionThree)) return null
  return {
    floorPositionMine: floor,
    bodyPositionThree,
    forwardThree,
    yaw: yawForForward(forwardThree[0], forwardThree[2]),
  }
}
