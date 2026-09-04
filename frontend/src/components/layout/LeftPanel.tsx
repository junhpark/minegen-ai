import { ScenarioPanel } from '@/components/panels/ScenarioPanel'
import { LayerPanel } from '@/components/panels/LayerPanel'
import { DesignPanel } from '@/components/panels/DesignPanel'
import { LayoutPanel } from '@/components/panels/LayoutPanel'
import { LegacyDeclinePanel } from '@/components/panels/LegacyDeclinePanel'
import { CommunicationPanel } from '@/components/panels/CommunicationPanel'
import { SensorPanel } from '@/components/panels/SensorPanel'
import { useViewerStore } from '@/stores/viewerStore'

export function LeftPanel() {
  // §26: infrastructure features are independent components shown by mode,
  // never appended to DesignPanel (Phase-10 UI review decision).
  // Closeout v3 §1: the primary workflow is World → Layout v2 → select /
  // activate → level access → level development → network → stopes →
  // timeline; the legacy Hybrid-A* decline chain is an Advanced section.
  const mode = useViewerStore((s) => s.mode)
  return (
    <aside className="flex w-[280px] shrink-0 flex-col overflow-y-auto border-r border-rock-700 bg-rock-800">
      <ScenarioPanel />
      {mode === 'INFRASTRUCTURE' ? (
        <>
          <CommunicationPanel />
          <SensorPanel />
        </>
      ) : (
        <>
          <LayoutPanel />
          <DesignPanel />
          <LegacyDeclinePanel />
        </>
      )}
      <LayerPanel />
    </aside>
  )
}
