import { Bar, BarChart, CartesianGrid, Line, LineChart, Tooltip, XAxis, YAxis } from 'recharts'
import { Metrics } from '@/components/ui/MetricRow'
import { chartRows, seriesHasValues } from '@/timeline/timeseriesView'
import type { MineAnalysisPayload, TimeseriesPayload } from '@/types/analysis'
import type { TimelinePayload } from '@/types/scene'
import { cubic, days, fmt0, tonnes } from './analysisFormat'

const TASK_ROWS_SHOWN = 300

/**
 * Hardening PR-2 H3 §8 — the Schedule tab: the MineTimeline baseline KPIs,
 * the backend time series (excavated development rock, planned mined tonnes,
 * backfill per bucket) and the task table as persisted. A synthetic
 * precedence-only planning baseline (rule 82), never a production forecast;
 * nothing is re-summed on the client.
 */
export function ScheduleBody({
  analysis,
  timeline,
  series,
  seriesError,
  seriesLoading,
}: {
  analysis: MineAnalysisPayload
  timeline: TimelinePayload | null
  series: TimeseriesPayload | null
  seriesError: string | null
  seriesLoading: boolean
}) {
  const sched = analysis.schedule
  if (sched.availability !== 'AVAILABLE') {
    return <p className="px-4 py-3 text-[11px] text-mute">{sched.reason ?? 'Schedule not available.'}</p>
  }
  const rows = series ? chartRows(series) : []
  const tick = { fontSize: 10, fill: '#8f99a3' }
  const tooltip = {
    contentStyle: { background: '#1f2328', border: '1px solid #3a3f46', fontSize: 11 },
    formatter: (v: unknown) => (typeof v === 'number' ? fmt0(v) : '—'),
  }
  return (
    <>
      <section className="border-b border-rock-700 px-4 py-3">
        <h3 className="plate mb-1.5 text-[12px] text-chalk">Baseline schedule</h3>
        <Metrics
          rows={[
            { label: 'Mine duration', value: days(sched.mineDurationDays) },
            { label: 'Ramp complete', value: days(sched.rampCompletionDay) },
            { label: 'First production', value: days(sched.firstProductionDay) },
            { label: 'Tasks', value: fmt0(sched.taskCount) },
            { label: 'Development tasks', value: fmt0(sched.developmentTaskCount) },
            { label: 'Production tasks', value: fmt0(sched.productionTaskCount) },
          ]}
        />
        <p className="mt-1 text-[10px] text-mute">
          Deterministic precedence-only baseline from typed schedule rates — a synthetic planning
          baseline, never a production forecast.
        </p>
      </section>
      <section className="border-b border-rock-700 px-4 py-3" data-testid="schedule-series">
        <h3 className="plate mb-1.5 text-[12px] text-chalk">Quantities over time (backend series)</h3>
        {seriesError ? (
          <p role="alert" className="text-[11px] text-danger">
            {seriesError}
          </p>
        ) : !series ? (
          <p className="text-[11px] text-mute">{seriesLoading ? 'Reading the time series…' : ''}</p>
        ) : series.availability !== 'AVAILABLE' ? (
          <p className="text-[11px] text-mute">{series.reason}</p>
        ) : (
          <div className="flex flex-col gap-3">
            <figure>
              <figcaption className="text-[11px] text-mute">
                {series.developmentRockVocabulary} (m³ per {fmt0(series.bucketDays)}-day bucket)
                {series.totals ? ` · total ${cubic(series.totals.developmentExcavationM3)}` : ''}
              </figcaption>
              <BarChart width={640} height={160} data={rows} margin={{ top: 8, right: 16 }}>
                <CartesianGrid stroke="#3a3f46" strokeDasharray="2 4" />
                <XAxis dataKey="day" tick={tick} tickLine={false} />
                <YAxis tick={tick} tickLine={false} width={64} />
                <Tooltip {...tooltip} />
                <Bar dataKey="developmentExcavationM3" fill="#8f99a3" isAnimationActive={false} />
              </BarChart>
            </figure>
            <figure>
              <figcaption className="text-[11px] text-mute">
                Planned mined tonnes per bucket
                {series.totals ? ` · total ${tonnes(series.totals.productionTonnes)}` : ''}
              </figcaption>
              <BarChart width={640} height={160} data={rows} margin={{ top: 8, right: 16 }}>
                <CartesianGrid stroke="#3a3f46" strokeDasharray="2 4" />
                <XAxis dataKey="day" tick={tick} tickLine={false} />
                <YAxis tick={tick} tickLine={false} width={64} />
                <Tooltip {...tooltip} />
                <Bar dataKey="productionTonnes" fill="#f2c14e" isAnimationActive={false} />
              </BarChart>
            </figure>
            {seriesHasValues(rows, 'backfillM3') && rows.some((r) => r.backfillM3 > 0) ? (
              <figure>
                <figcaption className="text-[11px] text-mute">
                  Backfill placed per bucket (m³)
                  {series.totals && series.totals.cementedBackfillM3 > 0
                    ? ` · ${cubic(series.totals.cementedBackfillM3)} cemented`
                    : ''}
                </figcaption>
                <LineChart width={640} height={140} data={rows} margin={{ top: 8, right: 16 }}>
                  <CartesianGrid stroke="#3a3f46" strokeDasharray="2 4" />
                  <XAxis dataKey="day" tick={tick} tickLine={false} />
                  <YAxis tick={tick} tickLine={false} width={64} />
                  <Tooltip {...tooltip} />
                  <Line dataKey="backfillM3" stroke="#b48ad6" dot={false} isAnimationActive={false} />
                </LineChart>
              </figure>
            ) : null}
            {series.developmentTonnes.status === 'NOT_CONFIGURED' ? (
              <p className="text-[10px] text-mute">
                Development tonnes: NOT_CONFIGURED — declare scenario.geology.hostRockDensity to
                express excavated development rock as tonnes (no default density is assumed).
              </p>
            ) : null}
          </div>
        )}
      </section>
      <section className="border-b border-rock-700 px-4 py-3">
        <h3 className="plate mb-1.5 text-[12px] text-chalk">
          Tasks{' '}
          {timeline
            ? `(${fmt0(Math.min(timeline.tasks.length, TASK_ROWS_SHOWN))} of ${fmt0(timeline.tasks.length)})`
            : ''}
        </h3>
        {timeline ? (
          <div className="readout max-h-80 overflow-y-auto text-[10px]" data-testid="schedule-tasks">
            <table className="w-full border-collapse">
              <thead>
                <tr className="text-mute">
                  <th className="text-left font-normal">Task</th>
                  <th className="text-left font-normal">Type</th>
                  <th className="text-right font-normal">Start</th>
                  <th className="text-right font-normal">End</th>
                  <th className="text-right font-normal">Days</th>
                </tr>
              </thead>
              <tbody>
                {timeline.tasks.slice(0, TASK_ROWS_SHOWN).map((t) => (
                  <tr key={t.id} className="border-t border-rock-800 text-chalk-dim">
                    <td className="py-0.5 break-all">{t.targetId}</td>
                    <td>{t.taskType}</td>
                    <td className="text-right">{fmt0(t.startDay)}</td>
                    <td className="text-right">{fmt0(t.endDay)}</td>
                    <td className="text-right">{fmt0(t.durationDays)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {timeline.tasks.length > TASK_ROWS_SHOWN ? (
              <p className="mt-1 text-mute">
                Showing the first {fmt0(TASK_ROWS_SHOWN)} tasks in persisted order; the full
                schedule is in timeline.json and the MineExchange export.
              </p>
            ) : null}
          </div>
        ) : (
          <p className="text-[11px] text-mute">The timeline artifact is not in the scene.</p>
        )}
      </section>
    </>
  )
}
