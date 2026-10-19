import { Fragment, useState } from 'react'
import { HoverDetail } from '@/components/ui/HoverDetail'
import { toggled } from '@/components/ui/interaction'
import type {
  AssessmentCheck,
  CandidateComparisonRow,
  DesignAssessmentPayload,
} from '@/types/scene'
import { tr } from '@/i18n/t'

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

/** the long form, shown in the check's detail only */
const AUTHORITY_LONG: Record<AssessmentCheck['authority'], string> = {
  HARD_DESIGN_RULE: 'Hard design rule',
  DERIVED_VALIDATION: 'Derived validation',
  ADVISORY: 'Design advisory — not a statutory compliance determination',
  INFORMATIONAL: 'Informational',
}

/** the status mark: hard rules / validations use ✓ / ✗, an advisory always
 * uses "!" (a satisfied advisory is still an advisory), info uses "i", and
 * anything not evaluated / not applicable uses "?" — never a check mark */
function mark(c: AssessmentCheck): { glyph: string; className: string } {
  if (c.status === 'NOT_EVALUATED' || c.status === 'NOT_APPLICABLE') {
    return { glyph: '?', className: 'text-mute' }
  }
  if (c.authority === 'ADVISORY') {
    return {
      glyph: '!',
      className: c.status === 'SATISFIED' ? 'text-chalk' : 'text-danger',
    }
  }
  if (c.authority === 'INFORMATIONAL') return { glyph: 'i', className: 'text-chalk-dim' }
  return c.status === 'SATISFIED'
    ? { glyph: '✓', className: 'text-lamp' }
    : { glyph: '✗', className: 'text-danger' }
}

function statusLabel(c: AssessmentCheck): string {
  switch (c.status) {
    case 'SATISFIED':
      return c.authority === 'ADVISORY' ? tr('criterion met (advisory)') : tr('satisfied')
    case 'NOT_SATISFIED':
      return c.authority === 'ADVISORY' ? tr('criterion not met (advisory)') : tr('not satisfied')
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
      return tr('{a}/{b} nodes · {r} routes', {
        a: String(e.meetingNodeCount),
        b: String(e.undergroundNodeCount),
        r: String(e.requiredRoutes),
      })
    case 'REQUIRED_CAPABILITY_PATHS':
      return tr('{a}/{b} paths', {
        a: String(e.satisfiedPathCount),
        b: String(e.requiredPathCount),
      })
    case 'ALL_REQUIRED_LEVELS_ACCESSIBLE':
      return tr('{a}/{b} levels', { a: String(e.accessibleLevels), b: String(e.requiredLevels) })
    case 'CLEARANCE_VALIDATED':
      return typeof e.conservativeMinimumClearance === 'number' &&
        typeof e.requiredClearance === 'number'
        ? `${e.conservativeMinimumClearance.toFixed(1)} m ≥ ${e.requiredClearance.toFixed(1)} m (${String(e.clearanceBasis)})`
        : statusLabel(c)
    case 'GEOMETRY_VALIDATED':
      return tr('{a} invalid / {b} samples', {
        a: String(e.invalidSampleCount),
        b: String(e.sampleCount),
      })
    case 'CANDIDATE_FEASIBLE':
      return String(e.status)
    case 'SELECTED_IS_RANKING_WINNER':
      return e.selectedRank == null ? statusLabel(c) : tr('rank {n}', { n: String(e.selectedRank) })
    case 'ACTIVE_RAMP_SOURCE':
      return String(e.activeSource)
    case 'LAYOUT_SELECTED':
      return typeof e.candidateId === 'string' ? e.candidateId : statusLabel(c)
    default:
      return statusLabel(c)
  }
}

/**
 * PR-3 round 2 — one readable line per check (mark · title · the backend
 * readout · authority badge); the backend summary, the long authority
 * label, the source artifact / field and the evidence open on hover and
 * on click (an expanded row). Nothing new is computed: the detail shows
 * the same `AssessmentCheck` fields the row already carried.
 */
function CheckDetail({ c }: { c: AssessmentCheck }) {
  const m = mark(c)
  const evidence = Object.entries(c.evidence).filter(
    ([, v]) => v === null || ['string', 'number', 'boolean'].includes(typeof v),
  )
  return (
    <div
      className="grid grid-cols-[6rem_minmax(0,1fr)] gap-x-2 gap-y-0.5 text-[11px] leading-snug"
      aria-label={tr('check detail')}
    >
      <div className="col-span-2 leading-relaxed text-chalk-dim">{tr(c.summary)}</div>
      <span className="text-mute">{tr('Status')}</span>
      <span className={`readout ${m.className}`}>{tr(statusLabel(c))}</span>
      <span className="text-mute">{tr('Authority')}</span>
      <span className="readout text-chalk-dim">{tr(AUTHORITY_LONG[c.authority])}</span>
      <span className="text-mute">{tr('Source')}</span>
      <span className="readout break-words text-chalk-dim">
        {c.sourceArtifact} · {c.sourceField}
      </span>
      {evidence.map(([k, v]) => (
        <Fragment key={k}>
          <span className="break-words text-mute">{humanKey(k)}</span>
          <span className="readout break-words text-chalk-dim">{v === null ? '—' : String(v)}</span>
        </Fragment>
      ))}
    </div>
  )
}

