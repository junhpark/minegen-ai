import type { WorldScene } from '@/types/scene'

/** react-query key tokens: the scene slots the assessment is a projection
 * of (rule 189). A change in any of them re-reads the read model; the
 * backend re-validates the artifacts regardless — this is a cache key,
 * never an authority. */
export function assessmentKey(scene: WorldScene | null): (string | null)[] {
  if (!scene) return [null]
  const cat = scene.layoutV2
  const sel = scene.layoutV2Selected
  const cap = scene.capabilityGraph ?? null
  return [
    scene.scenarioId,
    cat ? `${cat.winnerId ?? ''}|${String(cat.candidateCount)}|${cat.ranking.join(',')}` : null,
    sel ? `${sel.candidateId ?? ''}|${sel.sourceRevision ?? ''}|${sel.layoutRevision ?? ''}` : null,
    `${scene.rampSource.activeSource}|${scene.rampSource.candidateId ?? ''}`,
    scene.network ? scene.network.sourceRevision : null,
    cap ? `${cap.sourceRevision}|${cap.networkRevision}` : null,
  ]
}
