import type { ReactNode } from 'react'
import { InfoPopover } from '@/components/ui/InfoPopover'

interface Props {
  title: string
  /** optional right-aligned tag */
  tag?: string | undefined
  children: ReactNode
  /** collapsible section; `open` is controlled by the owner, `onToggle` flips it */
  collapsible?: boolean
  open?: boolean
  onToggle?: () => void
  /** optional one-line note under the header (shown even when collapsed) */
  note?: string | undefined
  /**
   * Phase 20E §17 — technical explanation behind a ⓘ button next to the
   * title, so the primary view keeps only the short human-readable copy.
   */
  info?: ReactNode
  /** status badge / summary shown in the header row, right of the title */
  status?: ReactNode
  /** header-row controls (never a generate action — those go in the body) */
  actions?: ReactNode
}

/**
 * One panel section. Phase 20E extends it with `info`, `status` and
 * `actions`; `title`, `tag`, `note` and the controlled `collapsible` /
 * `open` / `onToggle` contract are unchanged, so every pre-20E caller keeps
 * working. A collapsed section renders no body.
 */
export function PanelSection({
  title,
  tag,
  children,
  collapsible,
  open,
  onToggle,
  note,
  info,
  status,
  actions,
}: Props) {
  const expanded = collapsible ? (open ?? true) : true
  return (
    <section className="border-b border-rock-700 px-4 py-3">
      <header className="mb-2 flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-1.5">
          {collapsible ? (
            <button
              type="button"
              onClick={onToggle}
              aria-expanded={expanded}
              className="plate flex items-center gap-1 text-left text-[12px] text-chalk-dim hover:text-chalk"
            >
              <span aria-hidden className="readout text-[10px]">
                {expanded ? '▾' : '▸'}
              </span>
              <h2 className="plate text-[12px]">{title}</h2>
            </button>
          ) : (
            <h2 className="plate text-[12px] text-chalk-dim">{title}</h2>
          )}
          {info ? <InfoPopover label={title}>{info}</InfoPopover> : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {status}
          {actions}
          {tag ? <span className="readout text-[10px] text-mute">{tag}</span> : null}
        </div>
      </header>
      {note ? <p className="mb-2 text-[11px] leading-relaxed text-mute">{note}</p> : null}
      {expanded ? children : null}
    </section>
  )
}
