import { useTimelineStore } from '@/stores/timelineStore'

/**
 * Chainage-ruler style timeline placeholder. Becomes functional in Phase 10.
 * Ticks and labels are purely presentational until a schedule exists.
 */
export function TimelinePlaceholder() {
  const { currentDay, startDay, endDay, playing, speed } = useTimelineStore()
  const hasRange = endDay > startDay
  const ticks = Array.from({ length: 11 }, (_, i) => i)

  return (
    <div className="flex h-full items-center gap-4 px-4">
      <div className="flex items-center gap-1">
        <button
          type="button"
          disabled
          className="plate rounded-sm border border-rock-700 px-2 py-1 text-[12px] text-mute"
          aria-label="jump to start"
        >
          |◀
        </button>
        <button
          type="button"
          disabled
          className="plate rounded-sm border border-rock-700 px-2 py-1 text-[12px] text-mute"
          aria-label={playing ? 'pause' : 'play'}
        >
          {playing ? '❚❚' : '▶'}
        </button>
        <span className="readout ml-1 text-[10px] text-mute">{speed}×</span>
      </div>

      <div className="relative flex-1">
        <div className="h-px w-full bg-rock-600" />
        <div className="absolute inset-x-0 top-0 flex justify-between">
          {ticks.map((t) => (
            <div key={t} className="flex flex-col items-center">
              <div className={['w-px bg-rock-600', t % 5 === 0 ? 'h-3' : 'h-1.5'].join(' ')} />
              {t % 5 === 0 ? (
                <span className="readout mt-0.5 text-[9px] text-mute">
                  {hasRange ? `d${Math.round(startDay + ((endDay - startDay) * t) / 10)}` : '—'}
                </span>
              ) : null}
            </div>
          ))}
        </div>
        <input
          type="range"
          min={startDay}
          max={endDay}
          value={currentDay}
          disabled={!hasRange}
          readOnly
          aria-label="timeline"
          className="absolute inset-x-0 -top-2 h-4 w-full cursor-not-allowed appearance-none bg-transparent accent-lamp opacity-0"
        />
      </div>

      <div className="readout w-40 text-right text-[11px] text-chalk-dim">
        <span className="text-mute">4D </span>
        {hasRange ? `day ${currentDay.toFixed(0)}` : 'no schedule · Phase 10'}
      </div>
    </div>
  )
}
