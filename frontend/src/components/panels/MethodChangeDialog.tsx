import type { MiningConfig } from '@/types/api'
import { ScenarioChangeDialog } from './ScenarioChangeDialog'

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
 * that already has a world: the shared `ScenarioChangeDialog` (one
 * implementation for every scenario-document change, PR-2 H2-SH) with the
 * method wording. Applying is a scenario PUT (rule 40) followed by world
 * regeneration from the same seed; the dialog lists the backend reset plan
 * verbatim and decides nothing itself.
 */
export function MethodChangeDialog({
  scenarioId,
  mining,
  attempt,
  hasWorld,
  onCancel,
  onConfirm,
}: Props) {
  return (
    <ScenarioChangeDialog
      scenarioId={scenarioId}
      pending={mining}
      attempt={attempt}
      hasWorld={hasWorld}
      title="Change mining method"
      intro="The world is regenerated with the same seed; everything from Layout on is reset."
      confirmLabel="Apply method"
      listTestId="method-will-delete"
      onCancel={onCancel}
      onConfirm={onConfirm}
    />
  )
}
