import { describe, expect, it } from 'vitest'
import { placePopover, POPOVER_GAP, POPOVER_MARGIN } from './popoverPlacement'

const VIEWPORT = { width: 1280, height: 800 }
const PANEL = { width: 224, height: 120 }

describe('ⓘ popover placement (hardening H0 §3.3)', () => {
  it('prefers below the anchor, right edge aligned with the anchor', () => {
    const anchor = { left: 300, top: 100, width: 16, height: 16 }
    const p = placePopover(anchor, PANEL, VIEWPORT)
    expect(p).toEqual({
      left: 300 + 16 - 224,
      top: 100 + 16 + POPOVER_GAP,
      vertical: 'below',
      horizontal: 'right-aligned',
    })
  })

  it('flips to left-aligned when right alignment would cross the left margin (a left-panel card)', () => {
    const anchor = { left: 180, top: 100, width: 16, height: 16 }
    const p = placePopover(anchor, PANEL, VIEWPORT)
    expect(p.horizontal).toBe('left-aligned')
    expect(p.left).toBe(180)
    expect(p.left).toBeGreaterThanOrEqual(POPOVER_MARGIN)
  })

  it('flips above the anchor when the panel would run past the bottom margin', () => {
    const anchor = { left: 300, top: 760, width: 16, height: 16 }
    const p = placePopover(anchor, PANEL, VIEWPORT)
    expect(p.vertical).toBe('above')
    expect(p.top).toBe(760 - POPOVER_GAP - PANEL.height)
    expect(p.top + PANEL.height).toBeLessThanOrEqual(VIEWPORT.height - POPOVER_MARGIN)
  })

  it('clamps inside the viewport margins when neither flip fits', () => {
    // anchor near the top-right corner of a tiny viewport, panel taller than the room above
    const anchor = { left: 300, top: 10, width: 16, height: 16 }
    const p = placePopover(anchor, { width: 224, height: 700 }, { width: 320, height: 400 })
    expect(p.left).toBeGreaterThanOrEqual(POPOVER_MARGIN)
    expect(p.left + 224).toBeLessThanOrEqual(320 - POPOVER_MARGIN)
    expect(p.top).toBe(POPOVER_MARGIN) // pinned to the top margin
  })

  it('never leaves the viewport for any anchor on a 1280×800 screen', () => {
    for (let x = -20; x <= 1300; x += 97) {
      for (let y = -20; y <= 820; y += 71) {
        const p = placePopover({ left: x, top: y, width: 16, height: 16 }, PANEL, VIEWPORT)
        expect(p.left).toBeGreaterThanOrEqual(POPOVER_MARGIN)
        expect(p.left + PANEL.width).toBeLessThanOrEqual(VIEWPORT.width - POPOVER_MARGIN)
        expect(p.top).toBeGreaterThanOrEqual(POPOVER_MARGIN)
        expect(p.top + PANEL.height).toBeLessThanOrEqual(VIEWPORT.height - POPOVER_MARGIN)
      }
    }
  })
})
