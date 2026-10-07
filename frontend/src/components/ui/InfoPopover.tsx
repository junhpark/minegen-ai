import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from 'react'
import { createPortal } from 'react-dom'
import { isDismissKey, isOutside, toggled } from './interaction'
import { placePopover, type Placement } from './popoverPlacement'

interface Props {
  /** what the explanation is about; used for the accessible name */
  label: string
  /** the technical explanation — text only, never an action (Phase 20E §8) */
  children: ReactNode
  /** initial state; the popover is closed by default */
  defaultOpen?: boolean
}

/** the panel's fixed width, px (Tailwind w-56) — the one size the placement needs before the first paint */
const PANEL_WIDTH = 224

/**
 * Phase 20E §8 — the ⓘ information button.
 *
 * Holds the technical explanation of a feature (semantics, units,
 * architecture distinctions, validation meaning) that used to sit as a long
 * paragraph in the primary panel. It opens on click or keyboard activation,
 * never on hover, and closes on Escape or an outside click. It never
 * contains a button, a generate action or any state-changing control.
 *
 * Hardening H0 §3.3: the panel is rendered through a portal into
 * `document.body` with `position: fixed`, placed from the button's
 * `getBoundingClientRect()` by the pure `placePopover` rule (right-aligned
 * below the button; flips left / above and clamps to the viewport margins),
 * and re-placed on resize and scroll — so a scrolling side panel can no
 * longer clip it. Without a DOM (server / node tests) the panel renders
 * inline, so the rendered contract is unchanged.
 */
export function InfoPopover({ label, children, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen)
  const panelId = `info-${useId()}`
  const wrap = useRef<HTMLSpanElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLSpanElement>(null)
  const [placement, setPlacement] = useState<Placement | null>(null)
  const canPortal = typeof document !== 'undefined'

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (isDismissKey(e.key)) setOpen(false)
    }
    const onDown = (e: MouseEvent) => {
      // the panel lives in the portal, outside the wrapper: a click inside it is inside
      if (isOutside(wrap.current, e.target) && isOutside(panel.current, e.target)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
    }
  }, [open])

  // placement: measured from the live button and panel rectangles; re-run on
  // resize and on any scroll (capture — the aside scrolls, not the window)
  useLayoutEffect(() => {
    if (!open || !canPortal) {
      setPlacement(null)
      return
    }
    const place = () => {
      const b = button.current?.getBoundingClientRect()
      if (!b) return
      const height = panel.current?.getBoundingClientRect().height ?? 0
      setPlacement(
        placePopover(
          { left: b.left, top: b.top, width: b.width, height: b.height },
          { width: PANEL_WIDTH, height },
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
  }, [open, canPortal])

  const style: CSSProperties | undefined = canPortal
    ? placement
      ? { position: 'fixed', left: placement.left, top: placement.top, width: PANEL_WIDTH }
      : { position: 'fixed', left: 0, top: 0, width: PANEL_WIDTH, visibility: 'hidden' }
    : undefined
  const content = (
    <span
      ref={panel}
      id={panelId}
      role="note"
      data-placement={placement ? `${placement.vertical} ${placement.horizontal}` : undefined}
      style={style}
      className={[
        'z-50 rounded-sm border border-rock-600 bg-rock-950 px-2 py-1.5 text-left text-[11px] leading-relaxed font-normal tracking-normal text-chalk-dim normal-case shadow-lg',
        canPortal ? 'block' : 'absolute top-5 right-0 w-56',
      ].join(' ')}
    >
      {children}
    </span>
  )

  return (
    <span ref={wrap} className="relative inline-flex shrink-0 align-middle">
      <button
        ref={button}
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
      {open ? (canPortal ? createPortal(content, document.body) : content) : null}
    </span>
  )
}
