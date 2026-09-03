import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, ApiError } from '@/api/client'
import { JobProgress } from '@/components/panels/JobProgress'
import { PanelSection } from '@/components/layout/PanelSection'
import { compareCandidates } from '@/components/panels/layoutOrder'
import { afterLayoutRegen, afterLayoutSelect, afterRampSourceChange } from '@/scene/invalidation'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useViewerStore } from '@/stores/viewerStore'
import type {
  JobRecord,
  LayoutCandidateSummary,
  LayoutV2Catalogue,
  RampSource,
  RampSourceSummary,
  WorldScene,
} from '@/types/scene'

/**
 * Phase 20A — parametric whole-mine layout (layout-v2) and the explicit
 * Effective Ramp source switch (rules 149–151). Display + intent only: the
 * backend enumerates, validates, scores, ranks, materializes and resolves
 * the active source; this panel never computes any of it.
 */
export function LayoutPanel() {
  const scene = useScenarioStore((s) => s.scene)
  const applyScene = useScenarioStore((s) => s.applyScene)
  const epoch = useScenarioStore((s) => s.epoch)
  const jobs = useScenarioStore((s) => s.jobs)
  const setJob = useScenarioStore((s) => s.setJob)
  const setLayerVisible = useViewerStore((s) => s.setLayerVisible)
  const [pick, setPick] = useState<string | null>(null)
  const [showAll, setShowAll] = useState(false)

  // the layout job (kind LAYOUT_V2) lives in the scenario store like the
  // other design jobs (§1: a scenario change drops it structurally)
  const jobId = jobs.layout
  const generate = useMutation({
    mutationFn: async () => {
      if (!scene) throw new Error('generate the world first')
      const started = epoch
      const job = await api.submitLayoutV2(scene.scenarioId)
      setJob('layout', job.jobId, started)
    },
  })
  const job = useQuery({
    queryKey: ['job', 'layout', epoch, jobId],
    queryFn: () => api.getJob(jobId as string),
    enabled: jobId !== null,
    refetchInterval: (q) => {
      const s = q.state.data?.status
      return s === 'SUCCEEDED' || s === 'FAILED' ? false : 500
    },
  })
  const running = job.data?.status === 'QUEUED' || job.data?.status === 'RUNNING'
  useEffect(() => {
    const rec = job.data
    if (rec?.status === 'SUCCEEDED' && rec.result) {
      applyScene(epoch, (current) =>
        current.layoutV2 === rec.result
          ? current
          : afterLayoutRegen(current, rec.result as LayoutV2Catalogue),
      )
      setLayerVisible('layoutV2', true)
    }
  }, [job.data, epoch, applyScene, setLayerVisible])

  const select = useMutation({
    mutationFn: async (candidateId: string) => {
      if (!scene) throw new Error('generate the world first')
      const selected = await api.selectLayoutCandidate(scene.scenarioId, candidateId)
      // rule 157: the level-access artifact is written with the selection
      const accesses = await api.getLevelAccesses(scene.scenarioId)
      return { selected, accesses }
    },
    onSuccess: ({ selected, accesses }) => {
      applyScene(epoch, (current) => afterLayoutSelect(current, selected, accesses))
      setLayerVisible('layoutV2', true)
      setLayerVisible('levelAccesses', true)
    },
  })
  const activate = useMutation({
    mutationFn: async (candidateId: string) => {
      if (!scene) throw new Error('generate the world first')
      const result = await api.activateLayoutCandidate(scene.scenarioId, candidateId)
      const accesses = await api.getLevelAccesses(scene.scenarioId)
      return { ...result, accesses }
    },
    onSuccess: ({ rampSource: src, selected: sel, accesses }) => {
      applyScene(epoch, (current) => ({
        ...afterRampSourceChange(current, src, sel),
        levelAccesses: accesses,
      }))
      setLayerVisible('smoothedDecline', true)
      setLayerVisible('levelAccesses', true)
    },
  })
  const switchSource = useMutation({
    mutationFn: async (source: RampSource) => {
      if (!scene) throw new Error('generate the world first')
      return api.setRampSource(scene.scenarioId, source)
    },
    onSuccess: (src) => {
      applyScene(epoch, (current) => afterRampSourceChange(current, src))
    },
  })

  const err = generate.error ?? select.error ?? activate.error ?? switchSource.error
  const errorText =
    err instanceof ApiError ? `${err.code}: ${err.message}` : err ? err.message : null

  return (
    <LayoutPanelBody
      scene={scene}
      pick={pick}
      showAll={showAll}
      job={job.data ?? null}
      busy={generate.isPending || running || select.isPending || activate.isPending}
      generating={generate.isPending || running}
      switching={switchSource.isPending}
      selecting={select.isPending}
      activating={activate.isPending}
      errorText={errorText}
      onPick={setPick}
      onShowAll={setShowAll}
      onGenerate={() => generate.mutate()}
      onSelect={(id) => select.mutate(id)}
      onActivate={(id) => activate.mutate(id)}
      onSwitch={(src) => switchSource.mutate(src)}
    />
  )
}

