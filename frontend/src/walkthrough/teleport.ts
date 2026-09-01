/**
 * Level teleport targets (hotfix 2, item 9): deliberate reset-style jumps
 * to authoritative decline stations — the portal plus each MineNetwork
 * LEVEL_ENTRY node, mapped to its decline chainage via the nearest point
 * on the emitted effective centerline. Navigation convenience only: the
 * destination pose is computed by the SAME deterministic spawn rules, so
 * a teleport can never place the body outside the walkable volume. In
 * TIMELINE_SNAPSHOT the chainage points already stop at the ACTIVE
 * frontier, so beyond-frontier level entries fail the on-decline distance
 * test and are simply not offered.
 */
import type { WorldScene } from '@/types/scene'
import { approximateChainage } from './minimap'

/** a level entry farther than this from the emitted centerline is not on
 * the (currently walkable) decline */
const ON_DECLINE_TOLERANCE_M = 15

export interface TeleportTarget {
  id: string
  label: string
  chainageM: number
}

export function resolveTeleportTargets(
  scene: WorldScene | null | undefined,
  chainagePoints: readonly number[],
): TeleportTarget[] {
  if (!scene?.network || scene.network.status !== 'SUCCESS') return []
  if (chainagePoints.length < 6) return []
  const targets: TeleportTarget[] = [{ id: 'PORTAL', label: 'Portal', chainageM: 0 }]
  for (const node of scene.network.nodes) {
    if (node.type !== 'LEVEL_ENTRY') continue
    const hit = approximateChainage(
      [node.position[0], node.position[1], node.position[2]],
      chainagePoints,
    )
    if (!hit || hit.distanceM > ON_DECLINE_TOLERANCE_M) continue
    targets.push({
      id: node.id,
      label: node.levelId ? `Level ${node.levelId}` : node.id,
      chainageM: hit.chainageM,
    })
  }
  // deterministic order: down the decline
  targets.sort((a, b) => a.chainageM - b.chainageM || a.id.localeCompare(b.id))
  return targets
}
