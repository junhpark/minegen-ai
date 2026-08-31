import type { ReactNode } from 'react'
import { WALKTHROUGH_LOCK_SURFACE_ID } from '@/walkthrough/lockSurface'

/**
 * Viewport DOM ownership contract (PR #11 blocker 2, kept after the
 * keyboard-only hotfix removed pointer lock).
 *
 * The camera surface contains ONLY the canvas and the walkthrough HUD;
 * ordinary interactive UI — the walkthrough inspector card and its Close
 * button — lives OUTSIDE that element as a sibling. The split is encoded
 * structurally in this tiny component so it stays testable and no future
 * camera-input mechanism can be re-attached around ordinary UI clicks.
 */
export function MineViewportShell({
  lockSurfaceContent,
  overlayContent,
}: {
  /** canvas + HUD: the camera-input surface */
  lockSurfaceContent: ReactNode
  /** ordinary interactive UI outside the camera surface */
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
