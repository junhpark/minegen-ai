import { useId, useState, type ReactNode } from 'react'
import { toggled } from './interaction'

interface Props {
  /** trigger text, e.g. "Details" or "Advanced" */
  label: string
  children: ReactNode
  defaultOpen?: boolean
  /** optional right-aligned hint on the trigger row */
  hint?: string | undefined
  /** controlled mode: supply both to let the owner hold the state */
  open?: boolean | undefined
  onToggle?: (() => void) | undefined
}

/**
 * Phase 20E §10/§11 — collapsible secondary content.
 *
 * "Details" holds the detailed numbers of the CURRENT result; "Advanced"
 * holds developer / legacy controls. Status, key metrics and any failure
 * reason stay outside it (§24).
 *
 * The region stays in the document and is closed with the `hidden`
 * attribute, so the collapsed state is a real DOM-visibility state rather
 * than an unmounted subtree.
 */
export function Disclosure({
  label,
  children,
  defaultOpen = false,
  hint,
  open: controlled,
  onToggle,
}: Props) {
  const [uncontrolled, setUncontrolled] = useState(defaultOpen)
  const open = controlled ?? uncontrolled
  const panelId = `disclosure-${useId()}`
  return (
    <div className="mt-1.5">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => (onToggle ? onToggle() : setUncontrolled(toggled))}
        className="plate flex w-full items-baseline gap-1 text-left text-[11px] text-mute hover:text-chalk-dim"
      >
        <span aria-hidden className="readout text-[10px]">
          {open ? '▾' : '▸'}
        </span>
        <span>{label}</span>
        {hint ? <span className="readout ml-auto text-[10px] normal-case">{hint}</span> : null}
      </button>
      <div id={panelId} hidden={!open} className="readout mt-1 text-[11px]">
        {children}
      </div>
    </div>
  )
}
