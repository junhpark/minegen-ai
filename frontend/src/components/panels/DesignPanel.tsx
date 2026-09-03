import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { JobProgress } from '@/components/panels/JobProgress'
import { api, ApiError } from '@/api/client'
import { PanelSection } from '@/components/layout/PanelSection'
import { DESIGN_UNSUPPORTED_NOTICE, designSupported } from '@/scenario/builder'
import {
  afterLegacySmoothRegen,
  afterLegacyUpstreamRegen,
  afterLevelsRegen,
  afterNetworkRegen,
  afterStopesRegen,
  afterTimelineRegen,
} from '@/scene/invalidation'
import { useScenarioStore, type DesignJobKind } from '@/stores/scenarioStore'
import { useViewerStore } from '@/stores/viewerStore'
import { fmtMeters } from '@/utils/format'
import type {
  DeclinePayload,
  LevelsPayload,
  SmoothedDeclinePayload,
  StopesPayload,
  TimelinePayload,
  TunnelMeshReport,
} from '@/types/scene'

/** Phase 03: access-target generation. Values are echoed from the API. */
export function DesignPanel() {
  const scenario = useScenarioStore((s) => s.scenario)
  const scene = useScenarioStore((s) => s.scene)
  // Phase 17.1 §1: derived results are written through `applyScene`, which
  // re-reads the scene INSIDE the store and drops any write whose epoch is
  // no longer active. The previous `setScene({ ...scene, X })` captured the
  // manifest from the render that started the mutation, so a scenario-A job
  // resolving after scenario B loaded restored the whole stale A manifest.
  const applyScene = useScenarioStore((s) => s.applyScene)
  const epoch = useScenarioStore((s) => s.epoch)
  const jobs = useScenarioStore((s) => s.jobs)
  const setJob = useScenarioStore((s) => s.setJob)
  const setLayerVisible = useViewerStore((s) => s.setLayerVisible)
  const targets = scene?.accessTargets ?? null
  const decline = scene?.decline ?? null
  // Phase 20A: `smoothedDecline` is the ACTIVE effective ramp (legacy or
  // layout-v2); the legacy Phase 05 readout uses the raw legacy artifact
  const smoothed = scene?.smoothedDecline ?? null
  const legacySmoothed = scene?.legacySmoothedDecline ?? null
  const rampSource = scene?.rampSource.activeSource ?? 'LEGACY'
  const tunnel = scene?.tunnelMesh ?? null

  const generate = useMutation({
    mutationFn: async () => {
      if (!scene) throw new Error('generate the world first')
      const started = epoch
      const t = await api.generateTargets(scene.scenarioId)
      // rule 64: regenerated targets invalidate the decline AND its smoothing
      applyScene(started, (current) => ({
        ...afterLegacyUpstreamRegen(current),
        accessTargets: t,
        decline: null,
      }))
      setLayerVisible('accessTargets', true)
    },
  })
  // asynchronous decline job: submit → poll GET /jobs/{id} → apply result.
  // §1: the job id lives in the scenario store, so a scenario change drops
  // it (the component stays mounted and would otherwise keep polling A).
  const jobId = jobs.decline
  const generateDecline = useMutation({
    mutationFn: async () => {
      if (!scene) throw new Error('generate the world first')
      const started = epoch
      const job = await api.submitDecline(scene.scenarioId)
      setJob('decline', job.jobId, started)
    },
  })
  const job = useJobPoll('decline', jobId, epoch, 500)
  const jobRunning = job.data?.status === 'QUEUED' || job.data?.status === 'RUNNING'
  useEffect(() => {
    const rec = job.data
    if (rec?.status === 'SUCCEEDED' && rec.result) {
      // a new decline invalidates the previous smoothed artifact (rule 64)
      applyScene(epoch, (current) =>
        current.decline === rec.result
          ? current
          : {
              ...afterLegacyUpstreamRegen(current),
              decline: rec.result as DeclinePayload,
            },
      )
      setLayerVisible('rawSearchPath', true)
    }
  }, [job.data, epoch, applyScene, setLayerVisible])
  // Phase 05 smoothing job: submit → poll → apply smoothedDecline
  const smoothJobId = jobs.smooth
  const smoothDecline = useMutation({
    mutationFn: async () => {
      if (!scene) throw new Error('generate the decline first')
      const started = epoch
      const job = await api.submitSmooth(scene.scenarioId)
      setJob('smooth', job.jobId, started)
    },
  })
  const smoothJob = useJobPoll('smooth', smoothJobId, epoch, 500)
  const smoothRunning = smoothJob.data?.status === 'QUEUED' || smoothJob.data?.status === 'RUNNING'
  useEffect(() => {
    const rec = smoothJob.data
    if (rec?.status === 'SUCCEEDED' && rec.result) {
      // rule 74: a new smoothed artifact invalidates tunnel + levels + network
      // — only while LEGACY is the active ramp source (rule 151)
      applyScene(epoch, (current) =>
        current.legacySmoothedDecline === rec.result
          ? current
          : afterLegacySmoothRegen(current, rec.result as SmoothedDeclinePayload),
      )
      setLayerVisible('smoothedDecline', true)
    }
  }, [smoothJob.data, epoch, applyScene, setLayerVisible])
  // Phase 06 tunnel-mesh job: submit → poll → apply tunnelMesh report
  const tunnelJobId = jobs.tunnel
  const generateTunnel = useMutation({
    mutationFn: async () => {
      if (!scene) throw new Error('smooth the decline first')
      const started = epoch
      const job = await api.submitTunnel(scene.scenarioId)
      setJob('tunnel', job.jobId, started)
    },
  })
  const tunnelJob = useJobPoll('tunnel', tunnelJobId, epoch, 400)
  const tunnelRunning = tunnelJob.data?.status === 'QUEUED' || tunnelJob.data?.status === 'RUNNING'
  useEffect(() => {
    const rec = tunnelJob.data
    if (rec?.status === 'SUCCEEDED' && rec.result) {
      applyScene(epoch, (current) =>
        current.tunnelMesh === rec.result
          ? current
          : { ...current, tunnelMesh: rec.result as TunnelMeshReport },
      )
      setLayerVisible('tunnelMesh', true)
    }
  }, [tunnelJob.data, epoch, applyScene, setLayerVisible])
  // Phase 08 levels: synchronous deterministic developments (rules 71–74).
  // Regenerating levels invalidates the network server-side (rule 74), so
  // the displayed network report and scene overlay are cleared here too.
  const levels = scene?.levels ?? null
  const generateLevels = useMutation({
    mutationFn: async () => {
      if (!scene) throw new Error('smooth the decline first')
      return api.generateLevels(scene.scenarioId)
    },
    onSuccess: (payload: LevelsPayload) => {
      // rules 74/79: levels regeneration invalidates network + stopes (tunnel kept)
      applyScene(epoch, (current) => afterLevelsRegen(current, payload))
      setLayerVisible('levels', true)
      setLayerVisible('crosscuts', true)
    },
  })

  // Phase 09 stopes: synchronous planned-stope generation (rules 75–80).
  const stopes = scene?.stopes ?? null
  const generateStopes = useMutation({
    mutationFn: async () => {
      if (!scene) throw new Error('generate levels first')
      return api.generateStopes(scene.scenarioId)
    },
    onSuccess: (payload: StopesPayload) => {
      // rules 79/86: stope regeneration leaves tunnel/network/levels
      // untouched but invalidates the timeline
      applyScene(epoch, (current) => afterStopesRegen(current, payload))
      setLayerVisible('stopes', true)
    },
  })

  // Phase 10 timeline: deterministic precedence-only baseline (rules 81–86).
  const timeline = scene?.timeline ?? null
  const network = scene?.network ?? null
  const generateTimeline = useMutation({
    mutationFn: async () => {
      if (!scene) throw new Error('generate the network and stopes first')
      return api.generateTimeline(scene.scenarioId)
    },
    onSuccess: (payload: TimelinePayload) => {
      // rule 86: timeline regeneration touches nothing upstream
      applyScene(epoch, (current) => afterTimelineRegen(current, payload))
    },
  })

  // Phase 07/08 network: the scene manifest is the single source of truth —
  // the backend deletes network.json on upstream invalidation, the manifest
  // reload restores it, and the setScene calls mirror rules 74/79/86.
  const generateNetwork = useMutation({
    mutationFn: async () => {
      if (!scene) throw new Error('smooth the decline first')
      return api.generateNetwork(scene.scenarioId)
    },
    onSuccess: (payload) => {
      // rule 86: a rebuilt network invalidates the timeline
      applyScene(epoch, (current) => afterNetworkRegen(current, payload))
      setLayerVisible('network', true)
    },
  })

  const err =
    generate.error ??
    generateDecline.error ??
    smoothDecline.error ??
    generateTunnel.error ??
    generateLevels.error ??
    generateNetwork.error ??
    generateStopes.error ??
    generateTimeline.error
  const errorText =
    err instanceof ApiError ? `${err.code}: ${err.message}` : err ? err.message : null

  return (
    <PanelSection title="Access targets" tag="Phase 03">
      {!designSupported(scenario) ? (
        <p className="mb-2 rounded-sm border border-rock-700 bg-rock-900/70 px-2 py-1.5 text-[11px] leading-relaxed text-chalk-dim">
          {DESIGN_UNSUPPORTED_NOTICE}
        </p>
      ) : null}
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
        disabled={!scene || !designSupported(scenario) || generate.isPending}
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

      <button
        type="button"
        onClick={() => smoothDecline.mutate()}
        disabled={!decline || smoothDecline.isPending || smoothRunning || jobRunning}
        className="plate mt-3 w-full rounded-sm border border-lamp px-3 py-1.5 text-[13px] text-lamp hover:bg-lamp hover:text-rock-950 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {smoothDecline.isPending || smoothRunning
          ? 'Smoothing decline…'
          : legacySmoothed
            ? 'Re-smooth decline'
            : 'Smooth decline (Phase 05)'}
      </button>
      {smoothJob.data && (smoothRunning || smoothJob.data.status === 'FAILED') ? (
        <JobProgress job={smoothJob.data} />
      ) : null}
      {rampSource === 'LAYOUT_V2' ? (
        <p className="mt-2 text-[11px] text-mute">
          Active ramp source: Layout v2
          {smoothed?.candidateId ? ` (${smoothed.candidateId})` : ''}. The legacy smoothed decline
          is kept but not consumed downstream.
        </p>
      ) : null}
      {legacySmoothed ? (
        <div className="readout mt-2 text-[11px]">
          <div className="flex justify-between text-chalk-dim">
            <span className={legacySmoothed.status === 'SUCCESS' ? 'text-lamp' : 'text-danger'}>
              {legacySmoothed.status}
            </span>
            <span>
              {legacySmoothed.totals.segments} segments ·{' '}
              <span className="text-lamp">{legacySmoothed.totals.smoothedSegments} smoothed</span> ·{' '}
              <span className={legacySmoothed.totals.fallbackSegments > 0 ? 'text-danger' : ''}>
                {legacySmoothed.totals.fallbackSegments} fallback
              </span>
            </span>
          </div>
          <div className="mt-1 flex justify-between text-mute">
            <span>{legacySmoothed.totals.effectiveLength.toFixed(0)} m effective</span>
            <span>
              cost{' '}
              {legacySmoothed.totals.fieldCostDeltaPct === null
                ? '—'
                : `${legacySmoothed.totals.fieldCostDeltaPct.toFixed(2)}%`}
            </span>
            <span>
              min R{' '}
              {legacySmoothed.totals.minimumPlanRadius === null
                ? '—'
                : legacySmoothed.totals.minimumPlanRadius.toFixed(2)}{' '}
              m
            </span>
          </div>
          <ul className="mt-1 max-h-40 overflow-y-auto">
            {legacySmoothed.segments.map((s, i) => (
              <li key={s.levelId ?? i} className="flex justify-between py-0.5 text-chalk-dim">
                <span>
                  {s.levelId}{' '}
                  <span className={s.effectiveSource === 'SMOOTHED' ? 'text-mute' : 'text-danger'}>
                    {s.effectiveSource === 'SMOOTHED'
                      ? `${s.report.repairs > 0 ? `${String(s.report.repairs)}r ` : ''}Δ${(s.report.fieldCostDeltaPct ?? 0).toFixed(2)}%`
                      : 'RAW FALLBACK'}
                  </span>
                </span>
                <span>
                  {s.report.minPlanRadius === null ? '—' : `${s.report.minPlanRadius.toFixed(1)} m`}
                </span>
              </li>
            ))}
          </ul>
          <div className="mt-1 text-mute">
            validated effective centerline · Phase 06 tunnel input (rule 64)
          </div>
        </div>
      ) : null}

      <button
        type="button"
        onClick={() => generateTunnel.mutate()}
        disabled={
          !smoothed ||
          smoothed.status === 'FAILED' ||
          generateTunnel.isPending ||
          tunnelRunning ||
          smoothRunning ||
          jobRunning
        }
        className="plate mt-3 w-full rounded-sm border border-lamp px-3 py-1.5 text-[13px] text-lamp hover:bg-lamp hover:text-rock-950 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {generateTunnel.isPending || tunnelRunning
          ? 'Sweeping tunnel mesh…'
          : tunnel
            ? 'Regenerate tunnel mesh'
            : 'Generate tunnel mesh (Phase 06)'}
      </button>
      {tunnelJob.data && (tunnelRunning || tunnelJob.data.status === 'FAILED') ? (
        <JobProgress job={tunnelJob.data} />
      ) : null}
      {tunnel ? (
        <div className="readout mt-2 text-[11px]">
          <div className="flex justify-between text-chalk-dim">
            <span className={tunnel.status === 'SUCCESS' ? 'text-lamp' : 'text-danger'}>
              {tunnel.status}
            </span>
            {tunnel.status === 'SUCCESS' ? (
              <span>
                {tunnel.ringCount} rings · {tunnel.triangleCount} tris ·{' '}
                {tunnel.watertight && tunnel.manifold && tunnel.geometricallyClosed ? (
                  <span className="text-lamp">watertight</span>
                ) : (
                  <span className="text-danger">open</span>
                )}
              </span>
            ) : null}
          </div>
          {tunnel.status === 'SUCCESS' ? (
            <div className="mt-1 flex justify-between text-mute">
              <span>
                {tunnel.nominalExcavationVolume === undefined
                  ? '—'
                  : `${tunnel.nominalExcavationVolume.toFixed(0)} m³ nominal`}
              </span>
              <span>
                mesh Δ{' '}
                {tunnel.volumeDifferencePct === undefined || tunnel.volumeDifferencePct === null
                  ? '—'
                  : `${tunnel.volumeDifferencePct.toFixed(3)}%`}
              </span>
              <span>
                {tunnel.excavationSurfaceArea === undefined
                  ? '—'
                  : `${tunnel.excavationSurfaceArea.toFixed(0)} m² walls`}
              </span>
            </div>
          ) : (
            <div className="mt-1 text-danger">{tunnel.failureReason}</div>
          )}
          <div className="mt-1 text-mute">
            gravity-aligned sweep of the effective centerline (rules 65–67)
          </div>
        </div>
      ) : null}

      <button
        type="button"
        onClick={() => generateLevels.mutate()}
        disabled={
          !smoothed || smoothed.status === 'FAILED' || generateLevels.isPending || smoothRunning
        }
        className="plate mt-3 w-full rounded-sm border border-lamp px-3 py-1.5 text-[13px] text-lamp hover:bg-lamp hover:text-rock-950 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {generateLevels.isPending
          ? 'Laying out levels…'
          : levels
            ? 'Regenerate levels'
            : 'Generate levels (Phase 08)'}
      </button>
      {levels ? (
        <div className="readout mt-2 text-[11px]">
          <div className="flex justify-between text-chalk-dim">
            <span className={levels.status === 'SUCCESS' ? 'text-lamp' : 'text-danger'}>
              {levels.status}
            </span>
            {levels.status === 'SUCCESS' && levels.metrics ? (
              <span>
                {levels.metrics.driftPieceCount} drift pieces · {levels.metrics.crosscutCount}{' '}
                crosscuts · pitch {levels.metrics.stationPitch.toFixed(0)} m
              </span>
            ) : null}
          </div>
          {levels.status === 'SUCCESS' && levels.metrics ? (
            <div className="mt-1 flex justify-between text-mute">
              <span>{levels.metrics.totalDriftLength3d.toFixed(0)} m drifts</span>
              <span>{levels.metrics.totalCrosscutLength3d.toFixed(0)} m crosscuts</span>
              <span>{levels.metrics.stationsPerLevel} stations/level</span>
            </div>
          ) : (
            <div className="mt-1 text-danger">{levels.failureReason}</div>
          )}
          <div className="mt-1 text-mute">
            orebody-derived station lattice on the strike drift (rules 71–74)
          </div>
        </div>
      ) : null}

      <button
        type="button"
        onClick={() => generateNetwork.mutate()}
        disabled={
          !smoothed ||
          smoothed.status === 'FAILED' ||
          !levels ||
          levels.status === 'FAILED' ||
          generateNetwork.isPending ||
          generateLevels.isPending ||
          smoothRunning
        }
        className="plate mt-3 w-full rounded-sm border border-lamp px-3 py-1.5 text-[13px] text-lamp hover:bg-lamp hover:text-rock-950 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {generateNetwork.isPending
          ? 'Building network…'
          : network
            ? 'Regenerate network'
            : 'Generate network (Phase 07)'}
      </button>
      {network ? (
        <div className="readout mt-2 text-[11px]">
          <div className="flex justify-between text-chalk-dim">
            <span className={network.status === 'SUCCESS' ? 'text-lamp' : 'text-danger'}>
              {network.status}
            </span>
            {network.status === 'SUCCESS' && network.metrics && network.validation ? (
              <span>
                {network.metrics.nodeCount} nodes · {network.metrics.edgeCount} edges ·{' '}
                {network.validation.connected ? (
                  <span className="text-lamp">connected</span>
                ) : (
                  <span className="text-danger">split</span>
                )}
              </span>
            ) : null}
          </div>
          {network.status === 'SUCCESS' && network.metrics ? (
            <div className="mt-1 flex justify-between text-mute">
              <span>{network.metrics.totalRampLength3d.toFixed(0)} m ramps</span>
              <span>drop {network.metrics.verticalDropFromPortal.toFixed(0)} m</span>
              <span>
                surface paths{' '}
                {network.surfacePathAdvisory[0]
                  ? `${String(Math.min(...network.surfacePathAdvisory[0].perNode.map((e) => e.independentSurfacePaths)))}/${String(network.surfacePathAdvisory[0].requiredPaths)} advisory`
                  : '—'}
              </span>
            </div>
          ) : (
            <div className="mt-1 text-danger">{network.failureReason}</div>
          )}
          <div className="mt-1 text-mute">
            RAMP + DRIFT + CROSSCUT graph rebuilt from smoothed + levels (rules 68–74)
          </div>
        </div>
      ) : null}

      <button
        type="button"
        onClick={() => generateStopes.mutate()}
        disabled={
          !levels ||
          levels.status === 'FAILED' ||
          generateStopes.isPending ||
          generateLevels.isPending
        }
        className="plate mt-3 w-full rounded-sm border border-lamp px-3 py-1.5 text-[13px] text-lamp hover:bg-lamp hover:text-rock-950 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {generateStopes.isPending
          ? 'Planning stopes…'
          : stopes
            ? 'Regenerate stopes'
            : 'Generate stopes (Phase 09)'}
      </button>
      {stopes ? (
        <div className="readout mt-2 text-[11px]">
          <div className="flex justify-between text-chalk-dim">
            <span className={stopes.status === 'SUCCESS' ? 'text-lamp' : 'text-danger'}>
              {stopes.status}
            </span>
            {stopes.status === 'SUCCESS' && stopes.metrics ? (
              <span>
                {stopes.metrics.stopeCount} stopes · {stopes.metrics.levelIntervalCount} intervals ×{' '}
                {stopes.metrics.stationsPerInterval} stations
              </span>
            ) : null}
          </div>
          {stopes.status === 'SUCCESS' && stopes.metrics ? (
            <div className="mt-1 flex justify-between text-mute">
              <span>{(stopes.metrics.totalGeometricVolumeM3 / 1e6).toFixed(2)} Mm³</span>
              <span>{(stopes.metrics.totalTonnes / 1e6).toFixed(2)} Mt</span>
              <span>grade proxy {stopes.metrics.weightedMeanGradeProxy?.toFixed(2) ?? '—'}</span>
            </div>
          ) : (
            <div className="mt-1 text-danger">{stopes.failureReason}</div>
          )}
          <div className="mt-1 text-mute">
            planned longhole prisms anchored to Phase 08 access pairs (rules 75–80); planning
            proxies only — not reserves
          </div>
        </div>
      ) : null}

      <button
        type="button"
        onClick={() => generateTimeline.mutate()}
        disabled={
          !network ||
          network.status === 'FAILED' ||
          !stopes ||
          stopes.status === 'FAILED' ||
          generateTimeline.isPending ||
          generateStopes.isPending ||
          generateNetwork.isPending
        }
        className="plate mt-3 w-full rounded-sm border border-lamp px-3 py-1.5 text-[13px] text-lamp hover:bg-lamp hover:text-rock-950 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {generateTimeline.isPending
          ? 'Scheduling…'
          : timeline
            ? 'Regenerate timeline'
            : 'Generate timeline (Phase 10)'}
      </button>
      {timeline ? (
        <div className="readout mt-2 text-[11px]">
          <div className="flex justify-between text-chalk-dim">
            <span className={timeline.status === 'SUCCESS' ? 'text-lamp' : 'text-danger'}>
              {timeline.status}
            </span>
            {timeline.status === 'SUCCESS' && timeline.metrics ? (
              <span>
                {timeline.metrics.taskCount} tasks · {timeline.metrics.developmentTaskCount} dev ·{' '}
                {timeline.metrics.stopeTaskCount} stope
              </span>
            ) : null}
          </div>
          {timeline.status === 'SUCCESS' && timeline.metrics ? (
            <div className="mt-1 flex justify-between text-mute">
              <span>end day {timeline.metrics.endDay.toFixed(0)}</span>
              <span>
                first stoping{' '}
                {timeline.metrics.firstStopingDay !== null
                  ? `day ${timeline.metrics.firstStopingDay.toFixed(0)}`
                  : '—'}
              </span>
            </div>
          ) : (
            <div className="mt-1 text-danger">{timeline.failureReason}</div>
          )}
          <div className="mt-1 text-mute">
            deterministic precedence-only planning timeline — not a production forecast or optimized
            schedule (rules 81–86)
          </div>
        </div>
      ) : null}
    </PanelSection>
  )
}

/**
 * Poll one asynchronous design job (Phase 17.1 §1). The query key carries
 * the scenario epoch and the job id comes from the scenario store, so a
 * scenario change both stops the poll (the store cleared the id) and makes
 * it impossible for a cached scenario-A job record to be served to
 * scenario B under the same key.
 */
function useJobPoll(kind: DesignJobKind, jobId: string | null, epoch: number, intervalMs: number) {
  return useQuery({
    queryKey: ['job', kind, epoch, jobId],
    queryFn: () => api.getJob(jobId as string),
    enabled: jobId !== null,
    refetchInterval: (q) => {
      const s = q.state.data?.status
      return s === 'SUCCEEDED' || s === 'FAILED' ? false : intervalMs
    },
  })
}
