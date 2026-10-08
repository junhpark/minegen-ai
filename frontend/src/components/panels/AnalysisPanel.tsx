import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '@/api/client'
import { InfoPopover } from '@/components/ui/InfoPopover'
import { Metrics } from '@/components/ui/MetricRow'
import { artifactTone } from '@/components/ui/presentation'
import { WorkflowCard } from '@/components/ui/WorkflowCard'
import { useScenarioStore } from '@/stores/scenarioStore'
import type {
  EconomicsConfig,
  EconomicsConfigResponse,
  LayoutComparisonPayload,
  MineAnalysisPayload,
  ProductionDetail,
  SensitivityPayload,
  TimeseriesPayload,
  WhatIfFactors,
  WhatIfOutcome,
} from '@/types/analysis'
import type { DesignAssessmentPayload, LevelsPayload, TimelinePayload } from '@/types/scene'
import {
  AVAILABILITY_LABEL,
  availabilityTone,
  cubic,
  days,
  EDGE_TYPE_LABEL,
  fmt0,
  fmt1,
  fmt2,
  irrText,
  METHOD_LABEL,
  metres,
  money,
  tonnes,
} from './analysisFormat'
import { assessmentKey } from './assessmentKey'
import { CashflowCharts, CashflowTable } from './CashflowTable'
import { EconomicsConfigEditor } from './EconomicsConfigEditor'
import { economicsIdentity } from './economicsDraft'
import { levelCoverageLines } from './levelCoverage'
import { LayoutComparisonBody } from './LayoutComparisonPanel'
import { RulebookBody } from './RulebookPanel'
import { ScheduleBody } from './SchedulePanel'
import { SensitivityBody } from './SensitivityPanel'
import type { AnalysisTab } from './workflowTabs'

const errorText = (err: unknown): string | null =>
  err instanceof ApiError
    ? `${err.code}: ${err.message}`
    : err instanceof Error
      ? err.message
      : null

/**
 * Phase 22A/B/C — the Analysis workspace container. READ-ONLY queries over
 * backend projections — the analysis, the economics assumption document, the
 * Phase 20D.3 design assessment (the Rules tab; the SAME query key the Layout
 * panel uses, so both read one cache entry), the layout comparison and, since
 * hardening PR-2 H3 §8, the sensitivity grid and the time series (the SAME
 * `analysis-timeseries` key the 4D results card uses) — keyed on the scenario
 * epoch and the scene identity so a response of a previous scenario / revision
 * never populates the current one (the existing `scenarioStore` epoch
 * contract). Two mutations: saving the assumptions, which reloads the
 * economics-dependent reads and touches no mine artifact — an economics change
 * is not a viewer revision (no epoch bump, no scene clear) — and the explicit
 * what-if, a POST that persists nothing and whose answer is held only in the
 * mutation state.
 */
