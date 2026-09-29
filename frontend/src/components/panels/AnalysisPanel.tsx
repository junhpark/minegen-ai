import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '@/api/client'
import { InfoPopover } from '@/components/ui/InfoPopover'
import { Metrics } from '@/components/ui/MetricRow'
import { WorkflowCard } from '@/components/ui/WorkflowCard'
import { useScenarioStore } from '@/stores/scenarioStore'
import type {
  EconomicsConfig,
  EconomicsConfigResponse,
  LayoutComparisonPayload,
  MineAnalysisPayload,
  ProductionDetail,
} from '@/types/analysis'
import type { DesignAssessmentPayload } from '@/types/scene'
import {
  AVAILABILITY_LABEL,
  availabilityTone,
  cubic,
  days,
  EDGE_TYPE_LABEL,
  fmt0,
  fmt1,
  fmt2,
  METHOD_LABEL,
  metres,
  money,
  tonnes,
} from './analysisFormat'
import { assessmentKey } from './assessmentKey'
import { CashflowTable } from './CashflowTable'
import { EconomicsConfigEditor } from './EconomicsConfigEditor'
import { economicsIdentity } from './economicsDraft'
import { LayoutComparisonBody } from './LayoutComparisonPanel'
import { RulebookBody } from './RulebookPanel'
import type { AnalysisTab } from './workflowTabs'

const errorText = (err: unknown): string | null =>
  err instanceof ApiError
    ? `${err.code}: ${err.message}`
    : err instanceof Error
      ? err.message
      : null

/**
 * Phase 22A/B/C — the Analysis workspace container. Four READ-ONLY queries
 * over backend projections — the analysis, the economics assumption document,
 * the Phase 20D.3 design assessment (the Rules tab; the SAME query key the
 * Layout panel uses, so both read one cache entry) and the layout comparison —
 * keyed on the scenario epoch and the scene identity so a response of a
 * previous scenario / revision never populates the current one (the existing
 * `scenarioStore` epoch contract), and one mutation: saving the assumptions,
 * which reloads the analysis and the layout comparison and touches no mine
 * artifact — an economics change is not a viewer revision (no epoch bump, no
 * scene clear).
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
    },
  })

  return (
    <AnalysisPanelBody
      view={view}
      scenarioId={scenarioId}
      analysis={analysis.data ?? null}
      analysisError={errorText(analysis.error)}
      loading={analysis.isPending && scenarioId !== null}
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
    />
  )
}

export interface AnalysisPanelBodyProps {
  view: AnalysisTab
  scenarioId: string | null
  analysis: MineAnalysisPayload | null
  analysisError: string | null
  loading: boolean
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
  if (p.view === 'RULES') {
    return (
      <RulebookBody
        assessment={p.assessment}
        error={p.assessmentError}
        loading={p.assessmentLoading}
      />
    )
  }
  if (p.view === 'LAYOUT_COMPARISON') {
    return (
      <LayoutComparisonBody
        payload={p.layoutComparison}
        error={p.layoutComparisonError}
        loading={p.layoutComparisonLoading}
      />
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
  return p.view === 'OVERVIEW' ? (
    <OverviewCards analysis={p.analysis} />
  ) : (
    <EconomicsCards {...p} analysis={p.analysis} />
  )
}

// --------------------------------------------------------------------------- //
// Overview
// --------------------------------------------------------------------------- //

function OverviewCards({ analysis }: { analysis: MineAnalysisPayload }) {
  const dev = analysis.development
  const prod = analysis.production
  const sched = analysis.schedule
  const ratios = analysis.ratios
  return (
    <>
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
              Planning NPV {money(s.npv, code)} · net {money(s.undiscountedNetCashflow, code)}
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
          <CashflowTable buckets={eco.cashflow} code={code} />
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
