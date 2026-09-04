import { useMutation } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, ApiError } from '@/api/client'
import { JobProgress } from '@/components/panels/JobProgress'
import { PanelSection } from '@/components/layout/PanelSection'
import { legacySectionAutoOpen, useRampSourceSwitch } from '@/components/panels/rampSource'
import { useJobPoll } from '@/components/panels/useJobPoll'
import { DESIGN_UNSUPPORTED_NOTICE, designSupported } from '@/scenario/builder'
import { afterLegacySmoothRegen, afterLegacyUpstreamRegen } from '@/scene/invalidation'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useViewerStore } from '@/stores/viewerStore'
import { fmtMeters } from '@/utils/format'
import type { Scenario } from '@/types/api'
import type {
  DeclinePayload,
  JobRecord,
  RampSource,
  SmoothedDeclinePayload,
  WorldScene,
} from '@/types/scene'

export const LEGACY_SECTION_TITLE = 'Legacy decline (Hybrid-A*) — Advanced'
export const LEGACY_SECTION_NOTE =
  'Not required for Layout v2. The Phase 03–05 access-target → Hybrid-A* → smoothing chain ' +
  'is kept for the legacy workflow, goldens and comparisons.'

/**
 * Closeout v3 §1: the legacy Phase 03–05 decline workflow (access targets,
 * raw Hybrid-A* decline, Phase 05 smoothing) and the explicit ramp-source
 * switch, grouped as ONE collapsed "Advanced" section. It auto-expands only
 * for a scenario that actually uses the legacy chain (LEGACY active AND a
 * legacy artifact present); the user can always toggle it. Backend, API,
 * artifacts and goldens are untouched — this is UI hierarchy only.
 */
export function LegacyDeclinePanel() {
  const scenario = useScenarioStore((s) => s.scenario)
  const scene = useScenarioStore((s) => s.scene)
  const applyScene = useScenarioStore((s) => s.applyScene)
  const epoch = useScenarioStore((s) => s.epoch)
  const jobs = useScenarioStore((s) => s.jobs)
  const setJob = useScenarioStore((s) => s.setJob)
  const setLayerVisible = useViewerStore((s) => s.setLayerVisible)
  const switchSource = useRampSourceSwitch()
  // manual override of the auto open state, reset per scenario
  const [manualOpen, setManualOpen] = useState<boolean | null>(null)
  const scenarioId = scene?.scenarioId ?? null
  useEffect(() => {
    setManualOpen(null)
  }, [scenarioId])

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

  const err = generate.error ?? generateDecline.error ?? smoothDecline.error ?? switchSource.error
  const errorText =
    err instanceof ApiError ? `${err.code}: ${err.message}` : err ? err.message : null

  return (
    <LegacyDeclineBody
      scenario={scenario}
      scene={scene}
      open={manualOpen ?? legacySectionAutoOpen(scene)}
      onToggle={() => setManualOpen((prev) => !(prev ?? legacySectionAutoOpen(scene)))}
      targetsPending={generate.isPending}
      declineJob={job.data ?? null}
      declinePending={generateDecline.isPending || jobRunning}
      smoothJob={smoothJob.data ?? null}
      smoothPending={smoothDecline.isPending || smoothRunning}
      switching={switchSource.isPending}
      errorText={errorText}
      onGenerateTargets={() => generate.mutate()}
      onGenerateDecline={() => generateDecline.mutate()}
      onSmooth={() => smoothDecline.mutate()}
      onSwitch={(src) => switchSource.mutate(src)}
    />
  )
}

export interface LegacyDeclineBodyProps {
  scenario: Scenario | null
  scene: WorldScene | null
  open: boolean
  onToggle: () => void
  targetsPending: boolean
  declineJob: JobRecord | null
  declinePending: boolean
  smoothJob: JobRecord | null
  smoothPending: boolean
  switching: boolean
  errorText: string | null
  onGenerateTargets: () => void
  onGenerateDecline: () => void
  onSmooth: () => void
  onSwitch: (source: RampSource) => void
}

/** Pure presentation (testable without a store or query client). */
export function LegacyDeclineBody(p: LegacyDeclineBodyProps) {
  const { scenario, scene } = p
  const targets = scene?.accessTargets ?? null
  const decline = scene?.decline ?? null
  const legacySmoothed = scene?.legacySmoothedDecline ?? null
  const rampSource = scene?.rampSource ?? null
  const active = rampSource?.activeSource ?? 'LEGACY'
  const declineJobShown =
    p.declineJob && (p.declinePending || p.declineJob.status === 'FAILED') ? p.declineJob : null
  const smoothJobShown =
    p.smoothJob && (p.smoothPending || p.smoothJob.status === 'FAILED') ? p.smoothJob : null

  return (
    <PanelSection
      title={LEGACY_SECTION_TITLE}
      tag="Phase 03–05"
      collapsible
      open={p.open}
      onToggle={p.onToggle}
      note={LEGACY_SECTION_NOTE}
    >
      <div className="readout mb-2 text-[11px]" aria-label="ramp source switch">
        <div className="mb-1 text-mute">Effective ramp source (advanced)</div>
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
        onClick={p.onGenerateTargets}
        disabled={!scene || !designSupported(scenario) || p.targetsPending}
        className="plate w-full rounded-sm border border-lamp px-3 py-1.5 text-[13px] text-lamp hover:bg-lamp hover:text-rock-950 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {p.targetsPending
          ? 'Generating…'
          : targets
            ? 'Regenerate access targets (Phase 03)'
            : 'Generate access targets (Phase 03)'}
      </button>
      {p.errorText ? (
        <p role="alert" className="mt-2 text-[11px] text-danger">
          {p.errorText}
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
          Legacy only: decline access elevations and footwall candidates per level.
        </p>
      )}

      <button
        type="button"
        onClick={p.onGenerateDecline}
        disabled={!targets || p.declinePending}
        className="plate mt-3 w-full rounded-sm border border-lamp px-3 py-1.5 text-[13px] text-lamp hover:bg-lamp hover:text-rock-950 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {p.declinePending
          ? 'Generating decline…'
          : decline
            ? 'Regenerate decline (Hybrid-A*)'
            : 'Generate decline (Hybrid-A*, Phase 04)'}
      </button>
      {declineJobShown ? <JobProgress job={declineJobShown} /> : null}
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
        onClick={p.onSmooth}
        disabled={!decline || p.smoothPending || p.declinePending}
        className="plate mt-3 w-full rounded-sm border border-lamp px-3 py-1.5 text-[13px] text-lamp hover:bg-lamp hover:text-rock-950 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {p.smoothPending
          ? 'Smoothing decline…'
          : legacySmoothed
            ? 'Re-smooth decline'
            : 'Smooth decline (Phase 05)'}
      </button>
      {smoothJobShown ? <JobProgress job={smoothJobShown} /> : null}
      {active === 'LAYOUT_V2' ? (
        <p className="mt-2 text-[11px] text-mute">
          Active ramp source: Layout v2
          {scene?.smoothedDecline?.candidateId ? ` (${scene.smoothedDecline.candidateId})` : ''}.
          The legacy smoothed decline is kept but not consumed downstream.
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
    </PanelSection>
  )
}