export function AnalysisPanel({ view }: { view: AnalysisTab }) {
  const scene = useScenarioStore((s) => s.scene)
  const scenarioDoc = useScenarioStore((s) => s.scenario)
  const epoch = useScenarioStore((s) => s.epoch)
  const qc = useQueryClient()
  const scenarioId = scenarioDoc?.id ?? null

  const config = useQuery({
    queryKey: ['economics-config', epoch, scenarioId],
    queryFn: () => api.getEconomicsConfig(scenarioId ?? ''),
    enabled: scenarioId !== null,
    retry: false,
  })
  const revision = config.data?.revision ?? null
  const analysis = useQuery({
    queryKey: ['mine-analysis', epoch, scenarioId, ...assessmentKey(scene), revision],
    queryFn: () => api.getAnalysis(scenarioId ?? ''),
    enabled: scenarioId !== null,
    retry: false,
  })
  // Phase 22C Rules tab: the design assessment read model, ONE cache entry
  // shared with the Layout panel (identical key), never a second evaluator
  const assessment = useQuery({
    queryKey: ['design-assessment', epoch, ...assessmentKey(scene)],
    queryFn: () => api.getDesignAssessment(scene?.scenarioId ?? ''),
    enabled: scene !== null,
    retry: false,
  })
  // Phase 22C Layout comparison: persisted candidate lengths × configured rates
  const comparison = useQuery({
    queryKey: ['layout-comparison', epoch, scenarioId, ...assessmentKey(scene), revision],
    queryFn: () => api.getLayoutComparison(scenarioId ?? ''),
    enabled: scenarioId !== null,
    retry: false,
  })
  // PR-2 H3 §8.3: the what-if grid — only while the Sensitivity tab is shown
  // (nine parameters × six perturbations, each a backend projection)
  const sensitivity = useQuery({
    queryKey: ['analysis-sensitivity', epoch, scenarioId, ...assessmentKey(scene), revision],
    queryFn: () => api.getSensitivity(scenarioId ?? ''),
    enabled: scenarioId !== null && view === 'SENSITIVITY',
    retry: false,
  })
  // PR-2 H3 §6/§8: the bucketed time series, ONE cache entry with FourDResults
  const timelineRevision = scene?.timeline?.sourceRevision ?? null
  const timeseries = useQuery({
    queryKey: ['analysis-timeseries', epoch, scenarioId, timelineRevision],
    queryFn: () => api.getTimeseries(scenarioId ?? ''),
    enabled: scenarioId !== null && view === 'SCHEDULE' && scene?.timeline?.status === 'SUCCESS',
    retry: false,
  })
  const whatIf = useMutation({
    mutationFn: async (factors: WhatIfFactors) => {
      if (!scenarioId) throw new Error('load a scenario first')
      return api.postWhatIf(scenarioId, factors)
    },
    // a projection: nothing to invalidate, nothing persisted
  })
  const save = useMutation({
    mutationFn: async (next: EconomicsConfig) => {
      if (!scenarioId) throw new Error('load a scenario first')
      return api.putEconomicsConfig(scenarioId, next)
    },
    onSuccess: (saved: EconomicsConfigResponse) => {
      // the saved document IS the new persisted state; the analysis and the
      // layout comparison are re-read under its new economics revision.
      // Nothing else changes: no epoch bump, no scene clear, no invalidation.
      qc.setQueryData(['economics-config', epoch, scenarioId], saved)
      void qc.invalidateQueries({ queryKey: ['mine-analysis'] })
      void qc.invalidateQueries({ queryKey: ['layout-comparison'] })
      // PR-2 H3: the 4D time series carries the economics columns too, and
      // the what-if grid is relative to the configured assumptions
      void qc.invalidateQueries({ queryKey: ['analysis-timeseries'] })
      void qc.invalidateQueries({ queryKey: ['analysis-sensitivity'] })
      whatIf.reset()
    },
  })

  return (
    <AnalysisPanelBody
      view={view}
      scenarioId={scenarioId}
      analysis={analysis.data ?? null}
      analysisError={errorText(analysis.error)}
      loading={analysis.isPending && scenarioId !== null}
      levels={scene?.levels ?? null}
      assessment={assessment.data ?? null}
      assessmentError={errorText(assessment.error)}
      assessmentLoading={assessment.isPending && scene !== null}
      layoutComparison={comparison.data ?? null}
      layoutComparisonError={errorText(comparison.error)}
      layoutComparisonLoading={comparison.isPending && scenarioId !== null}
      economicsConfig={config.data ?? null}
      economicsError={errorText(config.error)}
      activeMethod={scenarioDoc?.mining.method ?? null}
      saving={save.isPending}
      saveError={errorText(save.error)}
      onSave={(next) => save.mutate(next)}
      sensitivity={sensitivity.data ?? null}
      sensitivityError={errorText(sensitivity.error)}
      sensitivityLoading={sensitivity.isPending && scenarioId !== null}
      timeseries={timeseries.data ?? null}
      timeseriesError={errorText(timeseries.error)}
      timeseriesLoading={timeseries.isPending && scenarioId !== null}
      timeline={scene?.timeline ?? null}
      whatIf={whatIf.data ?? null}
      whatIfPending={whatIf.isPending}
      whatIfError={errorText(whatIf.error)}
      onWhatIf={(factors) => whatIf.mutate(factors)}
    />
  )
}