export interface LayoutPanelBodyProps {
  scene: WorldScene | null
  pick: string | null
  showAll: boolean
  job: JobRecord | null
  busy: boolean
  generating: boolean
  switching: boolean
  selecting: boolean
  activating: boolean
  errorText: string | null
  onPick: (id: string) => void
  onShowAll: (show: boolean) => void
  onGenerate: () => void
  onSelect: (id: string) => void
  onActivate: (id: string) => void
  onSwitch: (source: RampSource) => void
}

/** Pure presentation of the backend layout-v2 state (testable without a
 * store or query client). */
export function LayoutPanelBody(p: LayoutPanelBodyProps) {
  const { scene, job } = p
  const catalogue = scene?.layoutV2 ?? null
  const selected = scene?.layoutV2Selected ?? null
  const rampSource: RampSourceSummary | null = scene?.rampSource ?? null
  const candidates = catalogue
    ? [...catalogue.candidates].sort(compareCandidates).filter((c) => p.showAll || c.rank !== null)
    : []
  const active = rampSource?.activeSource ?? 'LEGACY'
  const picked = p.pick ?? catalogue?.winnerId ?? null
  const running = job?.status === 'QUEUED' || job?.status === 'RUNNING'

  return (
    <PanelSection title="Layout v2 — parametric families" tag="Phase 20A">
      <div className="readout mb-2 text-[11px]">
        <div className="mb-1 text-mute">Effective ramp source</div>
        <div className="flex gap-1" role="radiogroup" aria-label="ramp source">
          {(['LEGACY', 'LAYOUT_V2'] as const).map((src) => (
            <button
              key={src}
              type="button"
              role="radio"
              aria-checked={active === src}
              disabled={
                !scene ||
                p.switching ||
                (src === 'LAYOUT_V2' && !(rampSource?.layoutV2Selected ?? false))
              }
              onClick={() => p.onSwitch(src)}
              className={`plate flex-1 rounded-sm border px-2 py-1 text-[11px] disabled:cursor-not-allowed disabled:opacity-40 ${
                active === src
                  ? 'border-lamp bg-lamp text-rock-950'
                  : 'border-rock-700 text-chalk-dim hover:border-lamp'
              }`}
            >
              {src === 'LEGACY' ? 'Legacy (Hybrid-A*)' : 'Layout v2'}
            </button>
          ))}
        </div>
        {rampSource ? (
          <div className="mt-1 text-mute">
            {rampSource.available
              ? `${rampSource.sourceKind ?? '—'} · ${String(rampSource.segmentCount)} segments · ${rampSource.owningArtifact}`
              : active === 'LEGACY'
                ? 'no smoothed legacy decline yet'
                : 'no selected layout-v2 candidate yet'}
          </div>
        ) : null}
      </div>

      <button
        type="button"
        onClick={p.onGenerate}
        disabled={!scene || p.busy}
        className="plate w-full rounded-sm bg-lamp px-3 py-1.5 text-[13px] text-rock-950 hover:bg-lamp-deep hover:text-chalk disabled:cursor-not-allowed disabled:opacity-40"
      >
        {p.generating
          ? 'Searching layout families…'
          : catalogue
            ? 'Regenerate candidates'
            : 'Generate candidates (SPIRAL / LONGITUDINAL / SWITCHBACK)'}
      </button>
      {job && (running || job.status === 'FAILED') ? <JobProgress job={job} /> : null}
      {p.errorText ? (
        <p role="alert" className="mt-2 text-[11px] text-danger">
          {p.errorText}
        </p>
      ) : null}

      {catalogue ? (
        <div className="readout mt-2 text-[11px]">
          <div className="flex justify-between text-chalk-dim">
            <span className={catalogue.status === 'SUCCESS' ? 'text-lamp' : 'text-danger'}>
              {catalogue.status === 'SUCCESS' ? 'SUCCESS' : 'NO FEASIBLE CANDIDATE'}
            </span>
            <span>
              {catalogue.feasibleCount} feasible / {catalogue.candidateCount} enumerated
            </span>
          </div>
          <div className="mt-1 flex justify-between text-mute">
            <span>
              {catalogue.serviceableLevelCount}/{catalogue.requiredLevels.length} levels with ore
            </span>
            <span>
              clearance {catalogue.clearanceBasis}
              {catalogue.clearanceBasis === 'CONSERVATIVE'
                ? ` (−${catalogue.clearanceErrorBound.toFixed(1)} m)`
                : ''}{' '}
              ≥ {catalogue.requiredClearance.toFixed(1)} m
            </span>
          </div>
          <div className="mt-1 flex justify-between text-mute">
            <span>reach {catalogue.accessReach.toFixed(0)} m</span>
            <span>{(catalogue.performance.totalSeconds ?? 0).toFixed(1)} s</span>
            <label className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={p.showAll}
                onChange={(e) => p.onShowAll(e.target.checked)}
              />
              show infeasible
            </label>
          </div>
          <ul className="mt-1 max-h-56 overflow-y-auto" aria-label="layout candidates">
            {candidates.map((c) => (
              <li key={c.candidateId}>
                <button
                  type="button"
                  onClick={() => p.onPick(c.candidateId)}
                  aria-pressed={picked === c.candidateId}
                  className={`flex w-full flex-col py-0.5 text-left ${
                    picked === c.candidateId ? 'text-lamp' : 'text-chalk-dim'
                  }`}
                >
                  <span className="flex w-full justify-between">
                    <span>
                      {c.rank !== null ? `#${String(c.rank)} ` : ''}
                      <span className="text-mute">{c.family}</span> {shortId(c)}
                      {c.candidateId === catalogue.winnerId ? ' ★' : ''}
                      {c.candidateId === rampSource?.candidateId && active === 'LAYOUT_V2'
                        ? ' (active)'
                        : c.candidateId === selected?.candidateId
                          ? ' (selected)'
                          : ''}
                    </span>
                    <span className={c.status === 'FEASIBLE' ? '' : 'text-danger'}>
                      {c.status === 'FEASIBLE'
                        ? c.scores
                          ? c.scores.total.toFixed(3)
                          : '—'
                        : c.status}
                    </span>
                  </span>
                  <span className="flex w-full justify-between text-mute">
                    <span>
                      {c.accessibleLevels !== null
                        ? `${String(c.accessibleLevels)}/${String(c.requiredLevels)} accessible`
                        : `${String(c.screenedLevels)}/${String(c.requiredLevels)} screened`}
                      {c.diagnostics ? ` · ramp ${c.diagnostics.length3d.toFixed(0)} m` : ''}
                      {c.access ? ` · access ${c.access.totalAccessLength.toFixed(0)} m` : ''}
                    </span>
                    <span>
                      {c.scores
                        ? `D ${c.scores.development.toFixed(2)} · G ${c.scores.geology.toFixed(2)} · M ${c.scores.geometry.toFixed(2)}`
                        : c.failureReasons.join(', ')}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {picked ? (
            <CandidateDetail
              candidate={catalogue.candidates.find((c) => c.candidateId === picked) ?? null}
            />
          ) : null}
          <div className="mt-2 flex gap-1">
            <button
              type="button"
              disabled={!picked || p.busy || !isFeasible(catalogue, picked)}
              onClick={() => picked && p.onSelect(picked)}
              className="plate flex-1 rounded-sm border border-lamp px-2 py-1 text-[12px] text-lamp hover:bg-lamp hover:text-rock-950 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {p.selecting ? 'Selecting…' : 'Select'}
            </button>
            <button
              type="button"
              disabled={!picked || p.busy || !isFeasible(catalogue, picked)}
              onClick={() => picked && p.onActivate(picked)}
              className="plate flex-1 rounded-sm bg-lamp px-2 py-1 text-[12px] text-rock-950 hover:bg-lamp-deep hover:text-chalk disabled:cursor-not-allowed disabled:opacity-40"
            >
              {p.activating ? 'Activating…' : 'Activate as ramp source'}
            </button>
          </div>
          <div className="mt-1 text-mute">
            finite declared grid · hard constraints stay hard · scores are Development / Geology /
            Geometry group totals (§26) · not an optimizer
          </div>
        </div>
      ) : (
        <p className="mt-2 text-[11px] text-mute">
          Enumerates SPIRAL, LONGITUDINAL and SWITCHBACK ramp families from the authoritative
          portal, validates the delivered centerline against every required level, and ranks
          feasible candidates. Works for every orebody type.
        </p>
      )}
    </PanelSection>
  )
}

function CandidateDetail({ candidate }: { candidate: LayoutCandidateSummary | null }) {
  if (!candidate) return null
  const d = candidate.diagnostics
  const cl = candidate.clearance
  return (
    <div className="mt-1 border-t border-rock-700 pt-1 text-mute" aria-label="candidate detail">
      <div className="text-chalk-dim">{candidate.candidateId}</div>
      {d ? (
        <div className="flex justify-between">
          <span>grade ≤ {d.maxAbsGradient.toFixed(3)}</span>
          <span>R ≥ {d.minPlanRadius === null ? '—' : d.minPlanRadius.toFixed(1)} m</span>
          <span>Σθ {d.cumulativeHeadingChangeDeg.toFixed(0)}°</span>
          <span>{d.headingReversalCount} hairpins</span>
        </div>
      ) : null}
      {cl ? (
        <div className="flex justify-between">
          <span>{cl.clearanceBasis} clearance</span>
          <span>
            {cl.conservativeMinimumClearance.toFixed(1)} m ≥ {cl.requiredClearance.toFixed(1)} m
            {cl.clearanceErrorBound !== null
              ? ` (bound ${cl.clearanceErrorBound.toFixed(1)} m)`
              : ''}
          </span>
        </div>
      ) : null}
      {candidate.failureDetail ? (
        <div className="text-danger">{candidate.failureDetail}</div>
      ) : null}
      {candidate.access ? (
        <div className="flex justify-between" aria-label="level access summary">
          <span>
            {candidate.access.accessibleLevelCount}/{candidate.access.levelCount} levels accessed
          </span>
          <span>
            access {candidate.access.totalAccessLength.toFixed(0)} m · worst{' '}
            {candidate.access.worstAccessLength.toFixed(0)} m · g ≤{' '}
            {candidate.access.maxAccessGradient.toFixed(3)} · R ≥{' '}
            {candidate.access.minAccessPlanRadius === null
              ? '—'
              : candidate.access.minAccessPlanRadius.toFixed(1)}{' '}
            m
          </span>
        </div>
      ) : null}
      <ul className="mt-0.5 max-h-24 overflow-y-auto">
        {candidate.levelAccesses
          ? candidate.levelAccesses.map((a) => (
              <li key={a.levelId} className="flex justify-between">
                <span>
                  {a.levelId} <span>{a.elevation.toFixed(0)} m</span>
                </span>
                <span className={a.status === 'OK' ? '' : 'text-danger'}>
                  {a.status === 'OK'
                    ? `junction @${(a.rampJunctionChainage ?? 0).toFixed(0)} m · access ${a.length3d.toFixed(0)} m`
                    : (a.failureReason ?? 'no access')}
                </span>
              </li>
            ))
          : candidate.rampLevelReferences.map((r) => (
              <li key={r.levelId} className="flex justify-between">
                <span>
                  {r.levelId} <span>{r.elevation.toFixed(0)} m</span>
                </span>
                <span className={r.withinReach ? '' : 'text-danger'}>
                  {r.withinReach
                    ? `screen ok · ${(r.footprintDistance ?? 0).toFixed(0)} m to ore`
                    : (r.screenReason ?? 'screen failed')}
                </span>
              </li>
            ))}
      </ul>
    </div>
  )
}

function isFeasible(catalogue: LayoutV2Catalogue, id: string): boolean {
  return catalogue.candidates.some((c) => c.candidateId === id && c.status === 'FEASIBLE')
}

function shortId(c: LayoutCandidateSummary): string {
  return c.candidateId.slice(c.family.length + 1)
}
