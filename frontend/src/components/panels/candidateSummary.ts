import type { LayoutCandidateSummary, LayoutV2Catalogue, RampSourceSummary } from '@/types/scene'

/**
 * Hardening PR-3 round 2 — what an OPTION row says, and what its detail
 * says (pure, tested as data). Every value is a backend field of the
 * catalogue; nothing is computed here beyond formatting.
 *
 *   Option 1  SPIRAL  ★ best  active                               5.201
 *   13/13 accessible · ramp 3,954 m · access 495 m
 *
 * The scores by group, the geometry diagnostics, the clearance and the
 * failure reasons live in the detail (hover, or the expanded picked row);
 * the candidate id stays in the card's Search details (rule 191).
 */

const metres = (v: number): string => `${Math.round(v).toLocaleString('en-US')} m`

/** "Option 1" for a ranked candidate, the id tail for an unranked one */
export function optionLabel(c: LayoutCandidateSummary): string {
  return c.rank !== null ? `Option ${String(c.rank)}` : c.candidateId.slice(c.family.length + 1)
}

/** the row's right-hand value: the total score, or the typed status */
export function optionValue(c: LayoutCandidateSummary): { text: string; feasible: boolean } {
  if (c.status !== 'FEASIBLE') return { text: c.status, feasible: false }
  return { text: c.scores ? c.scores.total.toFixed(3) : '—', feasible: true }
}

/** the one summary line under the option title */
export function optionSummaryLine(c: LayoutCandidateSummary): string {
  const parts: string[] = [
    c.accessibleLevels !== null
      ? `${String(c.accessibleLevels)}/${String(c.requiredLevels)} accessible`
      : `${String(c.screenedLevels)}/${String(c.requiredLevels)} screened`,
  ]
  if (c.diagnostics) parts.push(`ramp ${metres(c.diagnostics.length3d)}`)
  if (c.access) parts.push(`access ${metres(c.access.totalAccessLength)}`)
  return parts.join(' · ')
}

export interface BriefRow {
  label: string
  value: string
  tone?: 'danger'
}

/** the detail rows of an option (hover panel / expanded row) */
export function optionBriefRows(c: LayoutCandidateSummary): BriefRow[] {
  const rows: BriefRow[] = []
  if (c.scores) {
    rows.push({ label: 'Score', value: c.scores.total.toFixed(3) })
    rows.push({
      label: 'By group',
      value: `D ${c.scores.development.toFixed(2)} · G ${c.scores.geology.toFixed(2)} · M ${c.scores.geometry.toFixed(2)}`,
    })
  }
  rows.push({
    label: 'Levels',
    value:
      c.accessibleLevels !== null
        ? `${String(c.accessibleLevels)} of ${String(c.requiredLevels)} accessible`
        : `${String(c.screenedLevels)} of ${String(c.requiredLevels)} pass the screen`,
  })
  const d = c.diagnostics
  if (d) {
    rows.push({
      label: 'Ramp',
      value: `${metres(d.length3d)} · ${String(d.headingReversalCount)} hairpins`,
    })
    rows.push({
      label: 'Geometry',
      value: `grade ≤ ${d.maxAbsGradient.toFixed(3)} · R ≥ ${
        d.minPlanRadius === null ? '—' : `${d.minPlanRadius.toFixed(1)} m`
      }`,
    })
  }
  if (c.access) {
    rows.push({
      label: 'Access',
      value: `${metres(c.access.totalAccessLength)} · worst ${metres(c.access.worstAccessLength)} · g ≤ ${c.access.maxAccessGradient.toFixed(3)}`,
    })
  }
  if (c.clearance) {
    rows.push({
      label: 'Clearance',
      value: `${c.clearance.conservativeMinimumClearance.toFixed(1)} m ≥ ${c.clearance.requiredClearance.toFixed(1)} m (${c.clearance.clearanceBasis})`,
    })
  }
  if (c.status !== 'FEASIBLE' && c.failureReasons.length > 0) {
    rows.push({ label: 'Why not', value: c.failureReasons.join(', '), tone: 'danger' })
  }
  if (c.failureDetail) rows.push({ label: 'Detail', value: c.failureDetail, tone: 'danger' })
  return rows
}

/** the "Current design" readout of the Mine layout card */
export function currentDesignLabel(
  catalogue: LayoutV2Catalogue | null,
  rampSource: RampSourceSummary | null,
): string {
  const active = rampSource?.activeSource ?? 'LEGACY'
  const available = rampSource?.available ?? false
  if (active === 'LAYOUT_V2' && available) {
    const id = rampSource?.candidateId ?? null
    const c = id ? catalogue?.candidates.find((x) => x.candidateId === id) : undefined
    if (c) return `${optionLabel(c)} · ${c.family} (active)`
    return `Layout v2 · ${id ?? '—'} (active)`
  }
  if (active === 'LEGACY' && available) return 'Legacy decline (Hybrid-A*) — advanced'
  return 'none yet'
}
