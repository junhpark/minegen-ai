/**
 * Pure placement of the ⓘ popover panel (hardening H0 §3.3).
 *
 * The panel is rendered through a portal into `document.body` with
 * `position: fixed`, so a scrolling / clipping panel (`overflow-y-auto`
 * asides) can no longer cut it off. Where it goes is decided here from three
 * rectangles — the anchor button, the panel's own size and the viewport — so
 * the rule is unit-testable in the node test environment:
 *
 * - preferred: below the anchor, its RIGHT edge aligned with the anchor's
 *   right edge (the ⓘ sits at the right end of a card title);
 * - horizontal flip: when that would leave the left edge inside the margin,
 *   align the LEFT edge with the anchor's left edge instead;
 * - vertical flip: when the panel would run past the bottom margin, place it
 *   above the anchor;
 * - clamp: whatever the flips chose, the panel stays inside the viewport
 *   margins (a panel taller / wider than the viewport pins to the margin).
 */

export interface Rect {
  left: number
  top: number
  width: number
  height: number
}

export interface Size {
  width: number
  height: number
}

export interface Placement {
  left: number
  top: number
  vertical: 'below' | 'above'
  horizontal: 'right-aligned' | 'left-aligned'
}

/** gap between the anchor and the panel, px */
export const POPOVER_GAP = 4
/** minimum distance from every viewport edge, px */
export const POPOVER_MARGIN = 8

const clamp = (v: number, lo: number, hi: number): number =>
  Math.min(Math.max(v, lo), Math.max(lo, hi))

export function placePopover(
  anchor: Rect,
  panel: Size,
  viewport: Size,
  gap: number = POPOVER_GAP,
  margin: number = POPOVER_MARGIN,
): Placement {
  // horizontal: right-aligned to the anchor, flip to left-aligned near the left edge
  let horizontal: Placement['horizontal'] = 'right-aligned'
  let left = anchor.left + anchor.width - panel.width
  if (left < margin) {
    horizontal = 'left-aligned'
    left = anchor.left
  }
  left = clamp(left, margin, viewport.width - margin - panel.width)
  // vertical: below the anchor, flip above when it would run past the bottom
  let vertical: Placement['vertical'] = 'below'
  let top = anchor.top + anchor.height + gap
  if (top + panel.height > viewport.height - margin) {
    const above = anchor.top - gap - panel.height
    if (above >= margin) {
      vertical = 'above'
      top = above
    }
  }
  top = clamp(top, margin, viewport.height - margin - panel.height)
  return { left, top, vertical, horizontal }
}
