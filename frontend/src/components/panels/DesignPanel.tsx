import { useMutation } from '@tanstack/react-query'
import { useEffect } from 'react'
import { JobProgress } from '@/components/panels/JobProgress'
import { api, ApiError } from '@/api/client'
import { PanelSection } from '@/components/layout/PanelSection'
import { useJobPoll } from '@/components/panels/useJobPoll'
import {
  afterDevelopmentMeshRegen,
  afterLevelsRegen,
  afterNetworkRegen,
  afterStopesRegen,
  afterTimelineRegen,
} from '@/scene/invalidation'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useViewerStore } from '@/stores/viewerStore'
import type {
  DevelopmentMeshReport,
  LevelsPayload,
  StopesPayload,
  TimelinePayload,
  TunnelMeshReport,
} from '@/types/scene'

/**
 * Mine development chain over the ACTIVE Effective Ramp (closeout v3 §1):
 * Level development (Phase 08) → excavation meshes (Phase 06 ramp tunnel +
 * Phase 20B development mesh) → Network (Phase 07) → Stopes (Phase 09) →
 * Timeline (Phase 10). Every value is echoed from the backend; the legacy
 * Phase 03–05 decline workflow lives in the separate Advanced section.
 */
export function DesignPanel() {
  const scene = useScenarioStore((s) => s.scene)
  // Phase 17.1 §1: derived results are written through `applyScene`, which
  // re-reads the scene INSIDE the store and drops any write whose epoch is
  // no longer active.
  const applyScene = useScenarioStore((s) => s.applyScene)
  const epoch = useScenarioStore((s) => s.epoch)
  const jobs = useScenarioStore((s) => s.jobs)
  const setJob = useScenarioStore((s) => s.setJob)
  const setLayerVisible = useViewerStore((s) => s.setLayerVisible)
  // Phase 20A: `smoothedDecline` is the ACTIVE effective ramp (legacy or layout-v2)
  const smoothed = scene?.smoothedDecline ?? null
  const rampSource = scene?.rampSource.activeSource ?? 'LEGACY'
  const tunnel = scene?.tunnelMesh ?? null
  const developmentMesh = scene?.developmentMesh ?? null
  const rampReady = smoothed !== null && smoothed.status !== 'FAILED'

  // Phase 06 tunnel-mesh job: submit → poll → apply tunnelMesh report
  const tunnelJobId = jobs.tunnel
  const generateTunnel = useMutation({
    mutationFn: async () => {
      if (!scene) throw new Error('activate a ramp first')
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
  const levels = scene?.levels ?? null
  const generateLevels = useMutation({
    mutationFn: async () => {
      if (!scene) throw new Error('activate a ramp first')
      return api.generateLevels(scene.scenarioId)
    },
    onSuccess: (payload: LevelsPayload) => {
      // rules 74/79: levels regeneration invalidates development mesh +
      // network + stopes (tunnel kept)
      applyScene(epoch, (current) => afterLevelsRegen(current, payload))
      setLayerVisible('levels', true)
      setLayerVisible('crosscuts', true)
    },
  })

  // closeout v3 §4: development mesh job (LEVEL_ACCESS / DRIFT / CROSSCUT)
  const devMeshJobId = jobs.developmentMesh
  const generateDevelopmentMesh = useMutation({
    mutationFn: async () => {
      if (!scene) throw new Error('generate levels first')
      const started = epoch
      const job = await api.submitDevelopmentMesh(scene.scenarioId)
      setJob('developmentMesh', job.jobId, started)
    },
  })
  const devMeshJob = useJobPoll('developmentMesh', devMeshJobId, epoch, 400)
  const devMeshRunning =
    devMeshJob.data?.status === 'QUEUED' || devMeshJob.data?.status === 'RUNNING'
  useEffect(() => {
    const rec = devMeshJob.data
    if (rec?.status === 'SUCCEEDED' && rec.result) {
      applyScene(epoch, (current) =>
        current.developmentMesh === rec.result
          ? current
          : afterDevelopmentMeshRegen(current, rec.result as DevelopmentMeshReport),
      )
      setLayerVisible('developmentMesh', true)
    }
  }, [devMeshJob.data, epoch, applyScene, setLayerVisible])

  // Phase 09 stopes: synchronous planned-stope generation (rules 75–80).
  const stopes = scene?.stopes ?? null
  const generateStopes = useMutation({
    mutationFn: async () => {
      if (!scene) throw new Error('generate levels first')
      return api.generateStopes(scene.scenarioId)
    },
    onSuccess: (payload: StopesPayload) => {
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
      applyScene(epoch, (current) => afterTimelineRegen(current, payload))
    },
  })

  // Phase 07/08 network
  const generateNetwork = useMutation({
    mutationFn: async () => {
      if (!scene) throw new Error('generate levels first')
      return api.generateNetwork(scene.scenarioId)
    },
    onSuccess: (payload) => {
      applyScene(epoch, (current) => afterNetworkRegen(current, payload))
      setLayerVisible('network', true)
    },
  })

  const err =
    generateTunnel.error ??
    generateDevelopmentMesh.error ??
    generateLevels.error ??
    generateNetwork.error ??
    generateStopes.error ??
    generateTimeline.error
  const errorText =
    err instanceof ApiError ? `${err.code}: ${err.message}` : err ? err.message : null
  const levelsReady = levels !== null && levels.status !== 'FAILED'
  // the development mesh sweeps whatever the owning artifacts hold: level
  // accesses (layout-v2) and/or level developments — an implicit body with
  // no level development (typed boundary) still gets its access branches
  const developmentMeshReady =
    levelsReady || (rampSource === 'LAYOUT_V2' && scene?.levelAccesses != null)

  return (
    <PanelSection title="Mine development" tag="Phase 06–10">
      <p className="mb-2 text-[11px] leading-relaxed text-mute">
        Built on the active design
        {rampSource === 'LAYOUT_V2'
          ? ` (Layout v2${smoothed?.candidateId ? ` · ${smoothed.candidateId}` : ''})`
          : smoothed
            ? ' (legacy decline)'
            : ''}
        : level access → level development → excavation meshes → network → stopes → timeline.
      </p>
      {!rampReady ? (
        <p className="mb-2 rounded-sm border border-rock-700 bg-rock-900/70 px-2 py-1.5 text-[11px] leading-relaxed text-chalk-dim">
          No active design yet: generate Layout v2 candidates and activate one above.
        </p>
      ) : null}
      {errorText ? (
        <p role="alert" className="mb-2 text-[11px] text-danger">
          {errorText}
        </p>
      ) : null}

      <button
        type="button"
        onClick={() => generateLevels.mutate()}
        disabled={!rampReady || generateLevels.isPending}
        className="plate w-full rounded-sm bg-lamp px-3 py-1.5 text-[13px] text-rock-950 hover:bg-lamp-deep hover:text-chalk disabled:cursor-not-allowed disabled:opacity-40"
      >
        {generateLevels.isPending
          ? 'Laying out levels…'
          : levels
            ? 'Regenerate level development'
            : 'Generate level development (Phase 08)'}
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
            {levels.entrySource === 'LEVEL_ACCESS'
              ? 'entries at the level-access terminals (rule 157)'
              : 'entries at the legacy Phase 05 segment ends'}
            {levels.productionDevelopment && levels.productionDevelopment.status !== 'IMPLEMENTED'
              ? ` · production development ${levels.productionDevelopment.status} (${levels.productionDevelopment.method})`
              : ''}
          </div>
        </div>
      ) : null}

      <div className="readout mt-3 mb-1 text-[10px] text-mute">Excavation meshes</div>
      <button
        type="button"
        onClick={() => generateDevelopmentMesh.mutate()}
        disabled={
          !developmentMeshReady ||
          generateDevelopmentMesh.isPending ||
          devMeshRunning ||
          generateLevels.isPending
        }
        className="plate w-full rounded-sm border border-lamp px-3 py-1.5 text-[13px] text-lamp hover:bg-lamp hover:text-rock-950 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {generateDevelopmentMesh.isPending || devMeshRunning
          ? 'Sweeping development mesh…'
          : developmentMesh
            ? 'Regenerate development mesh'
            : 'Generate development mesh (access · drift · crosscut)'}
      </button>
      {devMeshJob.data && (devMeshRunning || devMeshJob.data.status === 'FAILED') ? (
        <JobProgress job={devMeshJob.data} />
      ) : null}
      {developmentMesh ? (
        <div className="readout mt-2 text-[11px]">
          <div className="flex justify-between text-chalk-dim">
            <span className={developmentMesh.status === 'SUCCESS' ? 'text-lamp' : 'text-danger'}>
              {developmentMesh.status}
            </span>
            {developmentMesh.status === 'SUCCESS' && developmentMesh.byKind ? (
              <span>
                {developmentMesh.byKind.LEVEL_ACCESS.developmentCount} access ·{' '}
                {developmentMesh.byKind.DRIFT.developmentCount} drift ·{' '}
                {developmentMesh.byKind.CROSSCUT.developmentCount} crosscut
              </span>
            ) : null}
          </div>
          {developmentMesh.status === 'SUCCESS' ? (
            <div className="mt-1 flex justify-between text-mute">
              <span>{(developmentMesh.triangleCount ?? 0).toLocaleString()} tris</span>
              <span>{developmentMesh.primitiveCount ?? 0} draw calls</span>
              <span>{((developmentMesh.glbBytes ?? 0) / 1024).toFixed(0)} kB</span>
              <span>{(developmentMesh.generationSeconds ?? 0).toFixed(1)} s</span>
            </div>
          ) : (
            <div className="mt-1 text-danger">{developmentMesh.failureReason}</div>
          )}
          <div className="mt-1 text-mute">
            swept on the owning centerlines · CAP / OPEN endpoints · no boolean junctions (Phase
            20D)
          </div>
        </div>
      ) : null}

      <button
        type="button"
        onClick={() => generateTunnel.mutate()}
        disabled={!rampReady || generateTunnel.isPending || tunnelRunning}
        className="plate mt-2 w-full rounded-sm border border-lamp px-3 py-1.5 text-[13px] text-lamp hover:bg-lamp hover:text-rock-950 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {generateTunnel.isPending || tunnelRunning
          ? 'Sweeping ramp tunnel mesh…'
          : tunnel
            ? 'Regenerate ramp tunnel mesh'
            : 'Generate ramp tunnel mesh (Phase 06)'}
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
        onClick={() => generateNetwork.mutate()}
        disabled={
          !rampReady || !levelsReady || generateNetwork.isPending || generateLevels.isPending
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
            RAMP + LEVEL_ACCESS + DRIFT + CROSSCUT graph rebuilt from the owning artifacts (rules
            68–74, 160)
          </div>
        </div>
      ) : null}

      <button
        type="button"
        onClick={() => generateStopes.mutate()}
        disabled={!levelsReady || generateStopes.isPending || generateLevels.isPending}
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
