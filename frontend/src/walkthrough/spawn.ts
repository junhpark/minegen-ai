/**
 * Deterministic walkthrough spawn (rule 102): derived from the
 * backend-authored Phase 05 effective decline at the portal end, a fixed
 * runtime chainage inside the tunnel, above the floor centerline. Pure
 * navigation initialization — never persisted, never engineering geometry.
 * No arbitrary world-origin fallback exists: malformed input returns null.
 */
import { mineToThree } from '@/geometry/coordinateTransform'
import type { SmoothedDeclinePayload } from '@/types/scene'
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
  const first = smoothed?.segments?.[0]
  const flat = first?.effectiveCenterline?.points
  if (!Array.isArray(flat) || flat.length < 6 || flat.length % 3 !== 0) return null
  const n = flat.length / 3
  const pts: [number, number, number][] = []
  for (let i = 0; i < n; i++) {
    const p: number[] = [flat[i * 3]!, flat[i * 3 + 1]!, flat[i * 3 + 2]!]
    if (!finite3(p) || p.some((v) => typeof v !== 'number')) return null
    pts.push(p as [number, number, number])
  }
  // walk the polyline from the portal end (chain start) to the fixed chainage
  const target = config.spawnChainageM
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
