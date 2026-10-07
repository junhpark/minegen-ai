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
 *
 * Review round 2 S3: a stage may host several cards (Excavation: ramp tunnel
 * + development meshes), so tones are kept PER REPORTER under the stage and
 * aggregated when read — a running job on any card is a running stage; one
 * card's report never overwrites another's.
 */
export type StageToneReports = Partial<Record<StageId, Readonly<Record<string, StatusTone>>>>

interface ShellState {
  controlsHost: HTMLElement | null
  resultsHost: HTMLElement | null
  stageTones: StageToneReports
  setControlsHost: (el: HTMLElement | null) => void
  setResultsHost: (el: HTMLElement | null) => void
  /** `reporter` identifies the mounted card (unique per instance); `null` withdraws it */
  reportTone: (stage: StageId, reporter: string, tone: StatusTone | null) => void
}

export const useShellStore = create<ShellState>()((set) => ({
  controlsHost: null,
  resultsHost: null,
  stageTones: {},
  setControlsHost: (controlsHost) => set({ controlsHost }),
  setResultsHost: (resultsHost) => set({ resultsHost }),
  reportTone: (stage, reporter, tone) =>
    set((s) => {
      const reports = s.stageTones[stage] ?? {}
      if ((reports[reporter] ?? null) === tone) return {}
      const next: Record<string, StatusTone> = { ...reports }
      if (tone === null) delete next[reporter]
      else next[reporter] = tone
      const stageTones: StageToneReports = { ...s.stageTones }
      if (Object.keys(next).length === 0) delete stageTones[stage]
      else stageTones[stage] = next
      return { stageTones }
    }),
}))

/** the aggregated tone of a stage: RUNNING if any mounted card reports a
 * running job, else FAILED if any reports a failure, else the first report */
export function stageTone(tones: StageToneReports, stage: StageId): StatusTone | null {
  const reports = Object.values(tones[stage] ?? {})
  if (reports.length === 0) return null
  if (reports.includes('RUNNING')) return 'RUNNING'
  if (reports.includes('FAILED')) return 'FAILED'
  return reports[0] ?? null
}

/** the stages where at least one mounted card reports a running job */
export function runningStages(tones: StageToneReports): Set<StageId> {
  const out = new Set<StageId>()
  for (const stage of Object.keys(tones) as StageId[]) {
    if (stageTone(tones, stage) === 'RUNNING') out.add(stage)
  }
  return out
}
