import { useMutation } from '@tanstack/react-query'
import { useEffect } from 'react'
import { JobProgress } from '@/components/panels/JobProgress'
import { api, ApiError } from '@/api/client'
import { developmentMeshScope } from '@/components/panels/developmentMeshScope'
import { useJobPoll } from '@/components/panels/useJobPoll'
import type { DesignTab } from '@/components/panels/workflowTabs'
import { ActionButton } from '@/components/ui/ActionButton'
import { artifactTone, nextActionVariant } from '@/components/ui/presentation'
import { Metrics } from '@/components/ui/MetricRow'
import { WorkflowCard } from '@/components/ui/WorkflowCard'
import {
  afterCapabilityGraphRegen,
  afterDevelopmentMeshRegen,
  afterLevelsRegen,
  afterNetworkRegen,
  afterShaftsRegen,
  afterStopesRegen,
  afterTimelineRegen,
} from '@/scene/invalidation'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useViewerStore } from '@/stores/viewerStore'
import type {
  CapabilityGraphPayload,
  DevelopmentMeshReport,
  JobRecord,
  LevelsPayload,
  MiningMethodSummary,
  NetworkPayload,
  ShaftsPayload,
  StopesPayload,
  TimelinePayload,
  TunnelMeshReport,
} from '@/types/scene'

/**
 * Mine development over the ACTIVE Effective Ramp. Phase 20E splits the
 * single long section into the Develop / Network / Mining workflow contexts
 * of the Design tabs; the component itself stays mounted for every tab so
 * every job poll, effect and mutation keeps exactly the pre-20E lifetime and
 * switching a tab performs no request (§19).
 *
 * Orchestration only lives here (mutations, job polling, scene
 * invalidation); `DesignPanelBody` below is pure presentation. Every value
 * is echoed from the backend and every disabled condition is the pre-20E
 * one, passed down unchanged.
 */
