import type { ReactNode } from 'react'
import { Disclosure } from './Disclosure'
import { InfoPopover } from './InfoPopover'
import { type StatusTone } from './presentation'
import { StatusBadge } from './StatusBadge'

interface Props {
  title: string
  tone: StatusTone
  /** overrides the badge text (e.g. "Access only") without a new status */
  statusLabel?: string | undefined
  /** technical explanation, moved out of the primary view into ⓘ (§9) */
  info?: ReactNode
  /** key metrics of the current result — one short line, always visible */
  summary?: ReactNode
  /** backend failure reason — ALWAYS visible, never behind Details (§24) */
  failure?: string | null | undefined
  /** prerequisite / scope notice that the user must see to act */
  notice?: ReactNode
  /** the primary or secondary action button for this feature */
  action?: ReactNode
  /** running-job progress, shown between the action and the result */
  progress?: ReactNode
  /** detailed numbers of the current result (§10) */
  details?: ReactNode
  detailsLabel?: string
}

/**
 * Phase 20E §1 — one workflow card layout:
 *
 *   title + ⓘ          status
 *   key metrics
 *   [ action ]
 *   Details ▸
 *
 * The card is presentation only: every value is echoed from the backend and
 * every enabled/disabled condition comes from the caller.
 */
export function WorkflowCard(p: Props) {
  return (
    <section className="border-b border-rock-700 px-4 py-3">
      <header className="mb-1.5 flex items-center justify-between gap-2">
        <h3 className="plate flex items-center gap-1.5 text-[12px] text-chalk">
          {p.title}
          {p.info ? <InfoPopover label={p.title}>{p.info}</InfoPopover> : null}
        </h3>
        <StatusBadge tone={p.tone} label={p.statusLabel} />
      </header>
      {p.summary ? (
        <div className="readout mb-1.5 text-[11px] text-chalk-dim">{p.summary}</div>
      ) : null}
      {p.failure ? <p className="mb-1.5 break-words text-[11px] text-danger">{p.failure}</p> : null}
      {p.notice ? (
        <div className="mb-1.5 rounded-sm border border-rock-700 bg-rock-900/70 px-2 py-1.5 text-[11px] leading-relaxed text-chalk-dim">
          {p.notice}
        </div>
      ) : null}
      {p.action}
      {p.progress}
      {p.details ? <Disclosure label={p.detailsLabel ?? 'Details'}>{p.details}</Disclosure> : null}
    </section>
  )
}
