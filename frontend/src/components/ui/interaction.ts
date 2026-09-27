/**
 * Pure interaction helpers for the Phase 20E panel primitives.
 *
 * The primitives keep their event handlers one-line delegations to the
 * functions below so the interaction rules (dismiss-on-Escape, arrow-key tab
 * movement, toggle) are unit-testable in this repository's node test
 * environment, without adding a DOM test dependency.
 */

/** Escape dismisses an open popover / disclosure. */
export function isDismissKey(key: string): boolean {
  return key === 'Escape' || key === 'Esc'
}

/** Space / Enter activate a native button already; nothing else opens one. */
export function isActivateKey(key: string): boolean {
  return key === 'Enter' || key === ' ' || key === 'Spacebar'
}

export function toggled(open: boolean): boolean {
  return !open
}

/**
 * Roving-tabindex movement inside a tablist. Returns the id to move to, or
 * `null` when the key is not a movement key (so the handler leaves the event
 * alone). Movement wraps, and Home / End jump to the ends.
 */
export function nextTabId<T extends string>(ids: readonly T[], current: T, key: string): T | null {
  if (ids.length === 0) return null
  const i = ids.indexOf(current)
  if (i < 0) return null
  switch (key) {
    case 'ArrowRight':
    case 'ArrowDown':
      return ids[(i + 1) % ids.length] ?? null
    case 'ArrowLeft':
    case 'ArrowUp':
      return ids[(i - 1 + ids.length) % ids.length] ?? null
    case 'Home':
      return ids[0] ?? null
    case 'End':
      return ids[ids.length - 1] ?? null
    default:
      return null
  }
}

/** Structural view of the one DOM call this module needs, so the helper is
 * testable without a DOM global. */
interface ContainsNode {
  contains(other: unknown): boolean
}

/**
 * True when the click that produced `target` happened outside `container`.
 * A missing container means there is nothing to close; a target that is not
 * an element (or is null) counts as outside.
 */
export function isOutside(container: ContainsNode | null, target: unknown): boolean {
  if (!container) return false
  if (target === null || typeof target !== 'object') return true
  return !container.contains(target)
}

/** Structural view of the one document call the roving tab focus needs. */
interface TabDocument {
  getElementById(id: string): { focus(): void } | null
}

/** The DOM id `PanelTabs` gives every tab button — ONE definition. */
export function tabElementId(panelId: string, id: string): string {
  return `${panelId}-tab-${id}`
}

/**
 * Phase 21A (§37): after a keyboard tab move the roving tabindex alone does
 * not move focus — `aria-selected` and `tabIndex` change, but the focused
 * element stays the old tab. Move DOM focus to the newly active tab; a
 * missing element (not mounted, no DOM) is a no-op. Returns whether focus
 * was moved, so the behaviour is testable without a DOM global.
 */
export function focusTab(doc: TabDocument | null, panelId: string, id: string): boolean {
  const el = doc?.getElementById(tabElementId(panelId, id)) ?? null
  if (!el) return false
  el.focus()
  return true
}
