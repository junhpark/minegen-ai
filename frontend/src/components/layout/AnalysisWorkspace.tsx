import { AnalysisPanel } from '@/components/panels/AnalysisPanel'
import { ANALYSIS_PANEL_ID, ANALYSIS_TABS } from '@/components/panels/workflowTabs'
import { PanelTabs } from '@/components/ui/PanelTabs'
import { useViewerStore } from '@/stores/viewerStore'

/**
 * Phase 22A/B — the Analysis workspace as secondary tabs: Overview
 * (development / production / schedule / ratio quantities) and Economics
 * (planning assumptions, cost / revenue summary, Planning Cashflow, Baseline
 * Planning NPV). The panel stays MOUNTED for both tabs so its read-only
 * queries keep their lifetime; switching a tab performs no request and no
 * mutation (Phase 20E §19).
 */
export function AnalysisWorkspace() {
  const tab = useViewerStore((s) => s.analysisTab)
  const setTab = useViewerStore((s) => s.setAnalysisTab)
  return (
    <>
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
      </div>
    </>
  )
}