export interface AnalysisPanelBodyProps {
  view: AnalysisTab
  scenarioId: string | null
  analysis: MineAnalysisPayload | null
  analysisError: string | null
  loading: boolean
  /** the scene's levels.json — its level-coverage report is shown on Overview (hardening H0 §3.1) */
  levels: LevelsPayload | null
  assessment: DesignAssessmentPayload | null
  assessmentError: string | null
  assessmentLoading: boolean
  layoutComparison: LayoutComparisonPayload | null
  layoutComparisonError: string | null
  layoutComparisonLoading: boolean
  economicsConfig: EconomicsConfigResponse | null
  economicsError: string | null
  activeMethod: string | null
  saving: boolean
  saveError: string | null
  onSave: (config: EconomicsConfig) => void
  /** hardening PR-2 H3 §8.3 — the read-only what-if grid (Sensitivity tab) */
  sensitivity: SensitivityPayload | null
  sensitivityError: string | null
  sensitivityLoading: boolean
  /** hardening PR-2 H3 §8 — the backend time series (Schedule tab) */
  timeseries: TimeseriesPayload | null
  timeseriesError: string | null
  timeseriesLoading: boolean
  /** the scene's timeline.json, shown as the task table (never re-summed) */
  timeline: TimelinePayload | null
  /** the last explicit what-if answer (mutation state only, never persisted) */
  whatIf: WhatIfOutcome | null
  whatIfPending: boolean
  whatIfError: string | null
  onWhatIf: (factors: WhatIfFactors) => void
}

export const ECONOMICS_NOT_CONFIGURED_TEXT = 'Planning economics is not configured.'

/** pure presentation of the read model — every number is a backend value */
export function AnalysisPanelBody(p: AnalysisPanelBodyProps) {
  // Phase 23C: the Simulation Results tab is its own container (mounted beside
  // this panel); the read panel renders nothing in that context
  if (p.view === 'SIMULATION') return null
  if (p.scenarioId === null) {
    return (
      <p className="px-4 py-3 text-[11px] text-mute">Load a scenario to analyse its mine plan.</p>
    )
  }
  // the KPI tiles head every analysis tab once the analysis read model exists
  const kpis = p.analysis ? (
    <KpiTiles
      analysis={p.analysis}
      code={p.analysis.economics.currencyCode ?? p.economicsConfig?.config?.currencyCode ?? null}
    />
  ) : null
  if (p.view === 'RULES') {
    return (
      <>
        {kpis}
        <RulebookBody
          assessment={p.assessment}
          error={p.assessmentError}
          loading={p.assessmentLoading}
        />
      </>
    )
  }
  if (p.view === 'LAYOUT_COMPARISON') {
    return (
      <>
        {kpis}
        <LayoutComparisonBody
          payload={p.layoutComparison}
          error={p.layoutComparisonError}
          loading={p.layoutComparisonLoading}
        />
      </>
    )
  }
  if (p.analysisError) {
    return (
      <p className="break-words px-4 py-3 text-[11px] text-danger" data-testid="analysis-error">
        {p.analysisError}
      </p>
    )
  }
  if (!p.analysis) {
    return <p className="px-4 py-3 text-[11px] text-mute">{p.loading ? 'Loading analysis…' : ''}</p>
  }
  const code = p.analysis.economics.currencyCode ?? p.economicsConfig?.config?.currencyCode ?? null
  return (
    <>
      {kpis}
      {p.view === 'OVERVIEW' ? (
        <OverviewCards analysis={p.analysis} levels={p.levels} />
      ) : p.view === 'SENSITIVITY' ? (
        <SensitivityBody
          payload={p.sensitivity}
          error={p.sensitivityError}
          loading={p.sensitivityLoading}
          code={code}
          whatIf={p.whatIf}
          whatIfPending={p.whatIfPending}
          whatIfError={p.whatIfError}
          onWhatIf={p.onWhatIf}
        />
      ) : p.view === 'SCHEDULE' ? (
        <ScheduleBody
          analysis={p.analysis}
          timeline={p.timeline}
          series={p.timeseries}
          seriesError={p.timeseriesError}
          seriesLoading={p.timeseriesLoading}
        />
      ) : (
        <EconomicsCards {...p} analysis={p.analysis} />
      )}
    </>
  )
}

// --------------------------------------------------------------------------- //
// KPI tiles (hardening PR-2 H3 §8.1)
// --------------------------------------------------------------------------- //

/**
 * The four large planning KPIs above every analysis tab: Planning NPV,
 * Planning IRR, mine life and first production day — backend values rendered
 * as given. An unconfigured economics shows its typed status, never a number.
 */
