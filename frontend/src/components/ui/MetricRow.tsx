import type { ReactNode } from 'react'
import { tr } from '@/i18n/t'

export interface Metric {
  label: string
  value: ReactNode
}

/** One label / value line of a detailed readout. */
export function MetricRow({ label, value }: Metric) {
  return (
    <div className="flex justify-between gap-3 border-b border-rock-800/60 py-px last:border-b-0">
      <span className="text-mute">{tr(label)}</span>
      <span className="readout text-right break-words text-chalk-dim">
        {typeof value === 'string' ? tr(value) : value}
      </span>
    </div>
  )
}

/**
 * Phase 20E §16 — the detailed-number block used inside `Disclosure`.
 * Rows whose value is `null` / `undefined` are dropped so a card never shows
 * an empty metric.
 */
export function Metrics({ rows }: { rows: (Metric | null)[] }) {
  const shown = rows.filter((r): r is Metric => r !== null && r.value !== null)
  if (shown.length === 0) return null
  return (
    <div className="flex flex-col gap-y-0.5">
      {shown.map((r) => (
        <MetricRow key={r.label} label={r.label} value={r.value} />
      ))}
    </div>
  )
}
