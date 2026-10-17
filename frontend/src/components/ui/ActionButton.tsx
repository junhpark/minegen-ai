import type { ReactNode } from 'react'
import { type ActionVariant } from './presentation'
import { tr } from '@/i18n/t'

interface Props {
  variant: ActionVariant
  onClick: () => void
  disabled?: boolean
  title?: string | undefined
  children: ReactNode
}

const STYLE: Record<ActionVariant, string> = {
  // the next key action of the current workflow
  primary:
    'bg-gradient-to-b from-lamp to-lamp-deep/90 text-rock-950 shadow-glow hover:from-chalk hover:to-lamp hover:text-rock-950',
  // regeneration / auxiliary action on an existing result
  secondary: 'border border-lamp/80 text-lamp hover:border-lamp hover:bg-lamp hover:text-rock-950',
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
      className={`plate w-full rounded-md px-3 py-1.5 text-[13px] transition-colors disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none ${STYLE[variant]}`}
    >
      {typeof children === 'string' ? tr(children) : children}
    </button>
  )
}