export function KpiTiles({
  analysis,
  code,
}: {
  analysis: MineAnalysisPayload
  code: string | null
}) {
  const eco = analysis.economics
  const sched = analysis.schedule
  const tiles: { label: string; value: string; note: string }[] = [
    {
      label: 'Planning NPV',
      value: eco.summary ? money(eco.summary.npv, code) : AVAILABILITY_LABEL[eco.availability],
      note: eco.summary
        ? `discount ${fmt2(eco.annualDiscountRate)} · ${fmt0(eco.cashflowBucketDays)}-day buckets`
        : 'planning economics',
    },
    {
      label: 'Planning IRR',
      value: irrText(eco.planningIrr),
      note:
        eco.planningIrr.status === 'DEFINED'
          ? 'annual, mid-bucket timing'
          : eco.planningIrr.status === 'NOT_DEFINED'
            ? 'no single rate'
            : 'planning economics',
    },
    {
      label: 'Mine life',
      value: days(sched.mineDurationDays),
      note: sched.availability === 'AVAILABLE' ? 'baseline schedule' : AVAILABILITY_LABEL[sched.availability],
    },
    {
      label: 'First production day',
      value: days(sched.firstProductionDay),
      note: sched.availability === 'AVAILABLE' ? 'earliest STOPING start' : AVAILABILITY_LABEL[sched.availability],
    },
  ]
  return (
    <div className="grid grid-cols-4 gap-2 border-b border-rock-700 px-4 py-3" data-testid="analysis-kpis">
      {tiles.map((t) => (
        <div key={t.label} className="rounded-sm border border-rock-700 bg-rock-900/70 px-3 py-2">
          <div className="plate text-[10px] text-mute">{t.label}</div>
          <div className="mt-0.5 text-[18px] leading-tight text-chalk" data-kpi={t.label}>
            {t.value}
          </div>
          <div className="text-[10px] text-mute">{t.note}</div>
        </div>
      ))}
    </div>
  )
}

// --------------------------------------------------------------------------- //
// Overview
// --------------------------------------------------------------------------- //

