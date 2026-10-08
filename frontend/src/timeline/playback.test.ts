import { describe, expect, it } from 'vitest'
import { advancePlayback, PLAYBACK_SPEEDS } from './playback'

describe('4D playback arithmetic (PR-2 H3 §7)', () => {
  it('advances by speed × elapsed seconds and keeps playing before the end', () => {
    expect(advancePlayback(10, 0.5, 20, 0, 100, false)).toEqual({
      currentDay: 20,
      playing: true,
      wrapped: false,
    })
    expect(PLAYBACK_SPEEDS).toEqual([1, 5, 20])
  })
  it('clamps at the end day and pauses without loop', () => {
    expect(advancePlayback(95, 1, 20, 0, 100, false)).toEqual({
      currentDay: 100,
      playing: false,
      wrapped: false,
    })
  })
  it('restarts at the start day and continues with loop (overshoot carried)', () => {
    const step = advancePlayback(95, 1, 20, 10, 100, true)
    expect(step.playing).toBe(true)
    expect(step.wrapped).toBe(true)
    // 95 + 20 = 115 → 15 past the end → 15 into the new cycle from day 10
    expect(step.currentDay).toBeCloseTo(25, 9)
    // exactly reaching the end also wraps (the terminal day is the restart trigger)
    expect(advancePlayback(99, 0.05, 20, 10, 100, true).currentDay).toBeCloseTo(10, 9)
  })
  it('ignores a non-positive or non-finite frame delta and a degenerate range', () => {
    expect(advancePlayback(5, 0, 1, 0, 100, true)).toEqual({ currentDay: 5, playing: true, wrapped: false })
    expect(advancePlayback(5, Number.NaN, 1, 0, 100, true).currentDay).toBe(5)
    expect(advancePlayback(5, 1, 1, 0, 0, true)).toEqual({ currentDay: 0, playing: false, wrapped: false })
  })
})
