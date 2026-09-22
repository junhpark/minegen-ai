import type {
  AssessmentCheck,
  CandidateComparisonRow,
  DesignAssessmentPayload,
} from '@/types/scene'

/**
 * Phase 20D.3 — design assessment + candidate comparison (rule 189).
 *
 * Pure presentation of the backend read model (GET …/design/assessment).
 * Every number, status, rank, ordering and authority in this markup is a
 * backend field: no client-side check, score, delta, re-sorting or
 * inference. Hard design rules, derived validations, advisories and
 * informational facts carry DIFFERENT marks and labels so a satisfied
 * advisory is never read as a certification badge (directive §19).
 */

const AUTHORITY_LABEL: Record<AssessmentCheck['authority'], string> = {
  HARD_DESIGN_RULE: 'hard rule',
  DERIVED_VALIDATION: 'validation',
  ADVISORY: 'advisory',
  INFORMATIONAL: 'info',
}

/** the status mark: hard rules / validations use ✓ / ✗, an advisory always
 * uses "!" (a satisfied advisory is still an advisory), info uses "i", and
 * anything not evaluated / not applicable uses "?" — never a check mark */
function mark(c: AssessmentCheck): { glyph: string; className: string } {
  if (c.status === 'NOT_EVALUATED' || c.status === 'NOT_APPLICABLE') {
    return { glyph: '?', className: 'text-mute' }
  }
  if (c.authority === 'ADVISORY') {
    return { glyph: '!', className: c.status === 'SATISFIED' ? 'text-chalk' : 'text-danger' }
  }
  if (c.authority === 'INFORMATIONAL') return { glyph: 'i', className: 'text-chalk-dim' }
  return c.status === 'SATISFIED'
    ? { glyph: '✓', className: 'text-lamp' }
    : { glyph: '✗', className: 'text-danger' }
}

function statusLabel(c: AssessmentCheck): string {
  switch (c.status) {
    case 'SATISFIED':
      return c.authority === 'ADVISORY' ? 'criterion met (advisory)' : 'satisfied'
    case 'NOT_SATISFIED':
      return c.authority === 'ADVISORY' ? 'criterion not met (advisory)' : 'not satisfied'
    case 'NOT_APPLICABLE':
      return 'NOT APPLICABLE'
    case 'NOT_EVALUATED':
      return 'NOT EVALUATED'
  }
}

/** the compact right-hand readout of a check, from its evidence only */
function readout(c: AssessmentCheck): string {
  const e = c.evidence
  if (c.status === 'NOT_EVALUATED' || c.status === 'NOT_APPLICABLE') return statusLabel(c)
  switch (c.id) {
    case 'DUAL_EGRESS_ADVISORY':
      return `${String(e.meetingNodeCount)}/${String(e.undergroundNodeCount)} nodes · ${String(e.requiredRoutes)} routes`
    case 'REQUIRED_CAPABILITY_PATHS':
      return `${String(e.satisfiedPathCount)}/${String(e.requiredPathCount)} paths`
    case 'ALL_REQUIRED_LEVELS_ACCESSIBLE':
      return `${String(e.accessibleLevels)}/${String(e.requiredLevels)} levels`
    case 'CLEARANCE_VALIDATED':
      return typeof e.conservativeMinimumClearance === 'number' &&
        typeof e.requiredClearance === 'number'
        ? `${e.conservativeMinimumClearance.toFixed(1)} m ≥ ${e.requiredClearance.toFixed(1)} m (${String(e.clearanceBasis)})`
        : statusLabel(c)
    case 'GEOMETRY_VALIDATED':
      return `${String(e.invalidSampleCount)} invalid / ${String(e.sampleCount)} samples`
    case 'CANDIDATE_FEASIBLE':
      return String(e.status)
    case 'SELECTED_IS_RANKING_WINNER':
      return e.selectedRank == null ? statusLabel(c) : `rank ${String(e.selectedRank)}`
    case 'ACTIVE_RAMP_SOURCE':
      return String(e.activeSource)
    case 'LAYOUT_SELECTED':
      return typeof e.candidateId === 'string' ? e.candidateId : statusLabel(c)
    default:
      return statusLabel(c)
  }
}

