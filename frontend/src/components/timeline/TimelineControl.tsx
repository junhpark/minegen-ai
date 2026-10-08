import { useEffect, useRef } from 'react'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useTimelineStore } from '@/stores/timelineStore'
import { advancePlayback, PLAYBACK_SPEEDS } from '@/timeline/playback'

/**
 * Phase 10 timeline control (§20): playback advances `currentDay` at
 * `speed` schedule days per real second via requestAnimationFrame; at
 * endDay it clamps and auto-pauses — or, with Loop on (hardening PR-2 H3
 * §7), restarts at the start day and continues. Restart jumps to the start
 * day. The timelineStore stays the UI state source; the range comes from the
 * backend timeline artifact and the clock never modifies it.
 */
export function TimelineControl() {
  const timeline = useScenarioStore((s) => s.scene?.timeline ?? null)
  const { currentDay, startDay, endDay, playing, speed } = useTimelineStore()
  const setCurrentDay = useTimelineStore((s) => s.setCurrentDay)
  const setRange = useTimelineStore((s) => s.setRange)
  const play = useTimelineStore((s) => s.play)
  const pause = useTimelineStore((s) => s.pause)
  const restart = useTimelineStore((s) => s.restart)
  const loop = useTimelineStore((s) => s.loop)
  const setLoop = useTimelineStore((s) => s.setLoop)
  const setSpeed = useTimelineStore((s) => s.setSpeed)

  // hydrate/reset the range from the backend timeline (§20/§25)
  const active = timeline?.status === 'SUCCESS'
  useEffect(() => {
    if (active && timeline) {
      setRange(timeline.startDay, timeline.endDay)
    } else {
      pause()
      setRange(0, 0)
    }
  }, [active, timeline, setRange, pause])

  const frame = useRef<number | null>(null)
  const last = useRef<number | null>(null)
  useEffect(() => {
    if (!playing) {
      last.current = null
      return
    }
    const tick = (t: number) => {
      const store = useTimelineStore.getState()
      if (last.current !== null) {
        const step = advancePlayback(
          store.currentDay,
          (t - last.current) / 1000,
          store.speed,
          store.startDay,
          store.endDay,
          store.loop,
        )
        store.setCurrentDay(step.currentDay)
        if (!step.playing) {
          store.pause() // clamped at endDay without loop
          last.current = null
          return
        }
      }
      last.current = t
      frame.current = requestAnimationFrame(tick)
    }
    frame.current = requestAnimationFrame(tick)
    return () => {
      if (frame.current !== null) cancelAnimationFrame(frame.current)
      last.current = null
    }
  }, [playing])

  if (!active) {
    return (
      <div className="flex h-full items-center px-3 text-[11px] text-mute">
        Timeline — schedule the mine development to enable 4D playback
      </div>
    )
  }

  return (
    <div className="flex h-full items-center gap-2 px-3 text-[11px]">
      <button
        type="button"
        className="plate rounded-sm border border-edge px-2 py-0.5 hover:border-lamp"
        onClick={restart}
        title="Restart at the first day"
        data-testid="timeline-restart"
      >
        Restart
      </button>
      <button
        type="button"
        className="plate rounded-sm border border-edge px-2 py-0.5 hover:border-lamp"
        onClick={() => (playing ? pause() : play())}
        data-testid="timeline-play"
      >
        {playing ? 'Pause' : 'Play'}
      </button>
      <button
        type="button"
        className={`plate rounded-sm border px-2 py-0.5 ${
          loop ? 'border-lamp text-lamp' : 'border-edge text-mute hover:border-lamp'
        }`}
        onClick={() => setLoop(!loop)}
        title="Restart at the start day when the schedule end is reached"
        aria-pressed={loop}
        data-testid="timeline-loop"
      >
        Loop
      </button>
      {PLAYBACK_SPEEDS.map((sp) => (
        <button
          key={sp}
          type="button"
          className={`plate rounded-sm border px-1.5 py-0.5 ${
            speed === sp ? 'border-lamp text-lamp' : 'border-edge text-mute hover:border-lamp'
          }`}
          onClick={() => setSpeed(sp)}
          data-testid={`timeline-speed-${String(sp)}`}
        >
          {sp}×
        </button>
      ))}
      <input
        type="range"
        min={startDay}
        max={endDay}
        step={(endDay - startDay) / 2000 || 1}
        value={currentDay}
        onChange={(e) => setCurrentDay(Number(e.target.value))}
        className="min-w-0 flex-1 accent-[#f2c14e]"
      />
      <span className="w-28 text-right tabular-nums text-chalk-dim">
        day {currentDay.toFixed(1)} / {endDay.toFixed(0)}
      </span>
    </div>
  )
}
