import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, ApiError } from '@/api/client'
import { methodChangeApplyEnabled } from '@/components/panels/methodChangeGate'
import { DialogButton, ModalDialog } from '@/components/ui/ModalDialog'
import { clearDeletedArtifacts } from '@/scene/artifactSlots'
import { loadScene } from '@/scenario/openScenario'
import { scenarioEpoch } from '@/stores/scenarioSession'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useViewerStore } from '@/stores/viewerStore'
import type { StageId } from '@/types/workflow'
import { useShellStore } from './shellStore'
import { resetStageFor, STAGE_LABEL } from './workflow'
import { tr } from '@/i18n/t'

/**
 * Hardening PR-3 — the ONE host of the two reset confirmations, mounted once
 * in `App` and opened by a request in the shell store (ribbon quick access,
 * flow dock, the controls column's "Reset from here"). Both dialogs are
 * driven by the backend plan and decide nothing themselves:
 *
 * - "Reset from <stage>" (hardening H1 §4.4 / PR #53 review B2): the plan is
 *   read on opening (`GET …/design/reset-plan?from=<stage>`), `willDelete`
 *   is listed verbatim, the confirmed list travels with the delete
 *   (`DELETE …/design/stages/<stage>`), the response's `deleted[]` empties
 *   the scene slots and the scene manifest is re-read; a 409
 *   RESET_PLAN_CHANGED deletes nothing and re-reads the plan for a fresh
 *   confirmation.
 * - "Reset mine" (PR-3): the way back to the generated world. The from=WORLD
 *   plan is read per opening (every derived artifact, rules 40 / 46) and
 *   confirming regenerates the world from the persisted document — same
 *   seed, same world (rule 119); the scenario document is untouched. The
 *   shell then opens the Layout stage, the first thing to decide again.
 *
 * Both plans are QUERIES keyed by the opening's nonce (review round 2 B1:
 * nothing cached, nothing reused across openings, the confirm button enabled
 * only once THIS read completed with no fetch in flight). A mutation started
 * in a mount effect is deliberately avoided: under React StrictMode's
 * simulated unmount / remount the mutation observer is detached from its
 * mutation and `isPending` never clears.
 */
export function ResetDialogs() {
  const request = useShellStore((s) => s.resetDialog)
  if (!request) return null
  return request.kind === 'STAGE' ? (
    <ResetStageDialog key={request.nonce} stage={request.stage} nonce={request.nonce} />
  ) : (
    <ResetMineDialog key={request.nonce} nonce={request.nonce} />
  )
}

const errorTextOf = (err: unknown): string | null =>
  err instanceof ApiError
    ? `${err.code}: ${err.message}`
    : err instanceof Error
      ? err.message
      : null

