/**
 * Keyboard-only HUD contract (hotfix §2/§6): no pointer-lock affordances
 * remain, the legend teaches WASD/IJKL/R (+E only in STATIC_FINAL) and
 * the temporal snapshot label survives.
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { WalkthroughHUD } from './WalkthroughHUD'

const BASE = { navigationMode: 'PERSON' as const, onNavigationMode: () => {} }

describe('walkthrough HUD (keyboard-only)', () => {
  it('shows the keyboard legend and no pointer-lock remnants', () => {
    const html = renderToStaticMarkup(<WalkthroughHUD {...BASE} focusedKind={null} />)
    for (const label of ['WASD', 'IJKL', 'Reset', 'Inspect']) expect(html).toContain(label)
    for (const gone of ['Click to enter', 'Mouse', 'ESC', 'Release']) {
      expect(html).not.toContain(gone)
    }
  })

  it('temporal variant keeps the snapshot label and drops E Inspect', () => {
    const html = renderToStaticMarkup(
      <WalkthroughHUD {...BASE} focusedKind={null} snapshotDay={420.5} />,
    )
    expect(html).toContain('Day 420.5')
    expect(html).toContain('Timeline snapshot')
    expect(html).toContain('Completed decline only')
    expect(html).toContain('Return to 4D to change time')
    expect(html).not.toContain('Inspect')
  })

  it('focus cue renders the asset kind with the E prompt in static mode', () => {
    const html = renderToStaticMarkup(<WalkthroughHUD {...BASE} focusedKind="MESH_ROUTER" />)
    expect(html).toContain('MESH_ROUTER')
    expect(html).toContain('E Inspect')
  })
})
