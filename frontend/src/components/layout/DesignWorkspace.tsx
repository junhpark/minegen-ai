import { DesignPanel } from '@/components/panels/DesignPanel'
import { LayoutPanel } from '@/components/panels/LayoutPanel'
import { LegacyDeclinePanel } from '@/components/panels/LegacyDeclinePanel'
import { DESIGN_PANEL_ID, DESIGN_TABS } from '@/components/panels/workflowTabs'
import { PanelTabs } from '@/components/ui/PanelTabs'
import { useViewerStore } from '@/stores/viewerStore'

/**
 * Phase 20E §4 — the Design workflow as secondary tabs.
 *
 * Every panel stays MOUNTED for every tab and renders only in its own
 * workflow context, so each job poll, query and effect keeps exactly its
 * pre-20E lifetime: switching a tab performs no request, no mutation and no
 * layer change (§19). The selected tab is frontend-local viewer state (§20).
 */
export function DesignWorkspace() {
  const tab = useViewerStore((s) => s.designTab)
  const setTab = useViewerStore((s) => s.setDesignTab)
  return (
    <>
      <PanelTabs
        tabs={DESIGN_TABS}
        active={tab}
        onSelect={setTab}
        label="design workflow"
        panelId={DESIGN_PANEL_ID}
      />
      <div id={DESIGN_PANEL_ID} role="tabpanel" aria-labelledby={`${DESIGN_PANEL_ID}-tab-${tab}`}>
        <LayoutPanel active={tab === 'LAYOUT'} />
        <DesignPanel view={tab} />
        {/* the legacy Hybrid-A* chain is the Layout tab's Advanced section */}
        <LegacyDeclinePanel active={tab === 'LAYOUT'} />
      </div>
    </>
  )
}
