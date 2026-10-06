/**
 * Hardening H1 §4.3 (review B2) — when "Apply method" may be pressed.
 *
 * A mine WITH a world is reset by the method change (rule 40), so the user
 * must have SEEN the backend reset plan first: the button is enabled only
 * once that read succeeded; while it loads or after it failed it stays
 * disabled (the dialog offers Retry / Cancel). A scenario without a world
 * clears nothing, so it applies at once. Pure — the dialog is the only
 * caller.
 */
export function methodChangeApplyEnabled(
  hasWorld: boolean,
  plan: { isSuccess: boolean; isError: boolean },
): boolean {
  if (!hasWorld) return true
  return plan.isSuccess && !plan.isError
}