function OverviewCards({
  analysis,
  levels,
}: {
  analysis: MineAnalysisPayload
  levels: LevelsPayload | null
}) {
  const dev = analysis.development
  const prod = analysis.production
  const sched = analysis.schedule
  const ratios = analysis.ratios
  const coverage = levelCoverageLines(levels)
  return (
    <>
      {coverage.length > 0 ? (
        <WorkflowCard
          title="Level coverage"
          tone={artifactTone(levels, false)}
          statusLabel="Levels excluded"
          info="Required levels the level development did not receive, as reported by the backend level artifact (rule 141): a TABULAR level above the footwall's top edge has ore above it but no footwall contact next to it, so no drift or crosscut can reach the slab there; the production interval below it is unserved. The dip-aware hint is the top mining margin that would give every level a footwall contact."
          summary={<span data-testid="level-coverage-summary">{coverage[0]}</span>}
          details={
            coverage.length > 1 ? (
              <div className="flex flex-col gap-y-0.5 text-chalk-dim">
                {coverage.slice(1).map((line) => (
                  <div key={line}>{line}</div>
                ))}
              </div>
            ) : null
          }
        />
      ) : null}
      <WorkflowCard
        title="Development"
        tone={availabilityTone(dev.availability)}
        statusLabel={AVAILABILITY_LABEL[dev.availability]}
        info="Development quantities are read from the MineNetwork edges: length is the 3-D centerline length per edge type and the excavation volume is length × cross-section area summed per edge. It is a GROSS volume — junction overlaps are not unioned. The declared network metrics are cross-checked against the edges and never overwritten."
        failure={dev.reason}
        summary={
          dev.totals ? (
            <span>
              {metres(dev.totals.totalDevelopmentLengthM)} ·{' '}
              {cubic(dev.totals.grossDevelopmentVolumeM3)} gross
            </span>
          ) : null
        }
        details={
          dev.totals ? (
            <Metrics
              rows={[
                {
                  label: 'Total development length',
                  value: metres(dev.totals.totalDevelopmentLengthM),
                },
                {
                  label: 'Gross development volume',
                  value: cubic(dev.totals.grossDevelopmentVolumeM3),
                },
                ...dev.categories
                  .filter((c) => c.edgeCount > 0)
                  .map((c) => ({
                    label: EDGE_TYPE_LABEL[c.edgeType] ?? c.edgeType,
                    value: `${String(c.edgeCount)} · ${metres(c.totalLengthM)} · ${cubic(c.grossExcavationVolumeM3)}`,
                  })),
              ]}
            />
          ) : null
        }
      />
      <WorkflowCard
        title="Production"
        tone={availabilityTone(prod.availability)}
        statusLabel={AVAILABILITY_LABEL[prod.availability]}
        info="Planned mined tonnes are the production geometry (stopes, cuts or extraction units) × density — a planning quantity, never a resource or reserve. The grade proxy is the tonnage-weighted Phase 09 planning proxy and is informational only; it is never a revenue input. Backfill and retained pillars are reported separately and are not production."
        failure={prod.reason}
        summary={
          prod.availability === 'AVAILABLE' ? (
            <span>
              {prod.method ? (METHOD_LABEL[prod.method] ?? prod.method) : ''} ·{' '}
              {tonnes(prod.totalPlannedMinedTonnes)} planned mined
            </span>
          ) : null
        }
        details={
          prod.availability === 'AVAILABLE' ? (
            <Metrics
              rows={[
                {
                  label: 'Method',
                  value: prod.method ? (METHOD_LABEL[prod.method] ?? prod.method) : '—',
                },
                { label: 'Production objects', value: fmt0(prod.productionObjectCount) },
                { label: 'Production volume', value: cubic(prod.totalProductionVolumeM3) },
                { label: 'Planned mined tonnes', value: tonnes(prod.totalPlannedMinedTonnes) },
                { label: 'Grade proxy (informational)', value: fmt2(prod.weightedMeanGradeProxy) },
                ...detailRows(prod.detail),
              ]}
            />
          ) : null
        }
      />
      <WorkflowCard
        title="Schedule"
        tone={availabilityTone(sched.availability)}
        statusLabel={AVAILABILITY_LABEL[sched.availability]}
        info="Schedule figures come from the deterministic precedence-only MineTimeline baseline: a synthetic planning baseline, never a production forecast. First production is the earliest STOPING task start."
        failure={sched.reason}
        summary={
          sched.availability === 'AVAILABLE' ? (
            <span>
              Baseline duration {days(sched.mineDurationDays)} · {fmt0(sched.taskCount)} tasks
            </span>
          ) : null
        }
        details={
          sched.availability === 'AVAILABLE' ? (
            <Metrics
              rows={[
                { label: 'Baseline duration', value: days(sched.mineDurationDays) },
                { label: 'Ramp complete', value: days(sched.rampCompletionDay) },
                { label: 'First production', value: days(sched.firstProductionDay) },
                { label: 'Tasks', value: fmt0(sched.taskCount) },
                { label: 'Development tasks', value: fmt0(sched.developmentTaskCount) },
                { label: 'Production tasks', value: fmt0(sched.productionTaskCount) },
              ]}
            />
          ) : null
        }
      />
      <WorkflowCard
        title="Ratios"
        tone={availabilityTone(ratios.availability)}
        statusLabel={AVAILABILITY_LABEL[ratios.availability]}
        info="Development intensity of the plan: total development length and gross development volume per thousand planned mined tonnes. Undefined (shown as —) when planned mined tonnes are zero."
        failure={ratios.reason}
        summary={
          ratios.availability === 'AVAILABLE' ? (
            <span>
              {fmt1(ratios.developmentMetresPerKt)} m/kt · {fmt1(ratios.grossDevelopmentM3PerKt)}{' '}
              m³/kt
            </span>
          ) : null
        }
      />
    </>
  )
}

function detailRows(d: ProductionDetail | null): { label: string; value: string }[] {
  if (!d) return []
  if (d.kind === 'LONGHOLE_OPEN_STOPING') {
    return [
      { label: 'Stopes', value: fmt0(d.stopeCount) },
      { label: 'Level intervals', value: fmt0(d.levelIntervalCount) },
    ]
  }
  if (d.kind === 'CUT_AND_FILL') {
    return [
      { label: 'Cuts', value: fmt0(d.cutCount) },
      { label: 'Lifts', value: fmt0(d.liftCount) },
      { label: 'Backfills', value: fmt0(d.backfillCount) },
      { label: 'Backfill volume (not production)', value: cubic(d.totalBackfillVolumeM3) },
    ]
  }
  return [
    { label: 'Rooms', value: fmt0(d.roomCount) },
    { label: 'Extraction units', value: fmt0(d.extractionUnitCount) },
    { label: 'Headings / benches', value: `${fmt0(d.headingCount)} / ${fmt0(d.benchCount)}` },
    { label: 'Pillars (retained)', value: fmt0(d.pillarCount) },
    { label: 'Retained pillar volume', value: cubic(d.retainedPillarVolumeM3) },
    { label: 'Retained pillar tonnes equivalent', value: tonnes(d.retainedPillarTonnesEquivalent) },
    { label: 'Geometric extraction fraction', value: fmt2(d.geometricExtractionFraction) },
  ]
}

