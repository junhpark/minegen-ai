/**
 * Pure center-ray targeting math (rule 107). The interaction ray originates
 * at the first-person camera and travels along the exact camera forward
 * direction (center crosshair — never mouse-screen coordinates). An asset
 * is focusable only when its ray distance is within the runtime interaction
 * range AND strictly closer than the tunnel wall along the same ray
 * (through-rock focus is impossible). Deterministic tie break: nearest
 * distance, then lexicographic id.
 */
import type { WalkthroughInteractionConfig } from './interactionConfig'

export interface RayTarget {
  id: string
  positionThree: [number, number, number]
}

/** Nearest positive ray/sphere intersection distance, or null. */
export function raySphereDistance(
  origin: [number, number, number],
  dir: [number, number, number],
  center: [number, number, number],
  radius: number,
): number | null {
  const ox = center[0] - origin[0]
  const oy = center[1] - origin[1]
  const oz = center[2] - origin[2]
  const tca = ox * dir[0] + oy * dir[1] + oz * dir[2]
  const d2 = ox * ox + oy * oy + oz * oz - tca * tca
  const r2 = radius * radius
  if (d2 > r2) return null
  const thc = Math.sqrt(r2 - d2)
  const t0 = tca - thc
  const t1 = tca + thc
  if (t0 > 0) return t0
  if (t1 > 0) return 0 // camera inside the proxy: treat as touching
  return null
}

/**
 * Focused target id for the current camera ray, or null.
 * `wallDistance` is the authoritative tunnel occlusion distance along the
 * same ray (null = no wall hit within range).
 */
export function computeFocus(
  origin: [number, number, number],
  dir: [number, number, number],
  targets: readonly RayTarget[],
  wallDistance: number | null,
  config: WalkthroughInteractionConfig,
): string | null {
  const wall = wallDistance ?? Number.POSITIVE_INFINITY
  let bestId: string | null = null
  let bestT = Number.POSITIVE_INFINITY
  for (const target of targets) {
    const t = raySphereDistance(origin, dir, target.positionThree, config.hitProxyRadiusM)
    if (t === null) continue
    if (t > config.maxInteractionDistanceM) continue
    if (!(t < wall - config.occlusionEpsilonM)) continue
    if (t < bestT || (t === bestT && bestId !== null && target.id < bestId)) {
      bestT = t
      bestId = target.id
    }
  }
  return bestId
}

/**
 * Edge-triggered inspect key (§6): one physical E press → one action.
 * Holding the key (auto-repeat) never re-fires; every lifecycle exit
 * (unlock, blur, unmount, mode switch) clears the held state.
 */
export interface InspectTrigger {
  press: () => boolean
  release: () => void
  clear: () => void
}

export function createInspectTrigger(): InspectTrigger {
  let held = false
  return {
    press() {
      if (held) return false
      held = true
      return true
    },
    release() {
      held = false
    },
    clear() {
      held = false
    },
  }
}
