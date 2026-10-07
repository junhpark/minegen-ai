import type { ReactNode } from 'react'
import { type ActionVariant } from './presentation'

interface Props {
  variant: ActionVariant
  onClick: () => void
  disabled?: boolean
  title?: string | undefined
  children: ReactNode
}

const STYLE: Record<ActionVariant, string> = {
  // the next key action of the current workflow
  primary: 'bg-lamp text-rock-950 hover:bg-lamp-deep hover:text-chalk',
  // regeneration / auxiliary action on an existing result
  secondary: 'border border-lamp text-lamp hover:bg-lamp hover:text-rock-950',
}

/**
 * Phase 20E §14 — one button hierarchy for every workflow action.
 *
 * `primary` is the next key action, `secondary` regenerates or supports an
 * existing result. The DISABLED condition is always supplied by the caller
 * from the pre-existing prerequisite logic; this component never decides it.
 */
export function ActionButton({ variant, onClick, disabled = false, title, children }: Props) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      data-variant={variant}
      className={`plate w-full rounded-sm px-3 py-1.5 text-[13px] disabled:cursor-not-allowed disabled:opacity-40 ${STYLE[variant]}`}
    >
      {children}
    </button>
  )
}
