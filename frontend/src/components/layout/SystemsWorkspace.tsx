import { CommunicationPanel } from '@/components/panels/CommunicationPanel'
import { SensorPanel } from '@/components/panels/SensorPanel'
import { SYSTEMS_PANEL_ID, SYSTEMS_TABS } from '@/components/panels/workflowTabs'
import { PanelTabs } from '@/components/ui/PanelTabs'
import { useViewerStore } from '@/stores/viewerStore'

/**
 * Phase 20E §5 — the infrastructure subsystems as secondary tabs.
 *
 * Presentation grouping only: communication and sensor planning keep their
 * own independent API, artifacts and planning semantics, and both panels stay
 * mounted so their queries and effects are unchanged. A further subsystem is
 * added by extending `SYSTEMS_TABS` and mounting its panel here.
 */
export function SystemsWorkspace() {
  const tab = useViewerStore((s) => s.systemsTab)
  const setTab = useViewerStore((s) => s.setSystemsTab)
  return (
    <>
      <PanelTabs
        tabs={SYSTEMS_TABS}
        active={tab}
        onSelect={setTab}
        label="systems"
        panelId={SYSTEMS_PANEL_ID}
      />
      <div id={SYSTEMS_PANEL_ID} role="tabpanel" aria-labelledby={`${SYSTEMS_PANEL_ID}-tab-${tab}`}>
        <CommunicationPanel active={tab === 'COMMUNICATION'} />
        <SensorPanel active={tab === 'SENSORS'} />
      </div>
    </>
  )
}
