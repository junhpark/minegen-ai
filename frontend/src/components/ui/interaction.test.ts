/**
 * Phase 20E §26 — the interaction rules of the panel primitives.
 *
 * The primitives delegate their handlers to these pure functions, so the
 * dismiss / movement / toggle behaviour is pinned here and the components'
 * rendered states are pinned in their own markup tests.
 */
import { describe, expect, it } from 'vitest'
import { isActivateKey, isDismissKey, isOutside, nextTabId, toggled } from './interaction'

describe('isDismissKey', () => {
  it('Escape closes an open popover or disclosure', () => {
    expect(isDismissKey('Escape')).toBe(true)
    expect(isDismissKey('Esc')).toBe(true)
  })

  it('no other key closes it — including keys that only move focus', () => {
    for (const k of ['Enter', ' ', 'Tab', 'ArrowDown', 'a', 'Backspace']) {
      expect(isDismissKey(k)).toBe(false)
    }
  })
})

describe('isActivateKey', () => {
  it('only Enter / Space activate', () => {
    expect(isActivateKey('Enter')).toBe(true)
    expect(isActivateKey(' ')).toBe(true)
    expect(isActivateKey('Spacebar')).toBe(true)
    expect(isActivateKey('Escape')).toBe(false)
    // hover is not an activation: there is no pointer key at all
    expect(isActivateKey('MouseOver')).toBe(false)
  })
})

describe('toggled', () => {
  it('flips the open state', () => {
    expect(toggled(false)).toBe(true)
    expect(toggled(true)).toBe(false)
  })
})

describe('nextTabId', () => {
  const ids = ['LAYOUT', 'DEVELOP', 'NETWORK', 'MINING'] as const

  it('ArrowRight / ArrowLeft move one tab and wrap', () => {
    expect(nextTabId(ids, 'LAYOUT', 'ArrowRight')).toBe('DEVELOP')
    expect(nextTabId(ids, 'MINING', 'ArrowRight')).toBe('LAYOUT')
    expect(nextTabId(ids, 'DEVELOP', 'ArrowLeft')).toBe('LAYOUT')
    expect(nextTabId(ids, 'LAYOUT', 'ArrowLeft')).toBe('MINING')
  })

  it('ArrowDown / ArrowUp mirror right / left', () => {
    expect(nextTabId(ids, 'LAYOUT', 'ArrowDown')).toBe('DEVELOP')
    expect(nextTabId(ids, 'LAYOUT', 'ArrowUp')).toBe('MINING')
  })

  it('Home / End jump to the ends', () => {
    expect(nextTabId(ids, 'NETWORK', 'Home')).toBe('LAYOUT')
    expect(nextTabId(ids, 'NETWORK', 'End')).toBe('MINING')
  })

  it('returns null for every non-movement key, so the event is left alone', () => {
    for (const k of ['Enter', ' ', 'Tab', 'Escape', 'x']) {
      expect(nextTabId(ids, 'LAYOUT', k)).toBeNull()
    }
  })

  it('returns null for an unknown current id or an empty tab list', () => {
    expect(nextTabId(ids, 'NOPE' as unknown as (typeof ids)[number], 'ArrowRight')).toBeNull()
    expect(nextTabId([], 'LAYOUT' as never, 'ArrowRight')).toBeNull()
  })
})

describe('isOutside', () => {
  it('a click on the container or its descendant is inside', () => {
    const child = { nodeType: 1 }
    const container = { contains: (n: unknown) => n === child || n === container }
    expect(isOutside(container, child)).toBe(false)
    expect(isOutside(container, container)).toBe(false)
  })

  it('a click elsewhere, or on a non-element target, is outside', () => {
    const container = { contains: () => false }
    expect(isOutside(container, { nodeType: 1 })).toBe(true)
    expect(isOutside(container, null)).toBe(true)
    expect(isOutside(container, 'window')).toBe(true)
  })

  it('with no container there is nothing to close', () => {
    expect(isOutside(null, null)).toBe(false)
  })
})
