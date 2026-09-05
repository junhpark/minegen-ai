import type { ReactNode } from 'react'

interface Props {
  title: string
  /** optional right-aligned tag, e.g. a phase marker */
  tag?: string | undefined
  children: ReactNode
  /** collapsible section (closeout v3 §1: the legacy workflow folds away);
   * `open` is controlled by the owner, `onToggle` flips it */
  collapsible?: boolean
  open?: boolean
  onToggle?: () => void
  /** optional one-line note under the header (shown even when collapsed) */
  note?: string | undefined
}

export function PanelSection({ title, tag, children, collapsible, open, onToggle, note }: Props) {
  const expanded = collapsible ? (open ?? true) : true
  return (
    <section className="border-b border-rock-700 px-4 py-3">
      <header className="mb-2 flex items-baseline justify-between">
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
        {tag ? <span className="readout text-[10px] text-mute">{tag}</span> : null}
      </header>
      {note ? <p className="mb-2 text-[11px] leading-relaxed text-mute">{note}</p> : null}
      {expanded ? children : null}
    </section>
  )
}