/** an evidence key as words ("accessibleLevels" → "accessible levels") —
 * presentation of the backend key, never a renamed field */
function humanKey(key: string): string {
  return key.replace(/([a-z0-9])([A-Z])/g, '$1 $2').toLowerCase()
}

function CheckRow({ c }: { c: AssessmentCheck }) {
  const [open, setOpen] = useState(false)
  const m = mark(c)
  return (
    <li
      className="py-0.5"
      data-check-id={c.id}
      data-authority={c.authority}
      data-status={c.status}
      data-scope={c.scope}
      aria-label={`${c.title}: ${statusLabel(c)} (${AUTHORITY_LABEL[c.authority]})`}
    >
      <HoverDetail label={`${c.title} detail`} detail={<CheckDetail c={c} />}>
        <button
          type="button"
          onClick={() => setOpen(toggled)}
          aria-expanded={open}
          className="flex w-full flex-wrap items-center gap-x-1.5 gap-y-0.5 rounded-sm px-1 py-1 text-left transition-colors hover:bg-rock-900/60"
        >
          <span
            className={`readout w-3 shrink-0 text-center text-[12px] ${m.className}`}
            aria-hidden="true"
          >
            {m.glyph}
          </span>
          <span
            className={`min-w-0 flex-1 basis-[11rem] text-[12px] leading-snug ${
              c.authority === 'ADVISORY' ? 'italic text-chalk-dim' : 'text-chalk'
            }`}
          >
            {tr(c.title)}
            {c.scope === 'INACTIVE_LAYOUT_V2' && c.status !== 'NOT_APPLICABLE' ? (
              <span className="text-mute"> {tr('(inactive)')}</span>
            ) : null}
          </span>
          {/* the readout and the badge sit beside a short title and wrap
              under a long one — the title is never squeezed */}
          <span className="ml-auto flex items-center gap-1.5 pl-4">
            <span className={`readout text-[11px] ${m.className}`}>{readout(c)}</span>
            <span
              className={`shrink-0 whitespace-nowrap rounded-sm border px-1 text-[9px] uppercase ${
                c.authority === 'ADVISORY'
                  ? 'border-dashed border-chalk-dim text-chalk-dim'
                  : c.authority === 'INFORMATIONAL'
                    ? 'border-rock-700 text-mute'
                    : 'border-rock-700 text-chalk-dim'
              }`}
            >
              {tr(AUTHORITY_LABEL[c.authority])}
            </span>
          </span>
        </button>
      </HoverDetail>
      {open ? (
        <div
          className="mb-1 ml-5 rounded-sm border border-rock-700 bg-rock-900/60 px-2 py-1.5"
          data-testid="check-detail"
        >
          <CheckDetail c={c} />
        </div>
      ) : null}
    </li>
  )
}

export function DesignAssessmentList({ assessment }: { assessment: DesignAssessmentPayload }) {
  return (
    <div className="mt-2" aria-label={tr('design assessment')}>
      <div className="readout text-[10px] text-mute">
        {tr('DESIGN ASSESSMENT · read-only projection · no statutory claim')}
      </div>
      <div className="readout mt-0.5 text-[10px] text-mute" aria-label={tr('assessment scope')}>
        {assessment.activeSource === 'LAYOUT_V2'
          ? tr('active design: Layout v2 · {id}', { id: assessment.activeDesignCandidateId ?? '—' })
          : assessment.layoutScope === 'INACTIVE_LAYOUT_V2'
            ? tr(
                'active design: LEGACY (Hybrid-A*) · layout-v2 checks describe the INACTIVE layout-v2 selection',
              )
            : tr('active design: LEGACY (Hybrid-A*) · no layout-v2 catalogue')}
      </div>
      <ul className="mt-1">
        {assessment.checks.map((c) => (
          <CheckRow key={c.id} c={c} />
        ))}
      </ul>
      {assessment.egressAdvisory ? (
        <div
          className="readout mt-1 text-[11px] text-mute"
          aria-label={tr('dual-egress advisory note')}
        >
          Dual-egress design advisory: {assessment.egressAdvisory.meetingNodeCount} /{' '}
          {assessment.egressAdvisory.undergroundNodeCount} underground nodes meet the{' '}
          {assessment.egressAdvisory.requiredRoutes}-route design criterion. This is a design
          advisory, not a statutory compliance determination.
        </div>
      ) : null}
      <pre
        className="readout mt-1 text-[11px] whitespace-pre-wrap font-sans text-mute"
        aria-label={tr('selection summary')}
      >
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
    <div className="readout mt-2 text-[11px]" aria-label={tr('candidate alternatives')}>
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
        <div className="mt-1 text-mute">{tr('no layout-v2 catalogue')}</div>
      ) : rows.length === 0 ? (
        <div className="mt-1 text-mute">{tr('no feasible candidate')}</div>
      ) : (
        <table className="mt-1 w-full table-fixed border-collapse whitespace-nowrap text-[11px]">
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
              <th className="truncate text-left font-normal">{tr('Candidate · Family')}</th>
              <th className="text-right font-normal">{tr('Score · Δ')}</th>
              <th className="text-right font-normal">{tr('Access')}</th>
              <th className="text-right font-normal">{tr('Status')}</th>
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
