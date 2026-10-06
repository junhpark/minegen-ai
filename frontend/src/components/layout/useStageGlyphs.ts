import { useMemo } from 'react'
import { runningStages, useShellStore } from '@/components/layout/shellStore'
import { stageStatuses, type StageGlyph } from '@/components/layout/workflow'
import { useScenarioStore } from '@/stores/scenarioStore'
import type { StageId } from '@/types/workflow'

/**
 * One glyph per stage from the live stores: the scene manifest (artifact
 * presence / status), the scenario document (declared shafts) and the tones
 * the mounted cards report (running jobs). Presentation only.
 */
export function useStageGlyphs(): Record<StageId, StageGlyph> {
  const scenario = useScenarioStore((s) => s.scenario)
  const scene = useScenarioStore((s) => s.scene)
  const tones = useShellStore((s) => s.stageTones)
  return useMemo(
    () =>
      stageStatuses({
        scenario: scenario !== null,
        scene,
        shaftSpecCount: scenario?.shafts?.specs.length ?? 0,
        running: runningStages(tones),
      }),
    [scenario, scene, tones],
  )
}
