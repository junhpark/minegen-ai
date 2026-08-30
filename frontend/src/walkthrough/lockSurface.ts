/**
 * Pointer-lock surface contract (PR #10 blocker).
 *
 * Drei PointerLockControls resolves its `selector` and attaches the click
 * listener ONCE in its mount effect. The lock target must therefore be a
 * DOM element that stays mounted for the ENTIRE walkthrough mode — never a
 * node the HUD swaps in and out with lock state, or re-entry after Esc
 * would click a recreated element that no longer carries the listener.
 *
 * The persistent MineCanvas wrapper carries this id; the HUD entry button
 * is a pure visual affordance whose click BUBBLES to the wrapper.
 */
export const WALKTHROUGH_LOCK_SURFACE_ID = 'walkthrough-lock-surface'
export const WALKTHROUGH_LOCK_SURFACE_SELECTOR = `#${WALKTHROUGH_LOCK_SURFACE_ID}`