export function DesignAssessmentList({ assessment }: { assessment: DesignAssessmentPayload }) {
  return (
    <div className="readout mt-2 text-[11px]" aria-label="design assessment">
      <div className="flex justify-between text-chalk-dim">
        <span>DESIGN ASSESSMENT</span>
        <span className="text-mute">read-only projection · no statutory claim</span>
      </div>
      <div className="mt-0.5 text-mute" aria-label="assessment scope">
        {assessment.activeSource === 'LAYOUT_V2'
          ? `active design: Layout v2 · ${assessment.activeDesignCandidateId ?? '—'}`
          : assessment.layoutScope === 'INACTIVE_LAYOUT_V2'
            ? 'active design: LEGACY (Hybrid-A*) · layout-v2 checks describe the INACTIVE layout-v2 selection'
            : 'active design: LEGACY (Hybrid-A*) · no layout-v2 catalogue'}
      </div>
      <ul className="mt-1">
        {assessment.checks.map((c) => {
          const m = mark(c)
          return (
            <li
              key={c.id}
              className="py-0.5"
              data-check-id={c.id}
              data-authority={c.authority}
              data-status={c.status}
              data-scope={c.scope}
              aria-label={`${c.title}: ${statusLabel(c)} (${AUTHORITY_LABEL[c.authority]})`}
            >
              <div className="flex items-start gap-1">
                <span className={`w-3 shrink-0 text-center ${m.className}`} aria-hidden="true">
                  {m.glyph}
                </span>
                <span
                  className={`flex-1 ${c.authority === 'ADVISORY' ? 'italic text-chalk-dim' : ''}`}
                >
                  {c.title}
                  {c.scope === 'INACTIVE_LAYOUT_V2' && c.status !== 'NOT_APPLICABLE' ? (
                    <span className="text-mute"> (inactive)</span>
                  ) : null}
                </span>
                <span
                  className={`shrink-0 whitespace-nowrap rounded-sm border px-1 text-[9px] uppercase ${
                    c.authority === 'ADVISORY'
                      ? 'border-dashed border-chalk-dim text-chalk-dim'
                      : c.authority === 'INFORMATIONAL'
                        ? 'border-rock-700 text-mute'
                        : 'border-rock-700 text-chalk-dim'
                  }`}
                >
                  {AUTHORITY_LABEL[c.authority]}
                </span>
              </div>
              <div className={`pl-4 text-right ${m.className}`}>{readout(c)}</div>
            </li>
          )
        })}
      </ul>
      {assessment.egressAdvisory ? (
        <div className="mt-1 text-mute" aria-label="dual-egress advisory note">
          Dual-egress design advisory: {assessment.egressAdvisory.meetingNodeCount} /{' '}
          {assessment.egressAdvisory.undergroundNodeCount} underground nodes meet the{' '}
          {assessment.egressAdvisory.requiredRoutes}-route design criterion. This is a design
          advisory, not a statutory compliance determination.
        </div>
      ) : null}
      <pre className="mt-1 whitespace-pre-wrap font-sans text-mute" aria-label="selection summary">
        {assessment.summary}
      </pre>
    </div>
  )
}

function shortId(row: CandidateComparisonRow): string {
  return row.candidateId.slice(row.family.length + 1)
}

function signed(v: number): string {
  return `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(3)}`
}

export function AlternativesTable({ assessment }: { assessment: DesignAssessmentPayload }) {
  // the backend order IS the ranking (rule 148 / directive §10): never
  // re-sorted, never filtered here
  const rows = assessment.candidateComparison
  return (
    <div className="readout mt-2 text-[11px]" aria-label="candidate alternatives">
      <div className="flex justify-between text-chalk-dim">
        <span>
          ALTERNATIVES
          {assessment.layoutScope === 'INACTIVE_LAYOUT_V2' ? (
            <span className="text-mute"> (inactive layout-v2 catalogue)</span>
          ) : null}
        </span>
        <span className="text-mute">{rows.length} rows · ranking order · ● winner</span>
      </div>
      {assessment.layoutScope === 'NONE' ? (
        <div className="mt-1 text-mute">no layout-v2 catalogue</div>
      ) : rows.length === 0 ? (
        <div className="mt-1 text-mute">no feasible candidate</div>
      ) : (
        <table className="mt-1 w-full table-fixed border-collapse whitespace-nowrap text-[10px]">
          <colgroup>
            <col className="w-3" />
            <col />
            <col className="w-12" />
            <col className="w-9" />
            <col className="w-14" />
          </colgroup>
          <thead className="text-mute">
            <tr>
              <th className="text-left font-normal">#</th>
              <th className="truncate text-left font-normal">Candidate · Family</th>
              <th className="text-right font-normal">Score · Δ</th>
              <th className="text-right font-normal">Access</th>
              <th className="text-right font-normal">Status</th>
            </tr>
          </thead>
          <tbody className="align-top">
            {rows.map((r) => (
              <tr
                key={r.candidateId}
                data-candidate-id={r.candidateId}
                data-winner={r.winner ? 'true' : 'false'}
                data-selected={r.selected ? 'true' : 'false'}
                className={r.selected ? 'text-lamp' : r.winner ? 'text-chalk' : 'text-chalk-dim'}
              >
                <td className="pr-1">{r.rank === null ? '—' : String(r.rank)}</td>
                <td className="overflow-hidden pr-1" title={r.candidateId}>
                  <div className="truncate">
                    {r.winner ? '● ' : ''}
                    {shortId(r)}
                    {r.selected ? ' (selected)' : ''}
                  </div>
                  <div className="text-mute">{r.family}</div>
                </td>
                <td className="pr-1 text-right">
                  <div>{r.scores ? r.scores.total.toFixed(3) : '—'}</div>
                  <div className="text-mute">
                    {r.deltas ? signed(r.deltas.totalScoreDeltaFromWinner) : '—'}
                  </div>
                </td>
                <td className="pr-1 text-right">
                  {r.accessibleLevels === null ? '—' : String(r.accessibleLevels)}/
                  {String(r.requiredLevels)}
                </td>
                <td className={`text-right ${r.status === 'FEASIBLE' ? '' : 'text-danger'}`}>
                  {r.status}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="mt-1 text-mute">
        scores and deltas are the backend Layout v2 values (Δ = candidate − winner, plain
        subtraction) · order is the stored ranking
      </div>
    </div>
  )
}
