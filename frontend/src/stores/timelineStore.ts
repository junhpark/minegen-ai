import { create } from 'zustand'
import type { PlaybackSpeed } from '@/timeline/playback'

/**
 * 4D timeline state (Phase 10 makes this functional).
 * `currentDay` is continuous; object states are evaluated by the backend
 * timeline, never interpolated here from year labels. Hardening PR-2 H3 §7:
 * `loop` restarts playback at the start day when the terminal day is
 * reached; `restart` jumps to the start day. Both are viewing state — no
 * clock ever modifies the MineTimeline artifact.
 */
export interface TimelineState {
  currentDay: number
  startDay: number
  endDay: number
  playing: boolean
  speed: PlaybackSpeed
  loop: boolean

  setCurrentDay: (day: number) => void
  setRange: (startDay: number, endDay: number) => void
  play: () => void
  pause: () => void
  restart: () => void
  setLoop: (loop: boolean) => void
  setSpeed: (speed: PlaybackSpeed) => void
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
  loop: false,

  setCurrentDay: (currentDay) =>
    set((s) => ({ currentDay: Math.min(Math.max(currentDay, s.startDay), s.endDay) })),
  setRange: (startDay, endDay) => set({ startDay, endDay, currentDay: startDay }),
  play: () => set({ playing: true }),
  pause: () => set({ playing: false }),
  restart: () => set((s) => ({ currentDay: s.startDay })),
  setLoop: (loop) => set({ loop }),
  setSpeed: (speed) => set({ speed }),
  // `speed` and `loop` are viewing preferences, not scenario-derived state
  reset: () => set({ currentDay: 0, startDay: 0, endDay: 0, playing: false }),
}))