// --------------------------------------------------------------------------- //
// Economics
// --------------------------------------------------------------------------- //

function EconomicsCards(p: AnalysisPanelBodyProps & { analysis: MineAnalysisPayload }) {
  const eco = p.analysis.economics
  const persisted = p.economicsConfig?.config ?? null
  const identity = economicsIdentity(p.scenarioId, p.economicsConfig?.revision ?? null)
  const code = eco.currencyCode ?? persisted?.currencyCode ?? ''
  const s = eco.summary
  return (
    <>
      <div
        className="mx-4 my-2 rounded-sm border border-rock-600 bg-rock-900/70 px-2 py-1.5 text-[11px] leading-relaxed text-chalk-dim"
        data-testid="economics-disclaimer"
      >
        {eco.disclaimer}{' '}
        <InfoPopover label="planning economics">
          The figures are a deterministic projection of explicit user assumptions over the planned
          development lengths, planned mined tonnes and the timeline baseline. They are not a
          feasibility study, a resource or reserve estimate, a bankable figure or an investment
          recommendation. Planning NPV discounts each cashflow bucket at its midpoint day.
        </InfoPopover>
      </div>
      <WorkflowCard
        title="Planning economics"
        tone={availabilityTone(eco.availability)}
        statusLabel={AVAILABILITY_LABEL[eco.availability]}
        info="Development cost = edge length × rate per edge type, spread over each development task. Production mining cost = planned mined tonnes × the active method's rate over STOPING; processing cost and gross revenue over MUCKING; Cut & Fill backfill cost over BACKFILL. Fixed operating cost is linear over the mine duration and initial capital sits in the first bucket. Baseline Planning NPV = Σ bucket net cashflow / (1 + rate)^(midpoint day / 365.25)."
        failure={
          eco.availability === 'NOT_CONFIGURED'
            ? ECONOMICS_NOT_CONFIGURED_TEXT
            : eco.availability === 'NOT_AVAILABLE'
              ? eco.reason
              : null
        }
        summary={
          s ? (
            <span>
              Planning NPV {money(s.npv, code)} · Planning IRR {irrText(eco.planningIrr)} · net{' '}
              {money(s.undiscountedNetCashflow, code)}
            </span>
          ) : null
        }
        details={
          s ? (
            <Metrics
              rows={[
                { label: 'Currency', value: code },
                { label: 'Development cost', value: money(s.developmentCost, code) },
                { label: 'Production mining cost', value: money(s.productionMiningCost, code) },
                { label: 'Processing cost', value: money(s.processingCost, code) },
                { label: 'Backfill cost', value: money(s.backfillCost, code) },
                { label: 'Fixed operating cost', value: money(s.fixedOperatingCost, code) },
                { label: 'Initial capital cost', value: money(s.initialCapitalCost, code) },
                { label: 'Total cost', value: money(s.totalCost, code) },
                { label: 'Gross revenue', value: money(s.totalRevenue, code) },
                {
                  label: 'Undiscounted net cashflow',
                  value: money(s.undiscountedNetCashflow, code),
                },
                { label: 'Baseline Planning NPV', value: money(s.npv, code) },
                { label: 'Planning IRR', value: irrText(eco.planningIrr) },
                { label: 'Mine duration', value: days(p.analysis.schedule.mineDurationDays) },
                {
                  label: 'Discount rate / bucket',
                  value: `${fmt2(eco.annualDiscountRate)} / ${fmt0(eco.cashflowBucketDays)} d`,
                },
              ]}
            />
          ) : null
        }
      />
      {s ? (
        <section className="border-b border-rock-700 px-4 py-3">
          <h3 className="plate mb-1.5 text-[12px] text-chalk">Planning Cashflow</h3>
          <CashflowCharts buckets={eco.cashflow} summary={s} code={code} />
          <div className="mt-2">
            <CashflowTable buckets={eco.cashflow} code={code} />
          </div>
        </section>
      ) : null}
      <section className="border-b border-rock-700 px-4 py-3">
        {p.economicsError ? (
          <p className="mb-1.5 break-words text-[11px] text-danger">{p.economicsError}</p>
        ) : null}
        <EconomicsConfigEditor
          persisted={persisted}
          identity={identity}
          activeMethod={p.activeMethod}
          saving={p.saving}
          enabled={p.economicsError === null}
          saveError={p.saveError}
          onSave={p.onSave}
        />
      </section>
    </>
  )
}
