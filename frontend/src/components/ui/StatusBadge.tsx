import { type StatusTone } from './presentation'

/**
 * Phase 20E §13 — one status presentation for every feature. The tone comes
 * from `artifactTone` in `presentation.ts`; this component only renders it,
 * reusing the existing MineGen colour tokens.
 */
const TEXT: Record<StatusTone, string> = {
  READY: 'Ready',
  RUNNING: 'Running',
  FAILED: 'Failed',
  NOT_GENERATED: 'Not generated',
  ACTIVE: 'Active',
  INACTIVE: 'Inactive',
}

const TONE: Record<StatusTone, string> = {
  READY: 'text-lamp',
  RUNNING: 'text-chalk-dim',
  FAILED: 'text-danger',
  NOT_GENERATED: 'text-mute',
  ACTIVE: 'text-lamp',
  INACTIVE: 'text-mute',
}

const DOT: Record<StatusTone, string> = {
  READY: 'bg-lamp',
  RUNNING: 'bg-chalk-dim',
  FAILED: 'bg-danger',
  NOT_GENERATED: 'bg-mute',
  ACTIVE: 'bg-lamp',
  INACTIVE: 'bg-mute',
}

export function StatusBadge({ tone, label }: { tone: StatusTone; label?: string | undefined }) {
  return (
    <span
      className={`plate inline-flex items-center gap-1 text-[11px] ${TONE[tone]}`}
      data-status={tone}
    >
      <span aria-hidden className={`inline-block h-1.5 w-1.5 rounded-full ${DOT[tone]}`} />
      {label ?? TEXT[tone]}
    </span>
  )
}
