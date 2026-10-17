import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from 'react'
import { createPortal } from 'react-dom'
import { isDismissKey } from './interaction'
import { placePopover, type Placement } from './popoverPlacement'

interface Props {
  /** what the detail is about; used for the accessible name */
  label: string
  /** the detail content — text and numbers only, never an action */
  detail: ReactNode
  /** the trigger: a row, an option, a check */
  children: ReactNode
  /** panel width, px */
  width?: number
}

/**
 * Hardening PR-3 round 2 — a hover / focus detail for dense rows.
 *
 * A list row keeps ONE readable line; everything behind it (the full
 * numbers, the backend summary, the source) opens in a portal panel while
 * the pointer rests on the row or the row has keyboard focus, placed by the
 * same `placePopover` rule as the ⓘ popover (viewport clamped, re-placed on
 * resize / scroll). The panel takes no pointer events and holds no control.
 * It is never the only way to the detail: the owner also shows the same
 * content on click (an expanded row), so the rule-191 "never hover-only"
 * contract holds. Without a DOM (static markup) nothing but the trigger
 * renders.
 */
export function HoverDetail({ label, detail, children, width = 300 }: Props) {
  const [open, setOpen] = useState(false)
  const wrap = useRef<HTMLDivElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const [placement, setPlacement] = useState<Placement | null>(null)
  const canPortal = typeof document !== 'undefined'

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (isDismissKey(e.key)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])

  useLayoutEffect(() => {
    if (!open || !canPortal) {
      setPlacement(null)
      return
    }
    const place = () => {
      const b = wrap.current?.getBoundingClientRect()
      if (!b) return
      const height = panel.current?.getBoundingClientRect().height ?? 0
      setPlacement(
        placePopover(
          { left: b.left, top: b.top, width: b.width, height: b.height },
          { width, height },
          { width: window.innerWidth, height: window.innerHeight },
        ),
      )
    }
    place()
    window.addEventListener('resize', place)
    document.addEventListener('scroll', place, true)
    return () => {
      window.removeEventListener('resize', place)
      document.removeEventListener('scroll', place, true)
    }
  }, [open, canPortal, width])

  const style: CSSProperties = placement
    ? { position: 'fixed', left: placement.left, top: placement.top, width }
    : { position: 'fixed', left: 0, top: 0, width, visibility: 'hidden' }
  const content = (
    <div
      ref={panel}
      role="tooltip"
      aria-label={label}
      data-testid="hover-detail"
      data-placement={placement ? `${placement.vertical} ${placement.horizontal}` : undefined}
      style={style}
      className="pointer-events-none z-50 rounded-sm border border-rock-600 bg-rock-950 px-2.5 py-2 text-left text-[11px] leading-relaxed font-normal tracking-normal text-chalk-dim normal-case shadow-lg"
    >
      {detail}
    </div>
  )
  return (
    <div
      ref={wrap}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      {children}
      {open && canPortal ? createPortal(content, document.body) : null}
    </div>
  )
}
