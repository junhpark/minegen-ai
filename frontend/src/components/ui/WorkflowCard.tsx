import { useContext, useEffect, useId, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useShellStore } from '@/components/layout/shellStore'
import type { StageId } from '@/types/workflow'
import { CardLayoutContext } from './cardLayout'
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
  /**
   * Hardening H1 §4.2 — the workflow stage this card belongs to. Inside the
   * three-pane shell the card's ACTION renders in the controls column while
   * its STATUS / metrics / failure / details render in the results column
   * (see `CardLayoutContext`); without a stage, or outside the shell, the
   * card renders whole exactly as before.
   */
  stage?: StageId
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
  const layout = useContext(CardLayoutContext)
  const reportTone = useShellStore((s) => s.reportTone)
  const { stage, tone } = p
  // the stepper's ↻ glyph: a mounted staged card reports the tone its badge
  // shows and withdraws it on unmount (never a second status source); the
  // report is keyed per card instance so sibling cards of one stage never
  // overwrite each other (review round 2 S3)
  const reporter = useId()
  useEffect(() => {
    if (stage === undefined) return undefined
    reportTone(stage, reporter, tone)
    return () => reportTone(stage, reporter, null)
  }, [stage, reporter, tone, reportTone])
  if (layout.placement === 'SPLIT' && p.stage !== undefined) {
    const hasControls = p.action !== undefined || p.notice || p.progress
    const controls =
      layout.stage === p.stage && layout.controlsHost && hasControls
        ? createPortal(
            <section className="border-b border-rock-700 px-4 py-3" data-card-controls={p.stage}>
              <header className="mb-1.5 flex items-center gap-1.5">
                <h3 className="plate flex items-center gap-1.5 text-[12px] text-chalk">
                  {p.title}
                  {p.info ? <InfoPopover label={p.title}>{p.info}</InfoPopover> : null}
                </h3>
              </header>
              {p.notice ? (
                <div className="mb-1.5 rounded-sm border border-rock-700 bg-rock-900/70 px-2 py-1.5 text-[11px] leading-relaxed text-chalk-dim">
                  {p.notice}
                </div>
              ) : null}
              {p.action}
              {p.progress}
            </section>,
            layout.controlsHost,
          )
        : null
    const results =
      layout.stepStages.includes(p.stage) && layout.resultsHost
        ? createPortal(
            <section className="border-b border-rock-700 px-4 py-3" data-card-results={p.stage}>
              <header className="mb-1.5 flex items-center justify-between gap-2">
                <h3 className="plate text-[12px] text-chalk">{p.title}</h3>
                <StatusBadge tone={p.tone} label={p.statusLabel} />
              </header>
              {p.summary ? (
                <div className="readout mb-1.5 text-[11px] text-chalk-dim">{p.summary}</div>
              ) : null}
              {p.failure ? (
                <p className="mb-1.5 break-words text-[11px] text-danger">{p.failure}</p>
              ) : null}
              {p.details ? (
                <Disclosure label={p.detailsLabel ?? 'Details'}>{p.details}</Disclosure>
              ) : null}
            </section>,
            layout.resultsHost,
          )
        : null
    return (
      <>
        {controls}
        {results}
      </>
    )
  }
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

/**
 * Inline content that belongs to a stage's CONTROLS column (a prerequisite
 * notice, an action error line) but is not a card. In the shell it is
 * portalled into the controls host while one of `stages` is current;
 * outside the shell it renders inline, unchanged.
 */
export function StageSlot({
  stages,
  children,
}: {
  stages: readonly StageId[]
  children: ReactNode
}) {
  const layout = useContext(CardLayoutContext)
  if (layout.placement !== 'SPLIT') return <>{children}</>
  if (layout.stage === null || !stages.includes(layout.stage) || !layout.controlsHost) return null
  return createPortal(<div data-stage-slot={layout.stage}>{children}</div>, layout.controlsHost)
}
