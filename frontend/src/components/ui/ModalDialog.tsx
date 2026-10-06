import { useEffect, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

interface Props {
  title: string
  /** closes on Escape / backdrop click; the owner decides what closing means */
  onClose: () => void
  children: ReactNode
  /** footer controls (Cancel / Confirm) — supplied by the owner */
  footer?: ReactNode
}

/**
 * Hardening H1 §4.3/§4.4 — one small modal for the confirmations the shell
 * asks for (Reset from here, a mining-method change). Presentation only: it
 * renders the owner's content through a portal to `document.body` and
 * never decides the outcome itself. Without a DOM (static markup) it
 * renders inline.
 */
export function ModalDialog({ title, onClose, children, footer }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const node = (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-rock-950/70"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="w-[380px] max-w-[92vw] rounded-sm border border-rock-600 bg-rock-800 shadow-xl"
      >
        <header className="border-b border-rock-700 px-4 py-2.5">
          <h2 className="plate text-[13px] text-chalk">{title}</h2>
        </header>
        <div className="max-h-[60vh] overflow-y-auto px-4 py-3 text-[12px] leading-relaxed text-chalk-dim">
          {children}
        </div>
        {footer ? (
          <footer className="flex justify-end gap-2 border-t border-rock-700 px-4 py-2.5">
            {footer}
          </footer>
        ) : null}
      </div>
    </div>
  )
  if (typeof document === 'undefined') return node
  return createPortal(node, document.body)
}

/** the two footer buttons every shell confirmation uses */
export function DialogButton({
  kind,
  onClick,
  disabled = false,
  children,
}: {
  kind: 'cancel' | 'confirm' | 'danger'
  onClick: () => void
  disabled?: boolean
  children: ReactNode
}) {
  const style =
    kind === 'cancel'
      ? 'border border-rock-600 text-chalk hover:bg-rock-700'
      : kind === 'danger'
        ? 'bg-danger text-rock-950 hover:brightness-110'
        : 'bg-lamp text-rock-950 hover:bg-lamp-deep hover:text-chalk'
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`plate rounded-sm px-3 py-1 text-[12px] disabled:cursor-not-allowed disabled:opacity-40 ${style}`}
    >
      {children}
    </button>
  )
}
