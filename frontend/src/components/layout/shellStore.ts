import { create } from 'zustand'
import type { StatusTone } from '@/components/ui/presentation'
import type { StageId } from '@/types/workflow'

/**
 * Hardening H1 §4.2 — the two column hosts of the three-pane shell, plus the
 * tone every MOUNTED staged card currently shows.
 *
 * The feature panels stay MOUNTED exactly where they were (one container,
 * one set of hooks each); a `WorkflowCard` that declares its stage renders
 * its ACTION into the controls column and its STATUS / metrics / failure /
 * details into the results column through portals to these two elements.
 * The columns register their host elements here when they mount. A card
 * also reports its badge tone while mounted (and withdraws it on unmount),
 * which is how the stepper shows ↻ for a stage whose job is running — the
 * tone is the same backend-status presentation the badge shows, never a
 * second status source. Frontend-local DOM plumbing, never persisted.
 */
interface ShellState {
  controlsHost: HTMLElement | null
  resultsHost: HTMLElement | null
  stageTones: Partial<Record<StageId, StatusTone>>
  setControlsHost: (el: HTMLElement | null) => void
  setResultsHost: (el: HTMLElement | null) => void
  reportTone: (stage: StageId, tone: StatusTone | null) => void
}

export const useShellStore = create<ShellState>()((set) => ({
  controlsHost: null,
  resultsHost: null,
  stageTones: {},
  setControlsHost: (controlsHost) => set({ controlsHost }),
  setResultsHost: (resultsHost) => set({ resultsHost }),
  reportTone: (stage, tone) =>
    set((s) => {
      if ((s.stageTones[stage] ?? null) === tone) return {}
      const stageTones = { ...s.stageTones }
      if (tone === null) delete stageTones[stage]
      else stageTones[stage] = tone
      return { stageTones }
    }),
}))

/** the stages whose mounted card reports a running job */
export function runningStages(tones: Partial<Record<StageId, StatusTone>>): Set<StageId> {
  const out = new Set<StageId>()
  for (const [stage, tone] of Object.entries(tones)) {
    if (tone === 'RUNNING') out.add(stage as StageId)
  }
  return out
}
