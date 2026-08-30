/**
 * PR #11 blocker 2 regression: DOM ownership between the pointer-lock
 * request surface and ordinary interactive UI. The inspector (overlay
 * content) must render as a SIBLING outside #walkthrough-lock-surface so
 * its clicks can never bubble into drei PointerLockControls' native click
 * listener and re-lock the pointer after ESC.
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { WALKTHROUGH_LOCK_SURFACE_ID } from '@/walkthrough/lockSurface'
import { MineViewportShell } from './MineViewportShell'

describe('viewport lock-surface DOM ownership (PR #11 blocker 2)', () => {
  it('renders overlay content OUTSIDE the lock surface, lock content inside', () => {
    const html = renderToStaticMarkup(
      <MineViewportShell
        lockSurfaceContent={<span data-testid="canvas-and-hud">canvas</span>}
        overlayContent={<aside data-testid="inspector">inspector</aside>}
      />,
    )
    const openTag = html.indexOf(`id="${WALKTHROUGH_LOCK_SURFACE_ID}"`)
    expect(openTag).toBeGreaterThan(-1)
    // the lock-surface div closes before the overlay begins
    const lockDivEnd = html.indexOf('</div>', openTag)
    const inspectorAt = html.indexOf('data-testid="inspector"')
    const canvasAt = html.indexOf('data-testid="canvas-and-hud"')
    expect(canvasAt).toBeGreaterThan(openTag)
    expect(canvasAt).toBeLessThan(lockDivEnd) // lockable content inside
    expect(inspectorAt).toBeGreaterThan(lockDivEnd) // inspector is a sibling AFTER it
  })

  it('keeps the lock surface mounted even with no overlay (persistent selector)', () => {
    const html = renderToStaticMarkup(<MineViewportShell lockSurfaceContent={<span />} />)
    expect(html).toContain(`id="${WALKTHROUGH_LOCK_SURFACE_ID}"`)
  })
})
