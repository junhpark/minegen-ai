import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { JobProgress } from '@/components/panels/JobProgress'
import { api, ApiError } from '@/api/client'
import { PanelSection } from '@/components/layout/PanelSection'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useViewerStore } from '@/stores/viewerStore'
import { fmtMeters } from '@/utils/format'

/** Phase 03: access-target generation. Values are echoed from the API. */
export function DesignPanel() {
  const scenario = useScenarioStore((s) => s.scenario)
  const scene = useScenarioStore((s) => s.scene)
  const setScene = useScenarioStore((s) => s.setScene)
  const setLayerVisible = useViewerStore((s) => s.setLayerVisible)
  const targets = scene?.accessTargets ?? null
  const decline = scene?.decline ?? null

  const generate = useMutation({
    mutationFn: async () => {
      if (!scene) throw new Error('generate the world first')
      const t = await api.generateTargets(scene.scenarioId)
      setScene({ ...scene, accessTargets: t, decline: null })
      setLayerVisible('accessTargets', true)
    },
  })
  // asynchronous decline job: submit → poll GET /jobs/{id} → apply result
  const [jobId, setJobId] = useState<string | null>(null)
  const generateDecline = useMutation({
    mutationFn: async () => {
      if (!scene) throw new Error('generate the world first')
      const job = await api.submitDecline(scene.scenarioId)
      setJobId(job.jobId)
    },
  })
  const job = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => api.getJob(jobId as string),
    enabled: jobId !== null,
    refetchInterval: (q) => {
      const s = q.state.data?.status
      return s === 'SUCCEEDED' || s === 'FAILED' ? false : 500
    },
  })
  const jobRunning = job.data?.status === 'QUEUED' || job.data?.status === 'RUNNING'
  useEffect(() => {
    const rec = job.data
    if (rec?.status === 'SUCCEEDED' && rec.result && scene && scene.decline !== rec.result) {
      setScene({ ...scene, decline: rec.result })
      setLayerVisible('rawSearchPath', true)
    }
  }, [job.data, scene, setScene, setLayerVisible])
  const err = generate.error ?? generateDecline.error
  const errorText =
    err instanceof ApiError ? `${err.code}: ${err.message}` : err ? err.message : null

  return (
    <PanelSection title="Access targets" tag="Phase 03">
      {scenario ? (
        <dl className="readout mb-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[11px]">
          <dt className="text-mute">Sublevel</dt>
          <dd>{fmtMeters(scenario.mining.sublevelInterval, 0)}</dd>
          <dt className="text-mute">Footwall offset</dt>
          <dd>{fmtMeters(scenario.ramp.footwallAccessOffset, 0)}</dd>
          <dt className="text-mute">Candidates</dt>
          <dd>
            {scenario.design.candidateCount} over ±
            {(scenario.design.candidateAlongStrikeSpan / 2).toFixed(0)} m
          </dd>
          <dt className="text-mute">Exclusion</dt>
          <dd>{fmtMeters(scenario.design.orebodyExclusionBuffer, 0)} buffer</dd>
        </dl>
      ) : null}
      <button
        type="button"
        onClick={() => generate.mutate()}
        disabled={!scene || generate.isPending}
        className="plate w-full rounded-sm border border-lamp px-3 py-1.5 text-[13px] text-lamp hover:bg-lamp hover:text-rock-950 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {generate.isPending
          ? 'Generating…'
          : targets
            ? 'Regenerate access targets'
            : 'Generate access targets'}
      </button>
      {errorText ? (
        <p role="alert" className="mt-2 text-[11px] text-danger">
          {errorText}
        </p>
      ) : null}
      {targets ? (
        <div className="readout mt-2 text-[11px]">
          <div className="flex justify-between text-chalk-dim">
            <span>{targets.nLevels} levels</span>
            <span>
              <span className="text-lamp">{targets.nValid} valid</span> ·{' '}
              <span className="text-danger">{targets.nRejected} rejected</span>
            </span>
          </div>
          <ul className="mt-1 max-h-40 overflow-y-auto">
            {targets.levels.map((l) => (
              <li key={l.levelId} className="flex justify-between py-0.5 text-chalk-dim">
                <span>
                  {l.levelId} <span className="text-mute">{l.elevation.toFixed(0)} m</span>
                </span>
                <span>
                  {Array.from({ length: l.nValid }, () => '●').join('')}
                  <span className="text-danger">
                    {Array.from({ length: l.nRejected }, () => '○').join('')}
                  </span>
                </span>
              </li>
            ))}
          </ul>
          <div className="mt-1 text-mute">
            Portal {targets.portalGenerated ? '(auto)' : ''}: E {targets.portal[0].toFixed(0)} N{' '}
            {targets.portal[1].toFixed(0)} Z {targets.portal[2].toFixed(0)}
          </div>
        </div>
      ) : (
        <p className="mt-2 text-[11px] text-mute">
          Generates decline access elevations and footwall candidates per level.
        </p>
      )}

      <button
        type="button"
        onClick={() => generateDecline.mutate()}
        disabled={!targets || generateDecline.isPending || jobRunning}
        className="plate mt-3 w-full rounded-sm bg-lamp px-3 py-1.5 text-[13px] text-rock-950 hover:bg-lamp-deep hover:text-chalk disabled:cursor-not-allowed disabled:opacity-40"
      >
        {generateDecline.isPending || jobRunning
          ? 'Generating decline…'
          : decline
            ? 'Regenerate decline'
            : 'Generate decline (Hybrid-A*)'}
      </button>
      {job.data && (jobRunning || job.data.status === 'FAILED') ? (
        <JobProgress job={job.data} />
      ) : null}
      {decline ? (
        <div className="readout mt-2 text-[11px]">
          <div className="flex justify-between text-chalk-dim">
            <span className={decline.status === 'SUCCESS' ? 'text-lamp' : 'text-danger'}>
              {decline.status} · {decline.completedLevels}/{decline.nLevels} levels
            </span>
            <span>{decline.totals.rawLength.toFixed(0)} m raw</span>
          </div>
          <div className="mt-1 flex justify-between text-mute">
            <span>cost {decline.totals.generalizedCost.toFixed(0)}</span>
            <span>{decline.totals.expandedStates.toLocaleString()} states</span>
            <span>{(decline.elapsedMs / 1000).toFixed(1)} s</span>
          </div>
          <ul className="mt-1 max-h-40 overflow-y-auto">
            {decline.levels.map((l) => (
              <li key={l.levelId} className="flex justify-between py-0.5 text-chalk-dim">
                <span>
                  {l.levelId}{' '}
                  <span className={l.status === 'SUCCESS' ? 'text-mute' : 'text-danger'}>
                    {l.status === 'SUCCESS' ? (l.selectedCandidateId ?? '').slice(-3) : l.status}
                  </span>
                </span>
                <span>
                  {l.candidateResults
                    .map((c) => (c.status === 'SUCCESS' ? (c.selected ? '●' : '○') : '×'))
                    .join('')}
                </span>
              </li>
            ))}
          </ul>
          <div className="mt-1 text-mute">
            raw Hybrid-A* centerline · not an engineering design (rule 11)
          </div>
        </div>
      ) : null}
    </PanelSection>
  )
}
