/**
 * Ramp teleport targets ("Go to…", hardening H0 §3.2): deliberate
 * reset-style jumps to authoritative stations ON the main ramp — the portal
 * plus every ramp turnout. Navigation convenience only: the destination
 * pose is computed by the SAME deterministic spawn rules, so a teleport can
 * never place the body outside the walkable volume.
 *
 * Authority is the backend's `RAMP_JUNCTION.chainage` (the main-ramp chainage
 * of the turnout where a level access leaves the ramp). The list never
 * depends on the level development: when the network is absent (levels
 * FAILED, nothing downstream) the same chainages are read from the level
 * accesses (`rampJunctionChainage`), and failing that from the Effective
 * Ramp's own segment boundaries — rule 155 splits the ramp EXACTLY at its
 * junctions (PARAMETRIC_V2 `rampJunction`), and a LEGACY segment ends at the
 * level entry on the ramp. No proximity test, no LEVEL_ENTRY node: a layout-v2
 * level entry sits ≥ 6 × tunnel width away from the ramp at the end of its
 * access branch and is a branch-teleport (later scope), not a ramp station.
 *
 * In TIMELINE_SNAPSHOT the chainage points stop at the ACTIVE frontier, so a
 * turnout beyond the emitted centerline is simply not offered.
 */
import type {
  LevelAccessesPayload,
  NetworkPayload,
  SmoothedDeclinePayload,
  WorldScene,
} from '@/types/scene'

/** A ramp station (portal / turnout) placed by main-ramp chainage, or — PR-4
 * W3 — a LEVEL_ENTRY placed at the end of the level's access branch. */
export type TeleportTarget =
  | { kind: 'RAMP'; id: string; label: string; chainageM: number }
  | {
      kind: 'LEVEL_ENTRY'
      id: string
      label: string
      levelId: string
      elevation: number
      /** main-ramp chainage of the level's turnout (ordering only) */
      chainageM: number
    }

export type TeleportAuthority =
  'NETWORK_RAMP_JUNCTION' | 'LEVEL_ACCESS_JUNCTION' | 'RAMP_SEGMENT_BOUNDARY' | 'NONE'

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

/** 3-D length of the emitted centerline (the walkable chainage extent) */
export function chainageExtent(chainagePoints: readonly number[]): number {
  const n = Math.floor(chainagePoints.length / 3)
  let acc = 0
  for (let i = 1; i < n; i++) {
    const dx = chainagePoints[i * 3]! - chainagePoints[(i - 1) * 3]!
    const dy = chainagePoints[i * 3 + 1]! - chainagePoints[(i - 1) * 3 + 1]!
    const dz = chainagePoints[i * 3 + 2]! - chainagePoints[(i - 1) * 3 + 2]!
    acc += Math.hypot(dx, dy, dz)
  }
  return acc
}

function fromNetwork(network: NetworkPayload | null | undefined): TeleportTarget[] | null {
  if (!network || network.status !== 'SUCCESS') return null
  const out: TeleportTarget[] = []
  for (const node of network.nodes) {
    if (node.type !== 'RAMP_JUNCTION' || !finite(node.chainage)) continue
    out.push({
      kind: 'RAMP',
      id: node.id,
      label: node.levelId ? `Turnout ${node.levelId}` : node.id,
      chainageM: node.chainage,
    })
  }
  return out.length > 0 ? out : null
}

function fromLevelAccesses(
  accesses: LevelAccessesPayload | null | undefined,
): TeleportTarget[] | null {
  if (!accesses || !Array.isArray(accesses.accesses)) return null
  const out: TeleportTarget[] = []
  for (const a of accesses.accesses) {
    if (a.status !== 'OK' || !finite(a.rampJunctionChainage)) continue
    out.push({
      kind: 'RAMP',
      id: `RAMP_JUNCTION:${a.levelId}`,
      label: `Turnout ${a.levelId}`,
      chainageM: a.rampJunctionChainage,
    })
  }
  return out.length > 0 ? out : null
}

/** segment boundaries of the Effective Ramp: a PARAMETRIC_V2 segment ends at
 * its ramp junction (rule 155); a LEGACY segment ends at the level entry ON
 * the ramp (its chainage is the cumulative length up to that boundary) */
