/**
 * Keyboard-only HUD contract (hotfix §2/§6): no pointer-lock affordances
 * remain, the legend teaches WASD/IJKL/R (+E only in STATIC_FINAL) and
 * the temporal snapshot label survives.
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { WalkthroughHUD } from './WalkthroughHUD'

const BASE = { navigationMode: 'PERSON' as const, onNavigationMode: () => {} }
const TARGETS = [
  { id: 'PORTAL', label: 'Portal', chainageM: 0 },
  { id: 'N:L1', label: 'Level L1', chainageM: 52 },
]

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

describe('level teleport select (hotfix 2)', () => {
  it('renders Go to… with the offered stations', () => {
    const html = renderToStaticMarkup(
      <WalkthroughHUD
        {...BASE}
        focusedKind={null}
        teleportTargets={TARGETS}
        onTeleport={() => {}}
      />,
    )
    expect(html).toContain('Go to')
    expect(html).toContain('Portal')
    expect(html).toContain('Level L1')
    expect(html).toContain('CH 52 m')
  })

  it('renders no select without targets', () => {
    const html = renderToStaticMarkup(<WalkthroughHUD {...BASE} focusedKind={null} />)
    expect(html).not.toContain('Go to')
  })
})
