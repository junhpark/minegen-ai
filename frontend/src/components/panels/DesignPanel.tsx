import { useMutation } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { JobProgress } from '@/components/panels/JobProgress'
import { api, ApiError } from '@/api/client'
import { developmentMeshScope } from '@/components/panels/developmentMeshScope'
import { levelCoverageLines } from '@/components/panels/levelCoverage'
import { useJobPoll } from '@/components/panels/useJobPoll'
import type { DesignTab } from '@/components/panels/workflowTabs'
import { ActionButton } from '@/components/ui/ActionButton'
import { artifactTone, nextActionVariant } from '@/components/ui/presentation'
import { Metrics } from '@/components/ui/MetricRow'
import { StageSlot, WorkflowCard } from '@/components/ui/WorkflowCard'
import { MethodChangeDialog } from '@/components/panels/MethodChangeDialog'
import { MiningMethodCard } from '@/components/panels/MiningMethodCard'
import {
  PRODUCTION_ACTION,
  PRODUCTION_UNIT_NOUN,
  productionKindOf,
  productionSummary,
} from '@/scene/production'
import { activateScenarioRevision } from '@/stores/scenarioSession'
import {
  afterCapabilityGraphRegen,
  afterDevelopmentMeshRegen,
  afterLevelsRegen,
  afterNetworkRegen,
  afterShaftMeshRegen,
  afterShaftsRegen,
  afterStopesRegen,
  afterTimelineRegen,
} from '@/scene/invalidation'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useViewerStore } from '@/stores/viewerStore'
import type { MiningConfig, ScenarioCreate } from '@/types/api'
import type {
  CapabilityGraphPayload,
  DevelopmentMeshReport,
  JobRecord,
  LevelsPayload,
  MiningMethodSummary,
  NetworkPayload,
  ProductionKind,
  ProductionPayload,
  ShaftMeshReport,
  ShaftsPayload,
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
  const setScene = useScenarioStore((s) => s.setScene)
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

  // Phase 09 → 21B/C production: ONE active production artifact for the
  // scenario's mining method (stopes / cuts + backfills / rooms + pillars),
  // generated through the method-generic route (rules 75–80).
  const production = scene?.stopes ?? null
  const miningMethod = scene?.miningMethod ?? null
  const generateProduction = useMutation({
    mutationFn: async () => {
      if (!scene) throw new Error('generate levels first')
      return api.generateProduction(scene.scenarioId)
    },
    onSuccess: (payload: ProductionPayload) => {
      applyScene(epoch, (current) => afterStopesRegen(current, payload))
      setLayerVisible('stopes', true)
    },
  })

  // Phase 21B/C method change = scenario PUT (rule 40: every derived artifact
  // is invalidated by the backend) followed by world regeneration — the world
  // is a pure function of the persisted document (rule 119), so the same seed
  // reproduces it — and a scene reload. The frontend submits explicit
  // parameters only (rule 124).
  // hardening H1 §4.3: a method change on a mine with a world is confirmed
  // first (the dialog lists the backend reset plan); the PUT runs on confirm
  // review round 2 B1: every opening of the confirmation is a new attempt,
  // so the dialog reads the reset plan afresh (never a cached answer)
  const [pendingMethod, setPendingMethod] = useState<{
    mining: MiningConfig
    attempt: number
  } | null>(null)
  const methodAttempt = useRef(0)
  const openMethodChange = (mining: MiningConfig) => {
    methodAttempt.current += 1
    setPendingMethod({ mining, attempt: methodAttempt.current })
  }
  const applyMethod = useMutation({
    mutationFn: async (mining: MiningConfig) => {
      if (!scene || !scenarioDoc) throw new Error('load a scenario first')
      const id = scenarioDoc.id
      const { methodParameters, ...miningBase } = mining
      // the persisted document minus its identity fields is the PUT body
      const body: Record<string, unknown> = {
        ...scenarioDoc,
        mining: methodParameters ? { ...miningBase, methodParameters } : miningBase,
      }
      delete body.id
      delete body.schemaVersion
      const updated = await api.replaceScenario(id, body as unknown as ScenarioCreate)
      // the PUT replaced the document: a NEW scenario revision (epoch + 1,
      // scene / jobs / slice / day cursor cleared) so a result of the previous
      // revision still in flight is dropped, never applied to this one
      const started = activateScenarioRevision(updated)
      await api.generateWorld(id)
      const next = await api.getScene(id)
      setScene(next, started)
      return updated
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
  // PR #54 review B3: the shaft DECLARATION (`scenario.shafts`) is a Setup
  // decision — Setup › Access (`AccessPanel`) — so applying it never resets a
  // finished design from here; this stage only PLANS the declared shafts and
  // sweeps their mesh.
  // hardening PR-2 H2-SH: the shaft excavation sweep — a leaf of the shafts
  const shaftMesh = scene?.shaftMesh ?? null
  const generateShaftMesh = useMutation({
    mutationFn: async () => {
      if (!scene) throw new Error('plan shafts first')
      return api.generateShaftMesh(scene.scenarioId)
    },
    onSuccess: (payload: ShaftMeshReport) => {
      applyScene(epoch, (current) => afterShaftMeshRegen(current, payload))
      setLayerVisible('shaftMesh', true)
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
    message(generateShafts.error) ??
    message(generateShaftMesh.error)
  const networkError = message(generateNetwork.error) ?? message(generateCapabilityGraph.error)
  const miningError =
    message(generateProduction.error) ??
    message(applyMethod.error) ??
    message(generateTimeline.error)

  return (
    <>
      {scenarioDoc ? (
        <MethodChangeDialog
          scenarioId={scenarioDoc.id}
          mining={pendingMethod?.mining ?? null}
          attempt={pendingMethod?.attempt ?? 0}
          hasWorld={scene !== null}
          onCancel={() => setPendingMethod(null)}
          onConfirm={(mining) => {
            setPendingMethod(null)
            applyMethod.mutate(mining)
          }}
        />
      ) : null}
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
        shaftMesh={shaftMesh}
        shaftMeshPending={generateShaftMesh.isPending}
        shaftMeshEnabled={
          shafts !== null &&
          shafts.status === 'SUCCESS' &&
          (shafts.metrics?.shaftCount ?? 0) > 0 &&
          !generateShaftMesh.isPending &&
          !generateShafts.isPending
        }
        onGenerateShaftMesh={() => generateShaftMesh.mutate()}
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
        scenarioIdentity={`${scenarioDoc?.id ?? ''}:${epoch}`}
        methodPending={applyMethod.isPending}
        methodEnabled={scenarioDoc !== null && scene !== null && !applyMethod.isPending}
        onApplyMethod={(mining) => (scene ? openMethodChange(mining) : applyMethod.mutate(mining))}
        production={production}
        productionPending={generateProduction.isPending}
        productionEnabled={
          levelsReady &&
          miningMethod?.implementationStatus === 'IMPLEMENTED' &&
          !generateProduction.isPending &&
          !generateLevels.isPending &&
          !applyMethod.isPending
        }
        onGenerateProduction={() => generateProduction.mutate()}
        timeline={timeline}
        timelinePending={generateTimeline.isPending}
        timelineEnabled={
          network !== null &&
          network.status !== 'FAILED' &&
          production !== null &&
          production.status !== 'FAILED' &&
          !generateTimeline.isPending &&
          !generateProduction.isPending &&
          !generateNetwork.isPending
        }
        onGenerateTimeline={() => generateTimeline.mutate()}
        developError={developError}
        networkError={networkError}
        miningError={miningError}
      />
    </>
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
  /** PR-2 H2-SH: the shaft excavation mesh (barrel · caps · drives) */
  shaftMesh: ShaftMeshReport | null
  shaftMeshPending: boolean
  shaftMeshEnabled: boolean
  onGenerateShaftMesh: () => void

  network: NetworkPayload | null
  networkPending: boolean
  networkEnabled: boolean
  onGenerateNetwork: () => void

  capabilityGraph: CapabilityGraphPayload | null
  capabilityPending: boolean
  capabilityEnabled: boolean
  onGenerateCapabilityGraph: () => void

  /** Phase 21B/C method card (null only while no scene is loaded) */
  miningMethod: MiningMethodSummary | null
  /** identity of the scenario REVISION the card edits (`id:epoch`) — its draft
   * never survives a scenario switch or a document replacement */
  scenarioIdentity: string
  methodPending: boolean
  methodEnabled: boolean
  onApplyMethod: (mining: MiningConfig) => void
  /** the ACTIVE production artifact, typed by method */
  production: ProductionPayload | null
  productionPending: boolean
  productionEnabled: boolean
  onGenerateProduction: () => void

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
      <StageSlot stages={['LEVELS', 'EXCAVATION', 'SHAFTS']}>
        <NoDesignNotice rampReady={p.rampReady} />
        <ErrorLine text={p.developError} />
      </StageSlot>

      <WorkflowCard
        stage="LEVELS"
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
        notice={
          levelCoverageLines(levels).length > 0 ? (
            <div data-testid="level-coverage">
              {levelCoverageLines(levels).map((line) => (
                <div key={line}>{line}</div>
              ))}
            </div>
          ) : null
        }
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
        stage="EXCAVATION"
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
            variant={
              tunnel === null
                ? 'secondary'
                : nextActionVariant(developmentMesh !== null, p.developmentMeshEnabled)
            }
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
        stage="EXCAVATION"
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
        stage="SHAFTS"
        title="Shafts"
        tone={artifactTone(shafts, p.shaftsPending)}
        info="Optional vertical infrastructure declared in Setup › Access (never a ramp layout family). This stage PLANS the declared shafts against the level development: each gets a collar on the terrain, one station per required level welded onto an existing level node, and a sump bottom; the shaft mesh below sweeps the plan. Changing the declaration itself is a Setup decision (it rewrites the scenario and resets the design). The ramp always remains the mine's primary access."
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
            <>
              No shaft declared — the mine stays ramp-only. To add one, choose Ramp + Shaft in Setup
              › Access (that rewrites the scenario and resets the design).
            </>
          ) : null
        }
        action={
          <ActionButton
            variant={nextActionVariant(shafts !== null, p.shaftsEnabled)}
            disabled={!p.shaftsEnabled || p.shaftSpecCount === 0}
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

      <WorkflowCard
        stage="SHAFTS"
        title="Shaft excavation"
        tone={artifactTone(p.shaftMesh, p.shaftMeshPending)}
        info="The excavation sweep of the planned shafts: a circular barrel on the vertical axis with a collar cap and a sump cap, plus one station drive per level, all on the shafts' own centerlines. It is a derivative of the shaft plan — re-planning the shafts deletes it — and it invalidates nothing else. No cage or hoist is modelled and the shaft is not a walkthrough space."
        summary={
          p.shaftMesh?.status === 'SUCCESS' ? (
            <>
              {p.shaftMesh.shaftCount ?? 0} barrel{(p.shaftMesh.shaftCount ?? 0) === 1 ? '' : 's'} ·{' '}
              {p.shaftMesh.stationAccessCount ?? 0} station drives ·{' '}
              {(p.shaftMesh.nominalExcavationVolume ?? 0).toFixed(0)} m³ nominal
            </>
          ) : null
        }
        failure={p.shaftMesh?.status === 'FAILED' ? p.shaftMesh.failureReason : null}
        notice={
          shafts === null ? (
            <>Plan the shafts first — the sweep follows the planned geometry.</>
          ) : shafts.status !== 'SUCCESS' ? (
            <>The shaft plan is FAILED; only validated shafts are swept.</>
          ) : null
        }
        action={
          <ActionButton
            variant={nextActionVariant(p.shaftMesh !== null, p.shaftMeshEnabled)}
            disabled={!p.shaftMeshEnabled}
            onClick={p.onGenerateShaftMesh}
          >
            {p.shaftMeshPending
              ? 'Sweeping shafts…'
              : p.shaftMesh
                ? 'Regenerate shaft mesh'
                : 'Generate shaft mesh'}
          </ActionButton>
        }
        details={
          p.shaftMesh?.status === 'SUCCESS' ? (
            <ul className="flex flex-col gap-y-1">
              {(p.shaftMesh.shafts ?? []).map((sh) => (
                <li key={sh.shaftId} className="text-mute">
                  <div className="text-chalk-dim">
                    {sh.shaftId} · ⌀{sh.diameter.toFixed(1)} m ·{' '}
                    {sh.barrel
                      ? `${String(sh.barrel.ringCount)} rings · ${sh.barrel.triangleCount.toLocaleString()} tris · ${sh.barrel.topology.watertight && sh.barrel.topology.manifold ? 'watertight' : 'open'}`
                      : 'no barrel'}
                  </div>
                  <div className="break-words">
                    {sh.stationAccesses.length} drives ·{' '}
                    {sh.barrel ? `mesh volume Δ ${sh.barrel.volumeDifferencePct.toFixed(3)} %` : ''}
                  </div>
                </li>
              ))}
              {(p.shaftMesh.limitations ?? []).map((l) => (
                <li key={l} className="break-words text-[10px]">
                  {l}
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
      <StageSlot stages={['NETWORK', 'CAPABILITY']}>
        <NoDesignNotice rampReady={p.rampReady} />
        <ErrorLine text={p.networkError} />
      </StageSlot>

      <WorkflowCard
        stage="NETWORK"
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
        stage="CAPABILITY"
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
  const { production, timeline, miningMethod } = p
  const tm = timeline?.metrics ?? null
  // the production KIND comes from the payload's own method when one exists,
  // else from the scenario's persisted method (both backend discriminators);
  // null = the active method has no production implementation
  const kind: ProductionKind | null = production
    ? productionKindOf(production)
    : (miningMethod?.productionKind ?? null)
  const implemented = miningMethod?.implementationStatus === 'IMPLEMENTED'
  const summary =
    production && production.status === 'SUCCESS' ? productionSummary(production) : null
  return (
    <>
      <StageSlot stages={['METHOD', 'PRODUCTION', 'SCHEDULE']}>
        <NoDesignNotice rampReady={p.rampReady} />
        <ErrorLine text={p.miningError} />
      </StageSlot>
      {miningMethod ? (
        <MiningMethodCard
          identity={p.scenarioIdentity}
          summary={miningMethod}
          pending={p.methodPending}
          enabled={p.methodEnabled}
          onApply={p.onApplyMethod}
        />
      ) : null}

      <WorkflowCard
        stage="PRODUCTION"
        title="Production"
        tone={artifactTone(production, p.productionPending)}
        info="The planned production volumes of the scenario's mining method — longhole stopes between adjacent levels, Cut & Fill lifts of cuts with their 1:1 backfills, or Room & Pillar rooms (heading and benches) with retained pillars — as orebody-aligned prisms the backend generated from the level development. Volume, tonnes and the grade proxy are deterministic planning quantities — never resources, reserves, a feasibility grade or a geotechnical pillar design."
        summary={summary}
        failure={production && production.status !== 'SUCCESS' ? production.failureReason : null}
        notice={
          miningMethod && !implemented
            ? `${miningMethod.displayName} production is not implemented in this version: no production geometry is generated and nothing is substituted from another method.`
            : null
        }
        action={
          <ActionButton
            variant={nextActionVariant(production !== null, p.productionEnabled)}
            disabled={!p.productionEnabled || !implemented || kind === null}
            onClick={p.onGenerateProduction}
          >
            {p.productionPending
              ? 'Generating…'
              : implemented && kind !== null
                ? PRODUCTION_ACTION[kind]
                : 'Not implemented'}
          </ActionButton>
        }
        details={production ? <Metrics rows={productionRows(production)} /> : null}
      />

      <WorkflowCard
        stage="SCHEDULE"
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
                tm
                  ? {
                      label: `Production tasks (${kind ? PRODUCTION_UNIT_NOUN[kind] : 'production units'})`,
                      value: tm.productionTaskCount ?? tm.stopeTaskCount,
                    }
                  : null,
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

/** Detailed production numbers per kind — every value is a backend metric. */
function productionRows(
  production: ProductionPayload,
): ({ label: string; value: string } | null)[] {
  const m = production.metrics
  if (!m) return []
  const mm3 = (v: number) => `${(v / 1e6).toFixed(2)} Mm³`
  const mt = (v: number) => `${(v / 1e6).toFixed(2)} Mt`
  if (production.method === 'CUT_AND_FILL' && 'cutCount' in m) {
    return [
      { label: 'Cuts / backfills', value: `${m.cutCount} / ${m.backfillCount}` },
      { label: 'Blocks / panels', value: `${m.blockCount} / ${m.panelCount}` },
      { label: 'Lifts', value: `${m.liftCount} over ${m.levelIntervalCount} intervals` },
      {
        label: 'Cemented sill mats',
        value: `${m.cementedBackfillCount} (${mm3(m.cementedBackfillVolumeM3)})`,
      },
      { label: 'Rib pillars (retained)', value: `${m.ribPillarCount}` },
      { label: 'Mean lift height', value: `${m.actualMeanLiftHeight.toFixed(2)} m` },
      { label: 'Mean cut length', value: `${m.actualMeanCutLength.toFixed(2)} m` },
      { label: 'Mean panel length', value: `${m.actualMeanPanelLength.toFixed(2)} m` },
      { label: 'Geometric volume', value: mm3(m.totalGeometricVolumeM3) },
      { label: 'Tonnes (planning)', value: mt(m.totalTonnes) },
      { label: 'Grade proxy', value: m.weightedMeanGradeProxy?.toFixed(2) ?? '—' },
    ]
  }
  if (production.method === 'ROOM_AND_PILLAR' && 'roomCount' in m) {
    return [
      { label: 'Rooms', value: `${m.roomCount}` },
      { label: 'Headings / benches', value: `${m.headingCount} / ${m.benchCount}` },
      { label: 'Pillars (retained)', value: `${m.pillarCount}` },
      { label: 'Mined volume', value: mm3(m.totalMinedVolumeM3) },
      { label: 'Pillar volume', value: mm3(m.totalPillarVolumeM3) },
      { label: 'Extraction fraction (geometric)', value: m.geometricExtractionFraction.toFixed(2) },
      { label: 'Tonnes (planning)', value: mt(m.totalMinedTonnes) },
      { label: 'Grade proxy', value: m.weightedMeanGradeProxy?.toFixed(2) ?? '—' },
    ]
  }
  if ('stopeCount' in m) {
    return [
      { label: 'Geometric volume', value: mm3(m.totalGeometricVolumeM3) },
      { label: 'Tonnes (planning)', value: mt(m.totalTonnes) },
      { label: 'Grade proxy', value: m.weightedMeanGradeProxy?.toFixed(2) ?? '—' },
    ]
  }
  return []
}
