import { useMemo } from 'react'
import { runningStages, useShellStore } from '@/components/layout/shellStore'
import { stageStatuses, type StageGlyph } from '@/components/layout/workflow'
import { useScenarioStore } from '@/stores/scenarioStore'
import { completedStagesFor, useViewerStore } from '@/stores/viewerStore'
import type { StageId } from '@/types/workflow'

/**
 * One glyph per stage from the live stores: the scene manifest (artifact
 * presence / status), the scenario document (declared shafts), the tones
 * the mounted cards report (running jobs) and the viewer-completed stages
 * (Analysis shown, Export downloaded — S2, bound to the scene revision, round 3
 * B2). Presentation only.
 */
export function useStageGlyphs(): Record<StageId, StageGlyph> {
  const scenario = useScenarioStore((s) => s.scenario)
  const scene = useScenarioStore((s) => s.scene)
  const sceneRevision = useScenarioStore((s) => s.sceneRevision)
  const tones = useShellStore((s) => s.stageTones)
  const completion = useViewerStore((s) => s.completedViewerStages)
  return useMemo(
    () =>
      stageStatuses({
        scenario: scenario !== null,
        scene,
        shaftSpecCount: scenario?.shafts?.specs.length ?? 0,
        running: runningStages(tones),
        // round 3 B2: only completions of THIS scene revision count
        completed: completedStagesFor(completion, sceneRevision),
      }),
    [scenario, scene, sceneRevision, tones, completion],
  )
}
