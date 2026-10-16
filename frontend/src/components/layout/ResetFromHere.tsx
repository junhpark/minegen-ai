import { runningStages, useShellStore } from '@/components/layout/shellStore'
import { resettable, resetStageFor, STAGE_LABEL } from '@/components/layout/workflow'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useViewerStore } from '@/stores/viewerStore'

/**
 * Hardening H1 §4.4 — "Reset from here" for the current stage, in the
 * controls column. PR-3 moved the confirmation itself into the one dialog
 * host (`ResetDialogs`), shared with the ribbon's quick access and the flow
 * dock: this button only requests it. The backend artifact registry stays
 * the ONLY authority (the dialog reads `reset-plan?from=<stage>` and shows
 * `willDelete` verbatim); nothing here decides what depends on what.
 *
 * PR #53 review B2 — a reset never races a job: the button is disabled while
 * any mounted card reports a running job (the backend refuses the same case
 * with 409 RESET_JOB_RUNNING, shown verbatim in the dialog when it is a job
 * this view does not know about).
 */
export function ResetFromHere() {
  const stage = useViewerStore((s) => s.stage)
  const scene = useScenarioStore((s) => s.scene)
  const tones = useShellStore((s) => s.stageTones)
  const openResetDialog = useShellStore((s) => s.openResetDialog)
  const target = resetStageFor(stage)
  const jobRunning = runningStages(tones).size > 0
  const enabled = scene !== null && resettable(stage) && !jobRunning
  return (
    <div className="border-t border-rock-700 px-4 py-3">
      <button
        type="button"
        disabled={!enabled}
        onClick={() => openResetDialog({ kind: 'STAGE', stage })}
        data-testid="reset-from-here"
        className="plate w-full rounded-sm border border-rock-600 px-3 py-1.5 text-[12px] text-chalk-dim hover:border-danger hover:text-danger disabled:cursor-not-allowed disabled:opacity-40"
        title={
          enabled
            ? `Delete the ${STAGE_LABEL[stage]} result and everything derived from it`
            : jobRunning && scene !== null && resettable(stage)
              ? 'A job is running — Reset waits until it finishes'
              : target === 'WORLD'
                ? 'Setup is the scenario document: regenerate the world or create a new mine instead'
                : 'This stage owns no design artifact'
        }
      >
        Reset from {STAGE_LABEL[stage]}…
      </button>
    </div>
  )
}
