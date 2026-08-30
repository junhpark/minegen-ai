/**
 * PR #10 blocker regression: the PointerLockControls selector must resolve
 * to a DOM element that persists across lock/unlock. The HUD swaps its DOM
 * with lock state, so it must never own the lock-surface id — the
 * persistent MineCanvas wrapper does, and the HUD entry button merely
 * bubbles its click to it.
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { WALKTHROUGH_LOCK_SURFACE_ID, WALKTHROUGH_LOCK_SURFACE_SELECTOR } from './lockSurface'
import { WalkthroughHUD } from './WalkthroughHUD'

describe('pointer-lock surface lifecycle contract', () => {
  it('selector points at the shared persistent-surface id', () => {
    expect(WALKTHROUGH_LOCK_SURFACE_SELECTOR).toBe(`#${WALKTHROUGH_LOCK_SURFACE_ID}`)
  })

  it('the HUD never carries the lock-surface id in either lock state', () => {
    const unlocked = renderToStaticMarkup(<WalkthroughHUD locked={false} />)
    const locked = renderToStaticMarkup(<WalkthroughHUD locked={true} />)
    expect(unlocked).toContain('Click to enter walkthrough')
    expect(unlocked).not.toContain(WALKTHROUGH_LOCK_SURFACE_ID)
    expect(locked).not.toContain(WALKTHROUGH_LOCK_SURFACE_ID)
    // the transient enter button owns no id at all — it cannot be a
    // selector target that unmounts on lock
    expect(unlocked).not.toContain('id=')
  })

  it('the entry button lets its click bubble (no stopPropagation handler)', () => {
    const unlocked = renderToStaticMarkup(<WalkthroughHUD locked={false} />)
    // static markup carries no click handler: the button is pure affordance
    expect(unlocked).toContain('<button type="button"')
  })
})
