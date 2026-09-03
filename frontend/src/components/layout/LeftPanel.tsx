import { ScenarioPanel } from '@/components/panels/ScenarioPanel'
import { LayerPanel } from '@/components/panels/LayerPanel'
import { DesignPanel } from '@/components/panels/DesignPanel'
import { LayoutPanel } from '@/components/panels/LayoutPanel'
import { CommunicationPanel } from '@/components/panels/CommunicationPanel'
import { SensorPanel } from '@/components/panels/SensorPanel'
import { useViewerStore } from '@/stores/viewerStore'

export function LeftPanel() {
  // §26: infrastructure features are independent components shown by mode,
  // never appended to DesignPanel (Phase-10 UI review decision)
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
        </>
      )}
      <LayerPanel />
    </aside>
  )
}
