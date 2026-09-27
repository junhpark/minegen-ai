/**
 * Phase 20E — presentation mappings shared by the panel primitives.
 *
 * These turn backend artifact state into DISPLAY state. They introduce no new
 * status vocabulary, rewrite no backend enum and never decide whether an
 * action is enabled.
 */

export type StatusTone = 'READY' | 'RUNNING' | 'FAILED' | 'NOT_GENERATED' | 'ACTIVE' | 'INACTIVE'

/**
 * Presentation mapping from a backend artifact report to a badge tone.
 * `SUCCESS` reads Ready, anything else present reads Failed (exactly the
 * pre-20E per-feature colouring), an absent artifact reads Not generated and
 * a running job wins over both.
 */
export function artifactTone(
  artifact: { status: string } | null | undefined,
  running = false,
): StatusTone {
  if (running) return 'RUNNING'
  if (artifact == null) return 'NOT_GENERATED'
  return artifact.status === 'SUCCESS' ? 'READY' : 'FAILED'
}

export type ActionVariant = 'primary' | 'secondary'

/**
 * Phase 20E §14 — the variant of a workflow action.
 *
 * `primary` marks the next key action: a feature that has no result yet and
 * whose prerequisites are satisfied. Everything else (a regeneration of an
 * existing result, or an action still waiting on its prerequisite) is
 * `secondary`, so at most the actionable next steps carry the accent colour.
 * This decides STYLE only — never whether the button is enabled.
 */
export function nextActionVariant(hasResult: boolean, enabled: boolean): ActionVariant {
  return !hasResult && enabled ? 'primary' : 'secondary'
}