function fromSegments(smoothed: SmoothedDeclinePayload): TeleportTarget[] | null {
  const out: TeleportTarget[] = []
  let acc = 0
  for (const seg of smoothed.segments) {
    const pts = seg.effectiveCenterline?.points
    if (!Array.isArray(pts) || pts.length < 6) continue
    for (let i = 3; i + 2 < pts.length; i += 3) {
      acc += Math.hypot(pts[i]! - pts[i - 3]!, pts[i + 1]! - pts[i - 2]!, pts[i + 2]! - pts[i - 1]!)
    }
    if (seg.rampJunction && finite(seg.rampJunction.chainage)) {
      out.push({
        kind: 'RAMP',
        id: `RAMP_JUNCTION:${seg.rampJunction.levelId}`,
        label: `Turnout ${seg.rampJunction.levelId}`,
        chainageM: seg.rampJunction.chainage,
      })
    } else if (
      seg.terminalKind !== 'RAMP_END' &&
      seg.effectiveSource !== 'PARAMETRIC_V2' &&
      seg.levelId
    ) {
      out.push({
        kind: 'RAMP',
        id: `LEVEL_ENTRY:${seg.levelId}`,
        label: `Level ${seg.levelId}`,
        chainageM: acc,
      })
    }
  }
  return out.length > 0 ? out : null
}

export function resolveTeleportAuthority(scene: WorldScene | null | undefined): {
  authority: TeleportAuthority
  turnouts: TeleportTarget[]
} {
  if (!scene?.smoothedDecline) return { authority: 'NONE', turnouts: [] }
  const net = fromNetwork(scene.network)
  if (net) return { authority: 'NETWORK_RAMP_JUNCTION', turnouts: net }
  const acc = fromLevelAccesses(scene.levelAccesses)
  if (acc) return { authority: 'LEVEL_ACCESS_JUNCTION', turnouts: acc }
  const seg = fromSegments(scene.smoothedDecline)
  if (seg) return { authority: 'RAMP_SEGMENT_BOUNDARY', turnouts: seg }
  return { authority: 'NONE', turnouts: [] }
}

/**
 * PR-4 W3 branch teleport: a LEVEL_ENTRY target per level whose access
 * excavation is collided — `mountedLevelIds` (STATIC_FINAL with the
 * development mesh: every OK access; TIMELINE_SNAPSHOT: the accesses ACTIVE
 * at the snapshot day). The target carries the level's RL and its turnout
 * chainage for ordering; the pose itself is resolved on the access
 * centerline by the runtime (3 m short of the entry, facing the drift).
 */
export function levelEntryTargets(
  accesses: LevelAccessesPayload | null | undefined,
  mountedLevelIds: ReadonlySet<string>,
): TeleportTarget[] {
  if (!accesses || accesses.status !== 'SUCCESS') return []
  const out: TeleportTarget[] = []
  for (const a of accesses.accesses) {
    if (a.status !== 'OK' || !a.centerline || !mountedLevelIds.has(a.levelId)) continue
    if (!finite(a.elevation) || !finite(a.rampJunctionChainage)) continue
    out.push({
      kind: 'LEVEL_ENTRY',
      id: `LEVEL_ENTRY:${a.levelId}`,
      label: `Level ${a.levelId} entry`,
      levelId: a.levelId,
      elevation: a.elevation,
      chainageM: a.rampJunctionChainage,
    })
  }
  return out
}

export function resolveTeleportTargets(
  scene: WorldScene | null | undefined,
  chainagePoints: readonly number[],
  mountedLevelIds: ReadonlySet<string> = new Set(),
): TeleportTarget[] {
  if (!scene?.smoothedDecline || chainagePoints.length < 6) return []
  const extent = chainageExtent(chainagePoints)
  const targets: TeleportTarget[] = [{ kind: 'RAMP', id: 'PORTAL', label: 'Portal', chainageM: 0 }]
  const seen = new Set<string>(['PORTAL'])
  for (const t of [
    ...resolveTeleportAuthority(scene).turnouts,
    ...levelEntryTargets(scene.levelAccesses, mountedLevelIds),
  ]) {
    // beyond the emitted (ACTIVE-prefix) centerline → not walkable, not offered
    if (t.chainageM < 0 || t.chainageM > extent + 1e-6 || seen.has(t.id)) continue
    seen.add(t.id)
    targets.push(t)
  }
  // deterministic order: down the ramp, a turnout before its level entry
  targets.sort(
    (a, b) =>
      a.chainageM - b.chainageM ||
      (a.kind === b.kind ? 0 : a.kind === 'RAMP' ? -1 : 1) ||
      a.id.localeCompare(b.id),
  )
  return targets
}
