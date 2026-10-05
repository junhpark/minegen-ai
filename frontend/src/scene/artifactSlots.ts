import type { WorldScene } from '@/types/scene'

/**
 * Hardening H1 §4.4 — after a backend "Reset from here" the response names
 * the derived files it deleted; this maps each file name to the scene slot
 * that displayed it and empties exactly those slots. It is a PRESENTATION
 * mapping (file → slot), not a dependency graph: the closure was decided by
 * the backend registry and is applied as returned, so no new frontend
 * mirror of the invalidation cascade exists (`scene/invalidation.ts` keeps
 * only the two Effective-Ramp identity halves, rule 169).
 *
 * `ramp_source.json` has no slot of its own: the scene's `rampSource`
 * summary is re-read with the next scene load.
 */
export const ARTIFACT_SLOTS: Readonly<Record<string, keyof WorldScene>> = {
  'targets.json': 'accessTargets',
  'decline.json': 'decline',
  'decline_smoothed.json': 'legacySmoothedDecline',
  'layout_v2.json': 'layoutV2',
  'layout_v2_selected.json': 'layoutV2Selected',
  'level_accesses.json': 'levelAccesses',
  'tunnel_mesh.json': 'tunnelMesh',
  'development_mesh.json': 'developmentMesh',
  'levels.json': 'levels',
  'shafts.json': 'shafts',
  'network.json': 'network',
  'capability_graph.json': 'capabilityGraph',
  'stopes.json': 'stopes',
  'timeline.json': 'timeline',
  'communication.json': 'communication',
  'sensors.json': 'sensors',
}

/** the ACTIVE Effective Ramp slot follows its owning artifact */
function activeRampDeleted(scene: WorldScene, deleted: ReadonlySet<string>): boolean {
  const owning = scene.smoothedDecline?.owningArtifact ?? scene.rampSource.owningArtifact
  return owning !== undefined && deleted.has(owning)
}

/** Empty the slots of the deleted files; unknown names (GLBs, the ramp-source
 * root) are ignored. Returns the same object when nothing changed. */
export function clearDeletedArtifacts(scene: WorldScene, deleted: readonly string[]): WorldScene {
  const set = new Set(deleted)
  const next: Record<string, unknown> = { ...scene }
  let changed = false
  for (const name of set) {
    const slot = ARTIFACT_SLOTS[name]
    if (slot === undefined || next[slot] === null || next[slot] === undefined) continue
    next[slot] = null
    changed = true
  }
  if (activeRampDeleted(scene, set) && scene.smoothedDecline !== null) {
    next['smoothedDecline'] = null
    changed = true
  }
  return changed ? (next as unknown as WorldScene) : scene
}
