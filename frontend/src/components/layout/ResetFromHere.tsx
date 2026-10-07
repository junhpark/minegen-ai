import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { api, ApiError } from '@/api/client'
import { runningStages, useShellStore } from '@/components/layout/shellStore'
import { resettable, resetStageFor, STAGE_LABEL } from '@/components/layout/workflow'
import { DialogButton, ModalDialog } from '@/components/ui/ModalDialog'
import { clearDeletedArtifacts } from '@/scene/artifactSlots'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useViewerStore } from '@/stores/viewerStore'
import type { ResetPlan } from '@/types/scene'

/**
 * Hardening H1 §4.4 — "Reset from here" for the current stage.
 *
 * The backend artifact registry is the ONLY authority: the button asks
 * `GET …/design/reset-plan?from=<stage>` and shows `willDelete` verbatim; on
 * confirm `DELETE …/design/stages/<stage>` removes the same closure and the
 * response's `deleted[]` empties the scene slots (file → slot mapping, no
 * frontend dependency graph), then the scene manifest is re-read so the
 * ramp-source summary reflects the backend. Nothing here decides what
 * depends on what.
 *
 * PR #53 review B2 — a reset never races a job: the button is disabled while
 * any mounted card reports a running job (the backend refuses the same case
 * with 409 RESET_JOB_RUNNING, shown verbatim when it is a job this view does
 * not know about), and the delete carries the previewed list the user
 * confirmed — a 409 RESET_PLAN_CHANGED (the mine changed since the preview)
 * deletes nothing; the plan is re-read and shown again for a fresh
 * confirmation.
 */
export function ResetFromHere() {
  const stage = useViewerStore((s) => s.stage)
  const scene = useScenarioStore((s) => s.scene)
  const applyScene = useScenarioStore((s) => s.applyScene)
  const setScene = useScenarioStore((s) => s.setScene)
  const epoch = useScenarioStore((s) => s.epoch)
  const tones = useShellStore((s) => s.stageTones)
  const [plan, setPlan] = useState<ResetPlan | null>(null)
  const [planChanged, setPlanChanged] = useState(false)
  const target = resetStageFor(stage)
  const jobRunning = runningStages(tones).size > 0
  const enabled = scene !== null && resettable(stage) && !jobRunning

  const preview = useMutation({
    mutationFn: async () => {
      if (!scene || !target) throw new Error('nothing to reset')
      return api.getResetPlan(scene.scenarioId, target)
    },
    onSuccess: setPlan,
  })
  const reset = useMutation({
    mutationFn: async (confirmed: readonly string[]) => {
      if (!scene || !target) throw new Error('nothing to reset')
      const started = epoch
      const result = await api.resetStage(scene.scenarioId, target, confirmed)
      applyScene(started, (current) => clearDeletedArtifacts(current, result.deleted))
      // the backend summary (ramp source, availability) is re-read, never inferred
      const fresh = await api.getScene(scene.scenarioId)
      setScene(fresh, started)
      return result
    },
    onSuccess: () => {
      setPlan(null)
      setPlanChanged(false)
    },
    onError: (e) => {
      if (e instanceof ApiError && e.code === 'RESET_PLAN_CHANGED') {
        // nothing was deleted; the current plan is read again and confirmed again
        setPlanChanged(true)
        preview.mutate()
      }
    },
  })
  const resetError =
    reset.error instanceof ApiError && reset.error.code === 'RESET_PLAN_CHANGED'
      ? null
      : reset.error
  const err = preview.error ?? resetError
  const errorText =
    err instanceof ApiError ? `${err.code}: ${err.message}` : err ? err.message : null

  return (
    <div className="border-t border-rock-700 px-4 py-3">
      <button
        type="button"
        disabled={!enabled || preview.isPending || reset.isPending}
        onClick={() => {
          setPlanChanged(false)
          preview.mutate()
        }}
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
        {preview.isPending ? 'Reading reset plan…' : `Reset from ${STAGE_LABEL[stage]}…`}
      </button>
      {errorText && !plan ? (
        <p role="alert" className="mt-2 text-[11px] text-danger">
          {errorText}
        </p>
      ) : null}
      {plan ? (
        <ModalDialog
          title={`Reset from ${STAGE_LABEL[stage]}`}
          onClose={() => setPlan(null)}
          footer={
            <>
              <DialogButton kind="cancel" onClick={() => setPlan(null)}>
                Cancel
              </DialogButton>
              <DialogButton
                kind="danger"
                disabled={!plan.present || reset.isPending || preview.isPending}
                onClick={() => reset.mutate(plan.willDelete)}
              >
                {reset.isPending
                  ? 'Deleting…'
                  : preview.isPending
                    ? 'Re-reading plan…'
                    : `Delete ${String(plan.willDelete.length)} file${plan.willDelete.length === 1 ? '' : 's'}`}
              </DialogButton>
            </>
          }
        >
          {planChanged ? (
            <p role="status" className="mb-2 text-warn" data-testid="reset-plan-changed">
              The mine changed since this plan was read — nothing was deleted. The list below is the
              current plan; confirm it again.
            </p>
          ) : null}
          {plan.present ? (
            <>
              <p className="mb-2">
                The backend will delete these derived files (the stage's own artifacts and
                everything that depends on them). Regenerate from this stage afterwards.
              </p>
              <ul className="readout list-disc pl-4 text-[11px]" data-testid="reset-will-delete">
                {plan.willDelete.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
            </>
          ) : (
            <p>Nothing to reset — this stage has no generated result yet.</p>
          )}
          {errorText ? (
            <p role="alert" className="mt-2 text-[11px] text-danger">
              {errorText}
            </p>
          ) : null}
        </ModalDialog>
      ) : null}
    </div>
  )
}
