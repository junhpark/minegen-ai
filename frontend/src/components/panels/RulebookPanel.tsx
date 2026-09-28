import type { DesignAssessmentPayload } from '@/types/scene'
import { InfoPopover } from '@/components/ui/InfoPopover'
import {
  AUTHORITY_LABEL,
  CATEGORY_LABEL,
  evidenceText,
  rulebookStatus,
  SCOPE_LABEL,
} from './rulebook'

/**
 * Phase 22C — the Design Rulebook (rule 203).
 *
 * A PRESENTATION of the Phase 20D.3 design assessment (`GET
 * …/design/assessment`, rule 189): every row is one backend `AssessmentCheck`
 * rendered with its recorded status, authority, scope and evidence. Nothing
 * is evaluated, scored, aggregated or inferred here — there is no overall
 * compliance score, percentage or "compliant" verdict, a satisfied ADVISORY is
 * never a pass mark, an INFORMATIONAL row carries no pass / fail, and
 * NOT_EVALUATED stays NOT_EVALUATED (never coerced to a failure).
 */

export const RULEBOOK_ADVISORY_NOTE = 'Design advisory — not a statutory compliance determination'
export const RULEBOOK_INACTIVE_NOTE =
  'The layout-v2 rows describe the INACTIVE layout-v2 selection; the active design uses the Legacy ramp.'

export interface RulebookBodyProps {
  assessment: DesignAssessmentPayload | null
  error: string | null
  loading: boolean
}

export function RulebookBody({ assessment, error, loading }: RulebookBodyProps) {
  if (error) {
    return (
      <p className="break-words px-4 py-3 text-[11px] text-danger" data-testid="rulebook-error">
        design assessment unavailable — {error}
      </p>
    )
  }
  if (!assessment) {
    return (
      <p className="px-4 py-3 text-[11px] text-mute">{loading ? 'Loading design rules…' : ''}</p>
    )
  }
  const inactive = assessment.layoutScope === 'INACTIVE_LAYOUT_V2'
  return (
    <section className="border-b border-rock-700 px-4 py-3" aria-label="design rulebook">
      <header className="mb-1.5 flex items-center justify-between gap-2">
        <h3 className="plate flex items-center gap-1.5 text-[12px] text-chalk">
          Design Rulebook
          <InfoPopover label="Design Rulebook">
            A read-only presentation of the design assessment: each row is one recorded design rule,
            design validation, design advisory or informational fact with its authority and scope.
            Nothing is re-evaluated here and no overall compliance score exists. A design advisory
            is not a statutory compliance determination; an informational row has no pass or fail.
          </InfoPopover>
        </h3>
        <span className="text-[10px] uppercase text-mute">{assessment.checks.length} rules</span>
      </header>
      <div className="mb-1.5 text-[11px] text-mute" aria-label="rulebook scope">
        {assessment.activeSource === 'LAYOUT_V2'
          ? `Active design: Layout v2 · ${assessment.activeDesignCandidateId ?? '—'}`
          : inactive
            ? 'Active design: Legacy ramp (Hybrid-A*)'
            : 'Active design: Legacy ramp (Hybrid-A*) · no layout-v2 catalogue'}
      </div>
      {inactive ? (
        <p className="mb-1.5 text-[11px] text-chalk-dim" data-testid="rulebook-inactive-note">
          {RULEBOOK_INACTIVE_NOTE}
        </p>
      ) : null}
      <table
        className="w-full table-fixed border-collapse text-[10px]"
        data-testid="rulebook-table"
      >
        <colgroup>
          <col className="w-14" />
          <col />
          <col className="w-[92px]" />
        </colgroup>
        <thead className="text-mute">
          <tr>
            <th className="text-left font-normal">Category</th>
            <th className="text-left font-normal">Rule</th>
            <th className="text-right font-normal">Status</th>
          </tr>
        </thead>
        <tbody className="align-top">
          {assessment.checks.map((c) => {
            const st = rulebookStatus(c)
            return [
              <tr
                key={c.id}
                className="border-t border-rock-800"
                data-check-id={c.id}
                data-authority={c.authority}
                data-status={c.status}
                data-scope={c.scope}
                data-rulebook-status={st.text}
              >
                <td className="pt-1 pr-1 text-mute">{CATEGORY_LABEL[c.category]}</td>
                <td className="pt-1 pr-1 text-chalk-dim">{c.title}</td>
                <td className={`pt-1 text-right whitespace-nowrap ${st.className}`}>
                  {st.glyph ? <span aria-hidden="true">{st.glyph} </span> : null}
                  {st.text}
                </td>
              </tr>,
              <tr key={`${c.id}:detail`} data-check-detail={c.id}>
                <td colSpan={3} className="pb-1 text-mute">
                  <div>
                    <span className="uppercase">Authority</span> {AUTHORITY_LABEL[c.authority]} ·{' '}
                    <span className="uppercase">Scope</span> {SCOPE_LABEL[c.scope]}
                  </div>
                  <div className="break-words" aria-label="evidence">
                    <span className="uppercase">Evidence</span> {evidenceText(c)}
                  </div>
                  {c.authority === 'ADVISORY' ? (
                    <div className="italic">{RULEBOOK_ADVISORY_NOTE}</div>
                  ) : null}
                </td>
              </tr>,
            ]
          })}
        </tbody>
      </table>
      <p className="mt-1.5 text-[10px] text-mute">
        Read-only projection of the design assessment · no overall compliance score · advisories are
        design advisories, not statutory compliance determinations.
      </p>
    </section>
  )
}
