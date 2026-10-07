import { useQuery } from '@tanstack/react-query'
import { api, ApiError } from '@/api/client'
import { DialogButton, ModalDialog } from '@/components/ui/ModalDialog'
import type { MiningConfig } from '@/types/api'
import { methodChangeApplyEnabled } from './methodChangeGate'

interface Props {
  scenarioId: string
  /** the edited MiningConfig awaiting confirmation (null = closed) */
  mining: MiningConfig | null
  /** counts the openings of the dialog: every opening reads the reset plan
   * afresh (review round 2 B1 — a cached plan never enables Apply) */
  attempt: number
  /** true when the scenario has a generated world (the only case that resets) */
  hasWorld: boolean
  onCancel: () => void
  onConfirm: (mining: MiningConfig) => void
}

/**
 * Hardening H1 §4.3 — confirmation before a mining-method change on a mine
 * that already has a world. Applying is a scenario PUT (rule 40: the backend
 * invalidates EVERY derived artifact) followed by world regeneration from
 * the same seed; this dialog lists the backend's `reset-plan?from=WORLD`
 * answer verbatim so the user sees exactly what will be cleared. It decides
 * nothing itself.
 *
 * Review round 2 B1: the plan is read ONCE PER OPENING — the query key
 * carries the opening's `attempt`, nothing is kept in the cache after the
 * dialog closes (`gcTime: 0`) and nothing is reused (`staleTime: 0`) — and
 * Apply is enabled only when that read completed and no fetch is in flight.
 */
export function MethodChangeDialog({
  scenarioId,
  mining,
  attempt,
  hasWorld,
  onCancel,
  onConfirm,
}: Props) {
  const plan = useQuery({
    queryKey: ['reset-plan', scenarioId, 'WORLD', attempt],
    queryFn: () => api.getResetPlan(scenarioId, 'WORLD'),
    enabled: mining !== null && hasWorld,
    retry: false,
    staleTime: 0,
    gcTime: 0,
  })
  if (mining === null) return null
  const err = plan.error
  const errorText =
    err instanceof ApiError ? `${err.code}: ${err.message}` : err ? err.message : null
  const canApply = methodChangeApplyEnabled(hasWorld, {
    isSuccess: plan.isSuccess,
    isError: plan.isError,
    isFetching: plan.isFetching,
  })
  const reading = hasWorld && (plan.isFetching || (!plan.isSuccess && !plan.isError))
  return (
    <ModalDialog
      title="Change mining method"
      onClose={onCancel}
      footer={
        <>
          <DialogButton kind="cancel" onClick={onCancel}>
            Cancel
          </DialogButton>
          {hasWorld && plan.isError && !plan.isFetching ? (
            <DialogButton kind="confirm" onClick={() => void plan.refetch()}>
              Retry
            </DialogButton>
          ) : null}
          <DialogButton
            kind="confirm"
            disabled={!canApply}
            onClick={() => {
              if (canApply) onConfirm(mining)
            }}
          >
            {reading ? 'Reading reset plan…' : 'Apply method'}
          </DialogButton>
        </>
      }
    >
      <p className="mb-2">
        The world is regenerated with the same seed; everything from Layout on is reset.
      </p>
      {hasWorld ? (
        plan.isSuccess && !plan.isFetching ? (
          plan.data.willDelete.length > 0 ? (
            <ul className="readout list-disc pl-4 text-[11px]" data-testid="method-will-delete">
              {plan.data.willDelete.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          ) : (
            <p className="text-mute">No design artifact exists yet, so nothing else is cleared.</p>
          )
        ) : errorText ? (
          <p role="alert" className="text-danger">
            The reset plan could not be read — nothing is applied until it is: {errorText}
          </p>
        ) : (
          <p className="text-mute">Reading the reset plan…</p>
        )
      ) : (
        <p className="text-mute">No world is generated yet, so nothing is cleared.</p>
      )}
    </ModalDialog>
  )
}
