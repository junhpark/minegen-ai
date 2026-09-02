import { create } from 'zustand'

/**
 * 4D timeline state (Phase 10 makes this functional).
 * `currentDay` is continuous; object states are evaluated by the backend
 * timeline, never interpolated here from year labels.
 */
export interface TimelineState {
  currentDay: number
  startDay: number
  endDay: number
  playing: boolean
  speed: 1 | 5 | 20

  setCurrentDay: (day: number) => void
  setRange: (startDay: number, endDay: number) => void
  play: () => void
  pause: () => void
  setSpeed: (speed: 1 | 5 | 20) => void
  /** Phase 17.1 §1: the day cursor and its range belong to one scenario's
   * timeline artifact and never survive a scenario change. */
  reset: () => void
}

export const useTimelineStore = create<TimelineState>()((set) => ({
  currentDay: 0,
  startDay: 0,
  endDay: 0,
  playing: false,
  speed: 1,

  setCurrentDay: (currentDay) =>
    set((s) => ({ currentDay: Math.min(Math.max(currentDay, s.startDay), s.endDay) })),
  setRange: (startDay, endDay) => set({ startDay, endDay, currentDay: startDay }),
  play: () => set({ playing: true }),
  pause: () => set({ playing: false }),
  setSpeed: (speed) => set({ speed }),
  // `speed` is a viewing preference, not scenario-derived state
  reset: () => set({ currentDay: 0, startDay: 0, endDay: 0, playing: false }),
}))
