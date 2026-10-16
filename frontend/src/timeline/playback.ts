/**
 * Hardening PR-2 H3 §7 — 4D playback arithmetic (pure, no React, no store).
 *
 * The animation clock advances the DAY CURSOR only; it never touches the
 * MineTimeline artifact (the authority for every state and progress value,
 * rules 81–86). `speed` is schedule days per real second. Loop semantics
 * (directive §7): when the cursor reaches the terminal day and loop is on,
 * playback restarts at the start day and continues; without loop the cursor
 * clamps at the end day and playback pauses.
 */
export type PlaybackSpeed = 1 | 5 | 20
export const PLAYBACK_SPEEDS: readonly PlaybackSpeed[] = [1, 5, 20]

export interface PlaybackStep {
  currentDay: number
  /** false when the end was reached without loop (the clock pauses) */
  playing: boolean
  /** true when this step wrapped from the end day back to the start day */
  wrapped: boolean
}

export function advancePlayback(
  currentDay: number,
  elapsedSeconds: number,
  speed: PlaybackSpeed,
  startDay: number,
  endDay: number,
  loop: boolean,
): PlaybackStep {
  if (!(elapsedSeconds > 0) || !Number.isFinite(elapsedSeconds)) {
    return { currentDay, playing: true, wrapped: false }
  }
  if (!(endDay > startDay)) return { currentDay: startDay, playing: false, wrapped: false }
  const next = currentDay + elapsedSeconds * speed
  if (next < endDay) return { currentDay: next, playing: true, wrapped: false }
  if (!loop) return { currentDay: endDay, playing: false, wrapped: false }
  // restart at the start day and carry the overshoot into the new cycle
  const span = endDay - startDay
  const overshoot = (next - endDay) % span
  return { currentDay: startDay + overshoot, playing: true, wrapped: true }
}
