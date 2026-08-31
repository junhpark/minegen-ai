import type { ReactNode } from 'react'
import { WALKTHROUGH_LOCK_SURFACE_ID } from '@/walkthrough/lockSurface'

/**
 * Viewport DOM ownership contract (PR #11 blocker 2).
 *
 * Drei PointerLockControls attaches a native click listener to the
 * `#walkthrough-lock-surface` element and calls lock() on ANY click that
 * reaches it. The lock-request surface must therefore contain ONLY the
 * canvas and the entry HUD (whose "Click to enter walkthrough" button
 * intentionally bubbles), while ordinary interactive UI — the walkthrough
 * inspector card and its Close button — must live OUTSIDE that element as
 * a sibling so an ESC-unlocked click on it can never re-lock the pointer.
 *
 * The lock surface itself stays mounted in every mode, preserving the
 * Phase 13 persistent-selector contract; we deliberately encode the split
 * in this tiny component so the ownership is structurally testable and
 * does not rely on stopPropagation discipline.
 */
export function MineViewportShell({
  lockSurfaceContent,
  overlayContent,
}: {
  /** children that MAY request pointer lock by click-bubbling */
  lockSurfaceContent: ReactNode
  /** ordinary interactive UI that must NEVER trigger pointer lock */
  overlayContent?: ReactNode
}) {
  return (
    <div className="relative h-full w-full bg-rock-950">
      <div id={WALKTHROUGH_LOCK_SURFACE_ID} className="absolute inset-0">
        {lockSurfaceContent}
      </div>
      {overlayContent}
    </div>
  )
}
