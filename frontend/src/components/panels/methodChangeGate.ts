/**
 * Hardening H1 §4.3 (review B2, round 2 B1) — when "Apply method" may be
 * pressed.
 *
 * A mine WITH a world is reset by the method change (rule 40), so the user
 * must have SEEN the backend reset plan first: the button is enabled only
 * once THIS dialog's read of the plan completed — `isSuccess` alone is not
 * enough, because a cached answer is `isSuccess` while a background refetch
 * is still in flight, so `isFetching` must be false as well (the dialog also
 * keys its query per opening and caches nothing, so no earlier read can
 * satisfy it). While it loads, refetches or after it failed the button stays
 * disabled (the dialog offers Retry / Cancel). A scenario without a world
 * clears nothing, so it applies at once. Pure — the dialog is the only
 * caller.
 */
export function methodChangeApplyEnabled(
  hasWorld: boolean,
  plan: { isSuccess: boolean; isError: boolean; isFetching: boolean },
): boolean {
  if (!hasWorld) return true
  return plan.isSuccess && !plan.isError && !plan.isFetching
}
