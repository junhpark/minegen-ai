import type { WorldScene } from '@/types/scene'

/**
 * react-query key of the design assessment read model (rule 189).
 *
 * The key is the IDENTITY of the scene object, not a digest of a few of its
 * fields: every backend mutation reaches the store through `setScene` /
 * `applyScene` with a NEW scene object, so any regenerated artifact — a
 * catalogue with the same winner / count / ranking but different projected
 * values included — yields a new key and a fresh validated read. The same
 * scene object keeps its key (no refetch storm). The backend validated read
 * stays the only correctness authority; this is a cache key.
 */
const generations = new WeakMap<WorldScene, number>()
let nextGeneration = 1

export function sceneGeneration(scene: WorldScene): number {
  let gen = generations.get(scene)
  if (gen === undefined) {
    gen = nextGeneration++
    generations.set(scene, gen)
  }
  return gen
}

export function assessmentKey(scene: WorldScene | null): (string | number | null)[] {
  if (!scene) return [null]
  return [scene.scenarioId, sceneGeneration(scene)]
}
