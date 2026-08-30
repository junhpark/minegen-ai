import { useEffect, useRef } from 'react'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useTimelineStore } from '@/stores/timelineStore'

const SPEEDS = [1, 5, 20] as const

/**
 * Phase 10 timeline control (§20): playback advances `currentDay` at
 * `speed` schedule days per real second via requestAnimationFrame; at
 * endDay it clamps and auto-pauses. The timelineStore stays the UI state
 * source; the range comes from the backend timeline artifact.
 */
export function TimelineControl() {
  const timeline = useScenarioStore((s) => s.scene?.timeline ?? null)
  const { currentDay, startDay, endDay, playing, speed } = useTimelineStore()
  const setCurrentDay = useTimelineStore((s) => s.setCurrentDay)
  const setRange = useTimelineStore((s) => s.setRange)
  const play = useTimelineStore((s) => s.play)
  const pause = useTimelineStore((s) => s.pause)
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
        const next = store.currentDay + ((t - last.current) / 1000) * store.speed
        if (next >= store.endDay) {
          store.setCurrentDay(store.endDay) // clamp…
          store.pause() // …and auto-pause at endDay
          last.current = null
          return
        }
        store.setCurrentDay(next)
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
        Timeline — generate the Phase 10 planning timeline to enable 4D playback
      </div>
    )
  }

  return (
    <div className="flex h-full items-center gap-2 px-3 text-[11px]">
      <button
        type="button"
        className="plate rounded-sm border border-edge px-2 py-0.5 hover:border-lamp"
        onClick={() => setCurrentDay(startDay)}
        title="Jump to start"
      >
        |&lt;
      </button>
      <button
        type="button"
        className="plate rounded-sm border border-edge px-2 py-0.5 hover:border-lamp"
        onClick={() => (playing ? pause() : play())}
      >
        {playing ? 'Pause' : 'Play'}
      </button>
      {SPEEDS.map((sp) => (
        <button
          key={sp}
          type="button"
          className={`plate rounded-sm border px-1.5 py-0.5 ${
            speed === sp ? 'border-lamp text-lamp' : 'border-edge text-mute hover:border-lamp'
          }`}
          onClick={() => setSpeed(sp)}
        >
          {sp}x
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
