import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { api, ApiError } from '@/api/client'
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
 */
export function ResetFromHere() {
  const stage = useViewerStore((s) => s.stage)
  const scene = useScenarioStore((s) => s.scene)
  const applyScene = useScenarioStore((s) => s.applyScene)
  const setScene = useScenarioStore((s) => s.setScene)
  const epoch = useScenarioStore((s) => s.epoch)
  const [plan, setPlan] = useState<ResetPlan | null>(null)
  const target = resetStageFor(stage)
  const enabled = scene !== null && resettable(stage)

  const preview = useMutation({
    mutationFn: async () => {
      if (!scene || !target) throw new Error('nothing to reset')
      return api.getResetPlan(scene.scenarioId, target)
    },
    onSuccess: setPlan,
  })
  const reset = useMutation({
    mutationFn: async () => {
      if (!scene || !target) throw new Error('nothing to reset')
      const started = epoch
      const result = await api.resetStage(scene.scenarioId, target)
      applyScene(started, (current) => clearDeletedArtifacts(current, result.deleted))
      // the backend summary (ramp source, availability) is re-read, never inferred
      const fresh = await api.getScene(scene.scenarioId)
      setScene(fresh, started)
      return result
    },
    onSuccess: () => setPlan(null),
  })
  const err = preview.error ?? reset.error
  const errorText =
    err instanceof ApiError ? `${err.code}: ${err.message}` : err ? err.message : null

  return (
    <div className="border-t border-rock-700 px-4 py-3">
      <button
        type="button"
        disabled={!enabled || preview.isPending || reset.isPending}
        onClick={() => preview.mutate()}
        data-testid="reset-from-here"
        className="plate w-full rounded-sm border border-rock-600 px-3 py-1.5 text-[12px] text-chalk-dim hover:border-danger hover:text-danger disabled:cursor-not-allowed disabled:opacity-40"
        title={
          enabled
            ? `Delete the ${STAGE_LABEL[stage]} result and everything derived from it`
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
                disabled={!plan.present || reset.isPending}
                onClick={() => reset.mutate()}
              >
                {reset.isPending
                  ? 'Deleting…'
                  : `Delete ${String(plan.willDelete.length)} file${plan.willDelete.length === 1 ? '' : 's'}`}
              </DialogButton>
            </>
          }
        >
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