function ResetStageDialog({ stage, nonce }: { stage: StageId; nonce: number }) {
  const scene = useScenarioStore((s) => s.scene)
  const applyScene = useScenarioStore((s) => s.applyScene)
  const setScene = useScenarioStore((s) => s.setScene)
  const epoch = useScenarioStore((s) => s.epoch)
  const close = useShellStore((s) => s.closeResetDialog)
  const [planChanged, setPlanChanged] = useState(false)
  const target = resetStageFor(stage)
  const scenarioId = scene?.scenarioId ?? null

  const plan = useQuery({
    queryKey: ['reset-plan', scenarioId, target, 'reset-from-here', nonce],
    queryFn: () => {
      if (!scenarioId || !target) throw new Error('nothing to reset')
      return api.getResetPlan(scenarioId, target)
    },
    enabled: scenarioId !== null && target !== null,
    retry: false,
    staleTime: 0,
    gcTime: 0,
  })
  const reset = useMutation({
    mutationFn: async (confirmed: readonly string[]) => {
      if (!scenarioId || !target) throw new Error('nothing to reset')
      const started = epoch
      const result = await api.resetStage(scenarioId, target, confirmed)
      applyScene(started, (current) => clearDeletedArtifacts(current, result.deleted))
      // the backend summary (ramp source, availability) is re-read, never inferred
      const fresh = await api.getScene(scenarioId)
      setScene(fresh, started)
      return result
    },
    onSuccess: () => close(),
    onError: (e) => {
      if (e instanceof ApiError && e.code === 'RESET_PLAN_CHANGED') {
        // nothing was deleted; the current plan is read again and confirmed again
        setPlanChanged(true)
        void plan.refetch()
      }
    },
  })

  const resetError =
    reset.error instanceof ApiError && reset.error.code === 'RESET_PLAN_CHANGED'
      ? null
      : reset.error
  const errorText = errorTextOf(plan.error ?? resetError)
  const reading = plan.isFetching || (!plan.isSuccess && !plan.isError)
  const current = plan.isSuccess && !plan.isFetching ? plan.data : null
  return (
    <ModalDialog
      title={tr('Reset from {stage}', { stage: tr(STAGE_LABEL[stage]) })}
      onClose={close}
      footer={
        <>
          <DialogButton kind="cancel" onClick={close}>
            Cancel
          </DialogButton>
          {plan.isError && !plan.isFetching ? (
            <DialogButton kind="confirm" onClick={() => void plan.refetch()}>
              Retry
            </DialogButton>
          ) : null}
          <DialogButton
            kind="danger"
            disabled={!current?.present || reset.isPending}
            onClick={() => {
              if (current?.present) reset.mutate(current.willDelete)
            }}
          >
            {reset.isPending
              ? tr('Deleting…')
              : reading
                ? tr('Reading plan…')
                : current
                  ? tr(current.willDelete.length === 1 ? 'Delete {n} file' : 'Delete {n} files', {
                      n: current.willDelete.length,
                    })
                  : tr('Delete')}
          </DialogButton>
        </>
      }
    >
      {planChanged ? (
        <p role="status" className="mb-2 text-warn" data-testid="reset-plan-changed">
          {tr(
            'The mine changed since this plan was read — nothing was deleted. The list below is the current plan; confirm it again.',
          )}
        </p>
      ) : null}
      {current ? (
        current.present ? (
          <>
            <p className="mb-2">
              {tr(
                "The backend will delete these derived files (the stage's own artifacts and everything that depends on them). Regenerate from this stage afterwards.",
              )}
            </p>
            <ul className="readout list-disc pl-4 text-[11px]" data-testid="reset-will-delete">
              {current.willDelete.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          </>
        ) : (
          <p>{tr('Nothing to reset — this stage has no generated result yet.')}</p>
        )
      ) : reading ? (
        <p className="text-mute">{tr('Reading the reset plan…')}</p>
      ) : null}
      {errorText ? (
        <p role="alert" className="mt-2 text-[11px] text-danger">
          {errorText}
        </p>
      ) : null}
    </ModalDialog>
  )
}

function ResetMineDialog({ nonce }: { nonce: number }) {
  const scene = useScenarioStore((s) => s.scene)
  const close = useShellStore((s) => s.closeResetDialog)
  const setStage = useViewerStore((s) => s.setStage)
  const scenarioId = scene?.scenarioId ?? null
  const plan = useQuery({
    queryKey: ['reset-plan', scenarioId, 'WORLD', 'reset-mine', nonce],
    queryFn: () => {
      if (!scenarioId) throw new Error('no world to reset')
      return api.getResetPlan(scenarioId, 'WORLD')
    },
    enabled: scenarioId !== null,
    retry: false,
    staleTime: 0,
    gcTime: 0,
  })
  const regenerate = useMutation({
    mutationFn: async () => {
      if (!scenarioId) throw new Error('no world to reset')
      const epoch = scenarioEpoch()
      // rule 46: regenerating the world clears derived/ first; rule 119: the
      // persisted document reproduces its world exactly
      await api.generateWorld(scenarioId)
      await loadScene(scenarioId, epoch)
    },
    onSuccess: () => {
      close()
      setStage('LAYOUT')
    },
  })
  const canApply =
    methodChangeApplyEnabled(true, {
      isSuccess: plan.isSuccess,
      isError: plan.isError,
      isFetching: plan.isFetching,
    }) && !regenerate.isPending
  const reading = plan.isFetching || (!plan.isSuccess && !plan.isError)
  const errorText = errorTextOf(plan.error ?? regenerate.error)
  return (
    <ModalDialog
      title="Reset mine"
      onClose={close}
      footer={
        <>
          <DialogButton kind="cancel" onClick={close}>
            Cancel
          </DialogButton>
          {plan.isError && !plan.isFetching ? (
            <DialogButton kind="confirm" onClick={() => void plan.refetch()}>
              Retry
            </DialogButton>
          ) : null}
          <DialogButton
            kind="danger"
            disabled={!canApply}
            onClick={() => {
              if (canApply) regenerate.mutate()
            }}
          >
            {regenerate.isPending
              ? tr('Regenerating world…')
              : reading
                ? tr('Reading reset plan…')
                : tr('Clear design & regenerate world')}
          </DialogButton>
        </>
      }
    >
      <p className="mb-2">
        {tr(
          'Back to the generated world: the scenario document is kept and its world is regenerated from the same seed, which clears every design artifact. The backend will delete:',
        )}
      </p>
      {plan.isSuccess && !plan.isFetching ? (
        plan.data.willDelete.length > 0 ? (
          <ul className="readout list-disc pl-4 text-[11px]" data-testid="reset-mine-will-delete">
            {plan.data.willDelete.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        ) : (
          <p className="text-mute" data-testid="reset-mine-will-delete">
            {tr('No design artifact exists yet — only the world is regenerated.')}
          </p>
        )
      ) : errorText && !regenerate.error ? (
        <p role="alert" className="text-danger">
          {tr('The reset plan could not be read — nothing is applied until it is: {error}', {
            error: errorText,
          })}
        </p>
      ) : (
        <p className="text-mute">{tr('Reading the reset plan…')}</p>
      )}
      {regenerate.error ? (
        <p role="alert" className="mt-2 text-[11px] text-danger">
          {errorTextOf(regenerate.error)}
        </p>
      ) : null}
    </ModalDialog>
  )
}
