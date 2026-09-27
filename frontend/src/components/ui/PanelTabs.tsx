import { focusTab, nextTabId, tabElementId } from './interaction'

export interface PanelTab<T extends string> {
  id: T
  label: string
}

interface Props<T extends string> {
  tabs: readonly PanelTab<T>[]
  active: T
  onSelect: (id: T) => void
  /** accessible name of the tablist */
  label: string
  /** id of the tabpanel the tabs control */
  panelId: string
}

/**
 * Phase 20E §4/§5 — secondary workflow tabs inside the left panel.
 *
 * Switching a tab is a PRESENTATION event only (§19): it selects which
 * workflow context is shown and never posts, mutates, regenerates or resets
 * layer state. Tab identity is frontend-local UI state and is never
 * persisted to a scenario. Arrow / Home / End keys move BOTH the selection
 * and DOM focus (Phase 21A §37), so the roving tabindex stays usable.
 */
export function PanelTabs<T extends string>({ tabs, active, onSelect, label, panelId }: Props<T>) {
  const ids = tabs.map((t) => t.id)
  return (
    <div
      role="tablist"
      aria-label={label}
      className="flex border-b border-rock-700 bg-rock-900/40 px-2"
    >
      {tabs.map((t) => {
        const selected = t.id === active
        return (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={tabElementId(panelId, t.id)}
            aria-selected={selected}
            aria-controls={panelId}
            tabIndex={selected ? 0 : -1}
            onClick={() => onSelect(t.id)}
            onKeyDown={(e) => {
              const next = nextTabId(ids, active, e.key)
              if (next === null) return
              e.preventDefault()
              onSelect(next)
              // §37: the roving tabindex needs DOM focus to follow the move
              focusTab(typeof document === 'undefined' ? null : document, panelId, next)
            }}
            className={[
              'plate flex-1 px-1 py-2 text-[12px] whitespace-nowrap transition-colors',
              selected
                ? 'text-lamp shadow-[inset_0_-2px_0_0_var(--color-lamp)]'
                : 'text-chalk-dim hover:text-chalk',
            ].join(' ')}
          >
            {t.label}
          </button>
        )
      })}
    </div>
  )
}
