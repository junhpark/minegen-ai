import type { LayoutCandidateSummary } from '@/types/scene'

const FAMILY_ORDER = ['SPIRAL', 'LONGITUDINAL', 'SWITCHBACK'] as const

/** Deterministic display order: ranked feasible first (by rank), then the
 * rest by family order and id — never re-scored on the client. */
export function compareCandidates(a: LayoutCandidateSummary, b: LayoutCandidateSummary): number {
  const ra = a.rank ?? Number.POSITIVE_INFINITY
  const rb = b.rank ?? Number.POSITIVE_INFINITY
  if (ra !== rb) return ra - rb
  const fa = FAMILY_ORDER.indexOf(a.family)
  const fb = FAMILY_ORDER.indexOf(b.family)
  if (fa !== fb) return fa - fb
  return a.candidateId < b.candidateId ? -1 : a.candidateId > b.candidateId ? 1 : 0
}
