import { AnalysisPanel } from '@/components/panels/AnalysisPanel'
import { SimulationResultsPanel } from '@/components/panels/SimulationResultsPanel'
import { ANALYSIS_PANEL_ID, ANALYSIS_TABS } from '@/components/panels/workflowTabs'
import { PanelTabs } from '@/components/ui/PanelTabs'
import { useViewerStore } from '@/stores/viewerStore'

/**
 * Phase 22A/B — the Analysis workspace as secondary tabs: Overview
 * (development / production / schedule / ratio quantities) and Economics
 * (planning assumptions, cost / revenue summary, Planning Cashflow, Baseline
 * Planning NPV). The panel stays MOUNTED for its tabs so its read-only
 * queries keep their lifetime; switching a tab performs no request and no
 * mutation (Phase 20E §19). Phase 23C adds the Simulation Results tab as a
 * SEPARATE container (its own import / list / frame queries) — no new mode.
 */
export function AnalysisWorkspace() {
  const tab = useViewerStore((s) => s.analysisTab)
  const setTab = useViewerStore((s) => s.setAnalysisTab)
  const show3d = useViewerStore((s) => s.analysisShow3d)
  const setShow3d = useViewerStore((s) => s.setAnalysisShow3d)
  return (
    <>
      <header className="flex items-center justify-between border-b border-rock-700 px-4 py-2">
        <h2 className="plate text-[13px] text-chalk">Analysis</h2>
        <label className="flex items-center gap-1.5 text-[11px] text-chalk-dim">
          <input
            type="checkbox"
            checked={show3d}
            onChange={(e) => setShow3d(e.target.checked)}
            data-testid="analysis-show-3d"
          />
          Show 3D context
        </label>
      </header>
      <PanelTabs
        tabs={ANALYSIS_TABS}
        active={tab}
        onSelect={setTab}
        label="analysis"
        panelId={ANALYSIS_PANEL_ID}
      />
      <div
        id={ANALYSIS_PANEL_ID}
        role="tabpanel"
        aria-labelledby={`${ANALYSIS_PANEL_ID}-tab-${tab}`}
      >
        <AnalysisPanel view={tab} />
        {/* Phase 23C: stays mounted so its list query and result clock keep their lifetime */}
        <SimulationResultsPanel active={tab === 'SIMULATION'} />
      </div>
    </>
  )
}
