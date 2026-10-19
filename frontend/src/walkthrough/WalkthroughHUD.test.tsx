/**
 * Keyboard-only HUD contract (hotfix §2/§6): no pointer-lock affordances
 * remain, the legend teaches WASD/IJKL/R (+E only in STATIC_FINAL) and
 * the temporal snapshot label survives.
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { WalkthroughHUD } from './WalkthroughHUD'
import type { TeleportTarget } from './teleport'

const BASE = { navigationMode: 'PERSON' as const, onNavigationMode: () => {} }
const TARGETS: TeleportTarget[] = [
  { kind: 'RAMP', id: 'PORTAL', label: 'Portal', chainageM: 0 },
  { kind: 'RAMP', id: 'N:L1', label: 'Level L1', chainageM: 52 },
  {
    kind: 'LEVEL_ENTRY',
    id: 'LEVEL_ENTRY:L02',
    label: 'Level L02 entry',
    levelId: 'L02',
    elevation: 1230.4,
    chainageM: 140,
  },
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
    expect(html).toContain('Completed excavation only')
    expect(html).toContain('Return to 4D to change time')
    expect(html).not.toContain('Inspect')
  })

  it('focus cue renders the asset kind with the E prompt in static mode', () => {
    const html = renderToStaticMarkup(<WalkthroughHUD {...BASE} focusedKind="MESH_ROUTER" />)
    expect(html).toContain('MESH_ROUTER')
    expect(html).toContain('E Inspect')
  })
})

describe('third-person mode selector (PR-4 W2)', () => {
  it('names the modes and offers the truck-class select only in VEHICLE mode', () => {
    const person = renderToStaticMarkup(<WalkthroughHUD {...BASE} focusedKind={null} />)
    expect(person).toContain('1 Person')
    expect(person).toContain('2 Vehicle')
    expect(person).toContain('3 Drone')
    expect(person).not.toContain('Truck class')
    const vehicle = renderToStaticMarkup(
      <WalkthroughHUD
        {...BASE}
        navigationMode="VEHICLE"
        vehiclePreset="UG_ADT_60T"
        onVehiclePreset={() => {}}
        focusedKind={null}
      />,
    )
    expect(vehicle).toContain('Truck class')
    expect(vehicle).toContain('UG ADT 60 t · 11.6 × 3.6 × 3.4 m')
    expect(vehicle).toContain('not a specification')
    for (const key of ['W/S', 'A/D', 'IJKL', 'Camera']) expect(vehicle).toContain(key)
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
    // PR-4 W3: a level entry reads its RL, not a ramp chainage
    expect(html).toContain('Level L02 entry · RL 1230 m')
  })

  it('renders no select without targets', () => {
    const html = renderToStaticMarkup(<WalkthroughHUD {...BASE} focusedKind={null} />)
    expect(html).not.toContain('Go to')
  })
})
