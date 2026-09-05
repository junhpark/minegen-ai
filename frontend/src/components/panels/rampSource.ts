import { useMutation } from '@tanstack/react-query'
import { api } from '@/api/client'
import { afterRampSourceChange } from '@/scene/invalidation'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useViewerStore } from '@/stores/viewerStore'
import type { RampSource, WorldScene } from '@/types/scene'

/**
 * Closeout v3 §1.B: a scenario has "legacy work" when any legacy Hybrid-A*
 * artifact exists. `activeSource === 'LEGACY'` alone is NOT enough — a fresh
 * scenario also starts on LEGACY — so the Advanced legacy section auto-
 * expands only for a scenario that actually uses the legacy chain.
 */
export function hasLegacyWork(scene: WorldScene | null): boolean {
  if (!scene) return false
  return (
    scene.accessTargets !== null || scene.decline !== null || scene.legacySmoothedDecline !== null
  )
}

export function legacySectionAutoOpen(scene: WorldScene | null): boolean {
  return (scene?.rampSource.activeSource ?? 'LEGACY') === 'LEGACY' && hasLegacyWork(scene)
}

/** Explicit Effective Ramp source switch (rule 150) — an ADVANCED action
 * (closeout v3 §1.C). Switching to LAYOUT_V2 hides the legacy diagnostic
 * layers; the scene invalidation mirrors the backend (rule 151). */
export function useRampSourceSwitch() {
  const scene = useScenarioStore((s) => s.scene)
  const applyScene = useScenarioStore((s) => s.applyScene)
  const epoch = useScenarioStore((s) => s.epoch)
  const setLayerVisible = useViewerStore((s) => s.setLayerVisible)
  return useMutation({
    mutationFn: async (source: RampSource) => {
      if (!scene) throw new Error('generate the world first')
      return api.setRampSource(scene.scenarioId, source)
    },
    onSuccess: (src) => {
      applyScene(epoch, (current) => afterRampSourceChange(current, src))
      if (src.activeSource === 'LAYOUT_V2') {
        setLayerVisible('accessTargets', false)
        setLayerVisible('rawSearchPath', false)
      }
    },
  })
}
