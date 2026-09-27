import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { isDismissKey, isOutside, toggled } from './interaction'

interface Props {
  /** what the explanation is about; used for the accessible name */
  label: string
  /** the technical explanation — text only, never an action (Phase 20E §8) */
  children: ReactNode
  /** initial state; the popover is closed by default */
  defaultOpen?: boolean
}

/**
 * Phase 20E §8 — the ⓘ information button.
 *
 * Holds the technical explanation of a feature (semantics, units,
 * architecture distinctions, validation meaning) that used to sit as a long
 * paragraph in the primary panel. It opens on click or keyboard activation,
 * never on hover, and closes on Escape or an outside click. It never
 * contains a button, a generate action or any state-changing control.
 */
export function InfoPopover({ label, children, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen)
  const panelId = `info-${useId()}`
  const wrap = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (isDismissKey(e.key)) setOpen(false)
    }
    const onDown = (e: MouseEvent) => {
      if (isOutside(wrap.current, e.target)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
    }
  }, [open])

  return (
    <span ref={wrap} className="relative inline-flex shrink-0 align-middle">
      <button
        type="button"
        aria-label={`About ${label}`}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen(toggled)}
        className={[
          'readout flex h-4 w-4 items-center justify-center rounded-full border text-[10px] leading-none transition-colors',
          open
            ? 'border-lamp bg-lamp text-rock-950'
            : 'border-rock-600 text-mute hover:border-lamp hover:text-lamp',
        ].join(' ')}
      >
        i
      </button>
      {open ? (
        <span
          id={panelId}
          role="note"
          className="absolute top-5 right-0 z-30 w-56 rounded-sm border border-rock-600 bg-rock-950 px-2 py-1.5 text-left text-[11px] leading-relaxed font-normal tracking-normal text-chalk-dim normal-case shadow-lg"
        >
          {children}
        </span>
      ) : null}
    </span>
  )
}
