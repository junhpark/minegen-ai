import type { JobRecord } from '@/types/scene'

/** Compact progress readout for a running/finished job. Display only. */
export function JobProgress({ job }: { job: JobRecord }) {
  const p = job.progress
  const pct = Math.round((p.progress ?? 0) * 100)
  const running = job.status === 'QUEUED' || job.status === 'RUNNING'
  const color =
    job.status === 'FAILED' ? 'bg-danger' : job.status === 'SUCCEEDED' ? 'bg-ore' : 'bg-lamp'
  return (
    <div className="readout mt-2 text-[11px]" aria-live="polite">
      <div className="flex justify-between text-chalk-dim">
        <span className="plate">{running ? 'Generating decline' : job.status}</span>
        <span>{pct} %</span>
      </div>
      <div className="mt-1 h-2 w-full overflow-hidden rounded-sm bg-rock-700" role="progressbar">
        <div
          className={`h-full ${color} transition-[width] duration-300`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-chalk-dim">
        <span className="text-mute">Level</span>
        <span>
          {p.level ?? '–'} / {p.total_levels ?? '–'} {p.level_id ? `(${p.level_id})` : ''}
        </span>
        <span className="text-mute">Candidate</span>
        <span>
          {p.candidate ?? '–'} / {p.total_candidates ?? '–'}{' '}
          {p.candidate_status ? <span className="text-mute">{p.candidate_status}</span> : null}
        </span>
        <span className="text-mute">Expanded</span>
        <span>{(p.expanded_states ?? 0).toLocaleString()} states</span>
        {job.error ? (
          <>
            <span className="text-mute">Error</span>
            <span className="text-danger">{job.error.message}</span>
          </>
        ) : null}
      </div>
    </div>
  )
}