export function DesignPanel({ view }: { view: DesignTab }) {
  const scene = useScenarioStore((s) => s.scene)
  const scenarioDoc = useScenarioStore((s) => s.scenario)
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
  const miningMethod = scene?.miningMethod ?? null
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

  // Phase 20C.2B shafts (rules 182–184): optional infrastructure planned
  // against the level developments; regenerating them invalidates the
  // network and everything below it.
  const shafts = scene?.shafts ?? null
  const shaftSpecCount = scenarioDoc?.shafts?.specs.length ?? 0
  const generateShafts = useMutation({
    mutationFn: async () => {
      if (!scene) throw new Error('generate levels first')
      return api.generateShafts(scene.scenarioId)
    },
    onSuccess: (payload: ShaftsPayload) => {
      applyScene(epoch, (current) => afterShaftsRegen(current, payload))
      setLayerVisible('shafts', true)
    },
  })

  // Phase 20C.2B capability graph (rule 185): semantics over the network
  const capabilityGraph = scene?.capabilityGraph ?? null
  const generateCapabilityGraph = useMutation({
    mutationFn: async () => {
      if (!scene) throw new Error('generate the network first')
      return api.generateCapabilityGraph(scene.scenarioId)
    },
    onSuccess: (payload: CapabilityGraphPayload) => {
      applyScene(epoch, (current) => afterCapabilityGraphRegen(current, payload))
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

  const levelsReady = levels !== null && levels.status !== 'FAILED'
  // the development mesh sweeps whatever the owning artifacts hold: level
  // accesses (layout-v2) and/or level developments — an implicit body with
  // no level development (typed boundary) still gets its access branches
  const developmentMeshReady =
    levelsReady || (rampSource === 'LAYOUT_V2' && scene?.levelAccesses != null)

  /** Phase 20E: the error of the workflow context the user is acting in.
   * The set of mutations is unchanged; only their display is grouped. */
  const message = (e: unknown): string | null =>
    e instanceof ApiError ? `${e.code}: ${e.message}` : e ? (e as Error).message : null
  const developError =
    message(generateLevels.error) ??
    message(generateDevelopmentMesh.error) ??
    message(generateTunnel.error) ??
    message(generateShafts.error)
  const networkError = message(generateNetwork.error) ?? message(generateCapabilityGraph.error)
  const miningError = message(generateStopes.error) ?? message(generateTimeline.error)

  return (
    <DesignPanelBody
      view={view}
      rampSource={rampSource}
      candidateId={smoothed?.candidateId ?? null}
      rampReady={rampReady}
      levels={levels}
      levelsPending={generateLevels.isPending}
      levelsEnabled={rampReady && !generateLevels.isPending}
      onGenerateLevels={() => generateLevels.mutate()}
      developmentMesh={developmentMesh}
      developmentMeshJob={devMeshJob.data ?? null}
      developmentMeshBusy={generateDevelopmentMesh.isPending || devMeshRunning}
      developmentMeshEnabled={
        developmentMeshReady &&
        !generateDevelopmentMesh.isPending &&
        !devMeshRunning &&
        !generateLevels.isPending
      }
      onGenerateDevelopmentMesh={() => generateDevelopmentMesh.mutate()}
      tunnel={tunnel}
      tunnelJob={tunnelJob.data ?? null}
      tunnelBusy={generateTunnel.isPending || tunnelRunning}
      tunnelEnabled={rampReady && !generateTunnel.isPending && !tunnelRunning}
      onGenerateTunnel={() => generateTunnel.mutate()}
      shafts={shafts}
      shaftSpecCount={shaftSpecCount}
      shaftsPending={generateShafts.isPending}
      shaftsEnabled={levelsReady && !generateShafts.isPending && !generateLevels.isPending}
      onGenerateShafts={() => generateShafts.mutate()}
      network={network}
      networkPending={generateNetwork.isPending}
      networkEnabled={
        rampReady && levelsReady && !generateNetwork.isPending && !generateLevels.isPending
      }
      onGenerateNetwork={() => generateNetwork.mutate()}
      capabilityGraph={capabilityGraph}
      capabilityPending={generateCapabilityGraph.isPending}
      capabilityEnabled={
        network !== null &&
        network.status !== 'FAILED' &&
        !generateCapabilityGraph.isPending &&
        !generateNetwork.isPending
      }
      onGenerateCapabilityGraph={() => generateCapabilityGraph.mutate()}
      miningMethod={miningMethod}
      stopes={stopes}
      stopesPending={generateStopes.isPending}
      stopesEnabled={levelsReady && !generateStopes.isPending && !generateLevels.isPending}
      onGenerateStopes={() => generateStopes.mutate()}
      timeline={timeline}
      timelinePending={generateTimeline.isPending}
      timelineEnabled={
        network !== null &&
        network.status !== 'FAILED' &&
        stopes !== null &&
        stopes.status !== 'FAILED' &&
        !generateTimeline.isPending &&
        !generateStopes.isPending &&
        !generateNetwork.isPending
      }
      onGenerateTimeline={() => generateTimeline.mutate()}
      developError={developError}
      networkError={networkError}
      miningError={miningError}
    />
  )
}

export interface DesignPanelBodyProps {
  /** which Design workflow context to render (§4) */
  view: DesignTab
  rampSource: 'LEGACY' | 'LAYOUT_V2'
  candidateId: string | null
  rampReady: boolean

  levels: LevelsPayload | null
  levelsPending: boolean
  levelsEnabled: boolean
  onGenerateLevels: () => void

  developmentMesh: DevelopmentMeshReport | null
  developmentMeshJob: JobRecord | null
  developmentMeshBusy: boolean
  developmentMeshEnabled: boolean
  onGenerateDevelopmentMesh: () => void

  tunnel: TunnelMeshReport | null
  tunnelJob: JobRecord | null
  tunnelBusy: boolean
  tunnelEnabled: boolean
  onGenerateTunnel: () => void

  shafts: ShaftsPayload | null
  shaftSpecCount: number
  shaftsPending: boolean
  shaftsEnabled: boolean
  onGenerateShafts: () => void

  network: NetworkPayload | null
  networkPending: boolean
  networkEnabled: boolean
  onGenerateNetwork: () => void

  capabilityGraph: CapabilityGraphPayload | null
  capabilityPending: boolean
  capabilityEnabled: boolean
  onGenerateCapabilityGraph: () => void

  /** Phase 21A read-only method card (null only while no scene is loaded) */
  miningMethod: MiningMethodSummary | null
  stopes: StopesPayload | null
  stopesPending: boolean
  stopesEnabled: boolean
  onGenerateStopes: () => void

  timeline: TimelinePayload | null
  timelinePending: boolean
  timelineEnabled: boolean
  onGenerateTimeline: () => void

  developError: string | null
  networkError: string | null
  miningError: string | null
}

/**
 * Pure presentation of the mine-development state (testable without a store
 * or a query client). It renders ONE workflow context at a time and computes
 * no engineering value: every number is a backend field and every disabled
 * condition arrives as a prop.
 */
export function DesignPanelBody(p: DesignPanelBodyProps) {
  if (p.view === 'LAYOUT') return null
  return (
    <>
      {p.view === 'DEVELOP' ? <DevelopView {...p} /> : null}
      {p.view === 'NETWORK' ? <NetworkView {...p} /> : null}
      {p.view === 'MINING' ? <MiningView {...p} /> : null}
    </>
  )
}

/** Shown once per workflow context while no design is active (§11: a
 * prerequisite the user must act on is never hidden). */
function NoDesignNotice({ rampReady }: { rampReady: boolean }) {
  if (rampReady) return null
  return (
    <p className="border-b border-rock-700 px-4 py-2 text-[11px] leading-relaxed text-chalk-dim">
      No active design yet — generate mine-layout candidates in the Layout tab and activate one.
    </p>
  )
}

function ErrorLine({ text }: { text: string | null }) {
  if (!text) return null
  return (
    <p role="alert" className="border-b border-rock-700 px-4 py-2 text-[11px] text-danger">
      {text}
    </p>
  )
}

function DevelopView(p: DesignPanelBodyProps) {
  const { levels, developmentMesh, tunnel, shafts } = p
  const m = levels?.metrics ?? null
  // closeout v4 §1.1: an access-only sweep is a legitimate result, not a
  // missing level mesh — say so instead of leaving the user to infer it
  const devScope = developmentMeshScope(developmentMesh, levels)
  const byKind = developmentMesh?.byKind ?? null
  return (
    <>
      <NoDesignNotice rampReady={p.rampReady} />
      <ErrorLine text={p.developError} />

      <WorkflowCard
        title="Level development"
        tone={artifactTone(levels, p.levelsPending)}
        info="Drifts and crosscuts on each required level, anchored exactly at the level entry that the ramp's level access reaches. The backend owns the geometry; this panel echoes it."
        summary={
          m ? (
            <>
              {m.driftPieceCount} drift pieces · {m.crosscutCount} crosscuts
            </>
          ) : null
        }
        failure={levels && levels.status !== 'SUCCESS' ? levels.failureReason : null}
        action={
          <ActionButton
            variant={nextActionVariant(levels !== null, p.levelsEnabled)}
            disabled={!p.levelsEnabled}
            onClick={p.onGenerateLevels}
          >
            {p.levelsPending
              ? 'Laying out levels…'
              : levels
                ? 'Regenerate level development'
                : 'Generate level development'}
          </ActionButton>
        }
        details={
          levels ? (
            <Metrics
              rows={[
                m ? { label: 'Drifts', value: `${m.totalDriftLength3d.toFixed(0)} m` } : null,
                m ? { label: 'Crosscuts', value: `${m.totalCrosscutLength3d.toFixed(0)} m` } : null,
                m ? { label: 'Stations / level', value: m.stationsPerLevel } : null,
                m ? { label: 'Station pitch', value: `${m.stationPitch.toFixed(0)} m` } : null,
                {
                  label: 'Entries',
                  value:
                    levels.entrySource === 'LEVEL_ACCESS'
                      ? 'level-access terminals'
                      : 'legacy ramp segment ends',
                },
                levels.productionDevelopment &&
                levels.productionDevelopment.status !== 'IMPLEMENTED'
                  ? {
                      label: 'Production development',
                      value: `${levels.productionDevelopment.status} (${levels.productionDevelopment.method})`,
                    }
                  : null,
                { label: 'Geometry', value: levels.developmentGeometry },
              ]}
            />
          ) : null
        }
      />

      <WorkflowCard
        title="Development mesh"
        tone={artifactTone(developmentMesh, p.developmentMeshBusy)}
        info="The excavation volume of the level access, drift and crosscut centerlines, swept with the same gravity-aligned profile as the ramp tunnel. Junction openings are typed local cuts; there is no general boolean union yet, so a neighbouring tube's inner wall can stay visible at a turnout."
        summary={
          byKind ? (
            <>
              {byKind.LEVEL_ACCESS.developmentCount} access · {byKind.DRIFT.developmentCount} drift
              · {byKind.CROSSCUT.developmentCount} crosscut
            </>
          ) : null
        }
        failure={
          developmentMesh && developmentMesh.status !== 'SUCCESS'
            ? developmentMesh.failureReason
            : null
        }
        notice={
          devScope.accessOnly ? (
            <>
              {devScope.headline}
              <span className="block text-mute">{devScope.detail}</span>
            </>
          ) : null
        }
        action={
          <ActionButton
            variant={nextActionVariant(developmentMesh !== null, p.developmentMeshEnabled)}
            disabled={!p.developmentMeshEnabled}
            onClick={p.onGenerateDevelopmentMesh}
          >
            {p.developmentMeshBusy
              ? 'Sweeping development mesh…'
              : developmentMesh
                ? 'Regenerate development mesh'
                : 'Generate development mesh'}
          </ActionButton>
        }
        progress={
          p.developmentMeshJob &&
          (p.developmentMeshBusy || p.developmentMeshJob.status === 'FAILED') ? (
            <JobProgress job={p.developmentMeshJob} />
          ) : null
        }
        details={
          developmentMesh ? (
            <Metrics
              rows={[
                {
                  label: 'Triangles',
                  value: (developmentMesh.triangleCount ?? 0).toLocaleString(),
                },
                { label: 'Draw calls', value: developmentMesh.primitiveCount ?? 0 },
                {
                  label: 'Mesh size',
                  value: `${((developmentMesh.glbBytes ?? 0) / 1024).toFixed(0)} kB`,
                },
                {
                  label: 'Generated in',
                  value: `${(developmentMesh.generationSeconds ?? 0).toFixed(1)} s`,
                },
              ]}
            />
          ) : null
        }
      />

      <WorkflowCard
        title="Ramp tunnel mesh"
        tone={artifactTone(tunnel, p.tunnelBusy)}
        info="The ramp excavation volume: a closed tube swept along the validated ramp centerline with a gravity-aligned floor, so the profile never banks. Nominal volume is the profile area times the 3-D centerline length; the closed-mesh signed volume is computed separately as a quality check."
        summary={tunnel ? <TunnelSummary tunnel={tunnel} /> : null}
        failure={tunnel && tunnel.status !== 'SUCCESS' ? tunnel.failureReason : null}
        action={
          <ActionButton
            variant={nextActionVariant(tunnel !== null, p.tunnelEnabled)}
            disabled={!p.tunnelEnabled}
            onClick={p.onGenerateTunnel}
          >
            {p.tunnelBusy
              ? 'Sweeping ramp tunnel mesh…'
              : tunnel
                ? 'Regenerate ramp tunnel mesh'
                : 'Generate ramp tunnel mesh'}
          </ActionButton>
        }
        progress={
          p.tunnelJob && (p.tunnelBusy || p.tunnelJob.status === 'FAILED') ? (
            <JobProgress job={p.tunnelJob} />
          ) : null
        }
        details={
          tunnel ? (
            <Metrics
              rows={[
                { label: 'Rings', value: tunnel.ringCount },
                { label: 'Triangles', value: tunnel.triangleCount?.toLocaleString() ?? '—' },
                {
                  label: 'Nominal volume',
                  value:
                    tunnel.nominalExcavationVolume === undefined
                      ? '—'
                      : `${tunnel.nominalExcavationVolume.toFixed(0)} m³`,
                },
                {
                  label: 'Mesh volume Δ',
                  value:
                    tunnel.volumeDifferencePct === undefined || tunnel.volumeDifferencePct === null
                      ? '—'
                      : `${tunnel.volumeDifferencePct.toFixed(3)} %`,
                },
                {
                  label: 'Wall area',
                  value:
                    tunnel.excavationSurfaceArea === undefined
                      ? '—'
                      : `${tunnel.excavationSurfaceArea.toFixed(0)} m²`,
                },
              ]}
            />
          ) : null
        }
      />

      <WorkflowCard
        title="Shafts"
        tone={artifactTone(shafts, p.shaftsPending)}
        info="Optional vertical infrastructure declared in the scenario, never a ramp layout family. Each declared shaft gets a collar on the terrain, one station per required level welded onto an existing level node, and a sump bottom. The ramp always remains the mine's primary access."
        summary={
          shafts?.metrics ? (
            <>
              {shafts.metrics.shaftCount} shaft{shafts.metrics.shaftCount === 1 ? '' : 's'} ·{' '}
              {shafts.metrics.stationCount} stations ·{' '}
              {shafts.metrics.totalShaftLength3d.toFixed(0)} m sunk
            </>
          ) : null
        }
        failure={shafts && shafts.status === 'FAILED' ? shafts.failureReason : null}
        notice={
          p.shaftSpecCount === 0 ? (
            <>No shaft declared in this scenario — the mine stays ramp-only.</>
          ) : null
        }
        action={
          <ActionButton
            variant={nextActionVariant(shafts !== null, p.shaftsEnabled)}
            disabled={!p.shaftsEnabled}
            onClick={p.onGenerateShafts}
          >
            {p.shaftsPending
              ? 'Planning shafts…'
              : shafts
                ? 'Regenerate shafts'
                : `Plan shafts (${String(p.shaftSpecCount)} declared)`}
          </ActionButton>
        }
        details={
          shafts ? (
            <ul className="flex flex-col gap-y-1">
              {shafts.shafts.map((sh) => (
                <li key={sh.shaftId} className="text-mute">
                  <div className={sh.status === 'OK' ? 'text-chalk-dim' : 'text-danger'}>
                    {sh.shaftId} · {sh.role.toLowerCase()} ·{' '}
                    {sh.collarSource === 'EXPLICIT' ? 'explicit collar' : 'default collar'}
                    {sh.status === 'OK' ? '' : ` · ${sh.failureCode ?? 'FAILED'}`}
                  </div>
                  {sh.status === 'OK' ? (
                    <div className="break-words">
                      stations {sh.stations.map((st) => st.levelId).join(' ')} ·{' '}
                      {sh.capabilities.length} capabilities · collar z {sh.collar[2].toFixed(0)} m ·
                      bottom z {sh.bottom[2].toFixed(0)} m
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null
        }
      />
    </>
  )
}

function TunnelSummary({ tunnel }: { tunnel: TunnelMeshReport }) {
  if (tunnel.status !== 'SUCCESS') return null
  const closed = tunnel.watertight && tunnel.manifold && tunnel.geometricallyClosed
  // Phase 20D.1: the emitted tube is open ONLY at its typed junction
  // apertures — a normal, connected state, not a defect
  const connected =
    tunnel.watertight &&
    tunnel.manifold &&
    tunnel.baseSweepGeometricallyClosed &&
    (tunnel.junctions?.removedTriangles ?? 0) > 0
  return (
    <>
      {tunnel.ringCount} rings · {tunnel.triangleCount?.toLocaleString() ?? '—'} tris ·{' '}
      {closed ? (
        <span className="text-lamp">watertight</span>
      ) : connected ? (
        <span className="text-lamp">
          junction-connected · {tunnel.junctions!.openedEndpointCount} apertures
        </span>
      ) : (
        <span className="text-danger">open</span>
      )}
    </>
  )
}

function NetworkView(p: DesignPanelBodyProps) {
  const { network, capabilityGraph } = p
  const nm = network?.metrics ?? null
  const advisory = network?.surfacePathAdvisory?.[0] ?? null
  const cm = capabilityGraph?.metrics ?? null
  const egress = capabilityGraph?.egressAdvisory ?? null
  return (
    <>
      <NoDesignNotice rampReady={p.rampReady} />
      <ErrorLine text={p.networkError} />

      <WorkflowCard
        title="Mine network"
        tone={artifactTone(network, p.networkPending)}
        info="Where connections exist: the mine as a graph of portals, ramp junctions, level entries, junctions, stope accesses and shaft nodes, joined by ramp, level-access, drift, crosscut and shaft edges. It answers connectivity and surface-egress questions and is the topology the schedule and the infrastructure planning build on. It is rebuilt from the authoritative centerlines rather than incrementally patched."
        summary={
          nm && network?.validation ? (
            <>
              {nm.nodeCount} nodes · {nm.edgeCount} edges ·{' '}
              {network.validation.connected ? (
                <span className="text-lamp">connected</span>
              ) : (
                <span className="text-danger">split</span>
              )}
            </>
          ) : null
        }
        failure={network && network.status !== 'SUCCESS' ? network.failureReason : null}
        action={
          <ActionButton
            variant={nextActionVariant(network !== null, p.networkEnabled)}
            disabled={!p.networkEnabled}
            onClick={p.onGenerateNetwork}
          >
            {p.networkPending ? 'Building network…' : network ? 'Rebuild network' : 'Build network'}
          </ActionButton>
        }
        details={
          network ? (
            <Metrics
              rows={[
                nm ? { label: 'Ramps', value: `${nm.totalRampLength3d.toFixed(0)} m` } : null,
                nm
                  ? {
                      label: 'Drop from portal',
                      value: `${nm.verticalDropFromPortal.toFixed(0)} m`,
                    }
                  : null,
                advisory
                  ? {
                      label: 'Surface paths (advisory)',
                      value: `${String(Math.min(...advisory.perNode.map((e) => e.independentSurfacePaths)))} / ${String(advisory.requiredPaths)}`,
                    }
                  : null,
                nm?.shaftCount
                  ? {
                      label: 'Shafts',
                      value: `${nm.shaftCount} · ${nm.shaftStationCount ?? 0} stations`,
                    }
                  : null,
                nm?.shaftCount
                  ? {
                      label: 'Shaft length',
                      value: `${(nm.totalShaftLength3d ?? 0).toFixed(0)} m axis · ${(nm.totalShaftStationAccessLength3d ?? 0).toFixed(0)} m drives`,
                    }
                  : null,
              ]}
            />
          ) : null
        }
      />

      <WorkflowCard
        title="Capabilities"
        tone={artifactTone(capabilityGraph, p.capabilityPending)}
        info="What each connection MAY be used for — personnel, haulage, ventilation path, utilities, emergency egress — as typed tags over the network's node and edge ids. It is a separate layer from the network's geometry and topology, and it is never a capacity: tonnes per hour, people per hour, airflow and hoist cycles are not modelled. Dual egress is reported as a design advisory only, never as regulatory compliance."
        summary={
          cm ? (
            <>
              {cm.edgeCount} edges classified · required paths {cm.requiredPathsSatisfiedCount}/
              {cm.requiredPathCount}
            </>
          ) : null
        }
        failure={
          capabilityGraph && capabilityGraph.status !== 'SUCCESS'
            ? capabilityGraph.failureReason
            : null
        }
        action={
          <ActionButton
            variant={nextActionVariant(capabilityGraph !== null, p.capabilityEnabled)}
            disabled={!p.capabilityEnabled}
            onClick={p.onGenerateCapabilityGraph}
          >
            {p.capabilityPending
              ? 'Assigning capabilities…'
              : capabilityGraph
                ? 'Rebuild capabilities'
                : 'Build capabilities'}
          </ActionButton>
        }
        details={
          capabilityGraph ? (
            <>
              {cm ? (
                <div className="mb-1 flex flex-wrap gap-x-3 text-mute">
                  {Object.entries(cm.edgesPerCapability).map(([cap, n]) => (
                    <span key={cap}>
                      {cap.toLowerCase().replace(/_/g, ' ')} {n}
                    </span>
                  ))}
                </div>
              ) : null}
              <Metrics
                rows={[
                  cm ? { label: 'Surface nodes', value: cm.surfaceNodeCount } : null,
                  egress
                    ? {
                        label: `Egress advisory (${egress.requiredRoutes} edge-disjoint)`,
                        value: `${egress.perNode.filter((e) => e.meetsCriterion).length} / ${egress.perNode.length} nodes`,
                      }
                    : null,
                  egress ? { label: 'Surface', value: egress.surfaceNodeIds.join(', ') } : null,
                ]}
              />
            </>
          ) : null
        }
      />
    </>
  )
}

function MiningView(p: DesignPanelBodyProps) {
  const { stopes, timeline, miningMethod } = p
  const sm = stopes?.metrics ?? null
  const tm = timeline?.metrics ?? null
  const implemented = miningMethod?.implementationStatus === 'IMPLEMENTED'
  return (
    <>
      <NoDesignNotice rampReady={p.rampReady} />
      <ErrorLine text={p.miningError} />
      {/* Phase 21A: READ-ONLY method card (rule 192). The backend registry
          decides the implementation status; there is no method selector and
          an unsupported method is a feature boundary, not a mine failure. */}
      {miningMethod ? (
        <WorkflowCard
          title="Mining method"
          tone={implemented ? 'ACTIVE' : 'INACTIVE'}
          statusLabel={implemented ? 'Implemented' : 'Not implemented'}
          info="The scenario's requested mining method, as the backend mining-method registry resolves it. Longhole open stoping is implemented; the other methods are reserved and receive only the generic level development — never longhole geometry under another name. The method is a scenario parameter and is not edited here."
          summary={<span data-testid="mining-method-name">{miningMethod.displayName}</span>}
          notice={
            implemented
              ? null
              : `${miningMethod.displayName} production development and stopes are not implemented in this version. Level access and the generic footwall drift are still designed.`
          }
          details={
            <Metrics
              rows={[
                { label: 'Sublevel interval', value: `${miningMethod.sublevelInterval} m` },
                { label: 'Stope length', value: `${miningMethod.stopeLength} m` },
                { label: 'Minimum pillar', value: `${miningMethod.minimumPillar} m` },
              ]}
            />
          }
        />
      ) : null}

      <WorkflowCard
        title="Stopes"
        tone={artifactTone(stopes, p.stopesPending)}
        info="Planned longhole production volumes: orebody-aligned prisms spanning an adjacent level pair at one station, anchored on the two crosscut terminals that reach them. Volume, tonnes and the grade proxy are deterministic planning quantities — never resources, reserves or a feasibility grade."
        summary={
          sm ? (
            <>
              {sm.stopeCount} stopes · {sm.levelIntervalCount} intervals × {sm.stationsPerInterval}{' '}
              stations
            </>
          ) : null
        }
        failure={stopes && stopes.status !== 'SUCCESS' ? stopes.failureReason : null}
        action={
          <ActionButton
            variant={nextActionVariant(stopes !== null, p.stopesEnabled)}
            disabled={!p.stopesEnabled}
            onClick={p.onGenerateStopes}
          >
            {p.stopesPending ? 'Planning stopes…' : stopes ? 'Replan stopes' : 'Plan stopes'}
          </ActionButton>
        }
        details={
          stopes ? (
            <Metrics
              rows={[
                sm
                  ? {
                      label: 'Geometric volume',
                      value: `${(sm.totalGeometricVolumeM3 / 1e6).toFixed(2)} Mm³`,
                    }
                  : null,
                sm
                  ? { label: 'Tonnes (planning)', value: `${(sm.totalTonnes / 1e6).toFixed(2)} Mt` }
                  : null,
                sm
                  ? {
                      label: 'Grade proxy',
                      value: sm.weightedMeanGradeProxy?.toFixed(2) ?? '—',
                    }
                  : null,
              ]}
            />
          ) : null
        }
      />

      <WorkflowCard
        title="Schedule"
        tone={artifactTone(timeline, p.timelinePending)}
        info="An earliest-start baseline over a precedence-only task graph: each task starts when its dependencies end. There are no resource limits and no optimization, so it is a synthetic planning baseline — never a production forecast. It overlays temporal state on the existing geometry and owns no geometry itself."
        summary={
          tm ? (
            <>
              {tm.taskCount} tasks · end day {tm.endDay.toFixed(0)}
            </>
          ) : null
        }
        failure={timeline && timeline.status !== 'SUCCESS' ? timeline.failureReason : null}
        action={
          <ActionButton
            variant={nextActionVariant(timeline !== null, p.timelineEnabled)}
            disabled={!p.timelineEnabled}
            onClick={p.onGenerateTimeline}
          >
            {p.timelinePending
              ? 'Scheduling…'
              : timeline
                ? 'Reschedule development'
                : 'Schedule development'}
          </ActionButton>
        }
        details={
          timeline ? (
            <Metrics
              rows={[
                tm ? { label: 'Development tasks', value: tm.developmentTaskCount } : null,
                tm ? { label: 'Stope tasks', value: tm.stopeTaskCount } : null,
                tm
                  ? {
                      label: 'First stoping',
                      value:
                        tm.firstStopingDay !== null ? `day ${tm.firstStopingDay.toFixed(0)}` : '—',
                    }
                  : null,
              ]}
            />
          ) : null
        }
      />
    </>
  )
}
