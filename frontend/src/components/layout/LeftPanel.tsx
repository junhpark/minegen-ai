import { ScenarioPanel } from '@/components/panels/ScenarioPanel'
import { LayerPanel } from '@/components/panels/LayerPanel'
import { DesignPanel } from '@/components/panels/DesignPanel'

export function LeftPanel() {
  return (
    <aside className="flex w-[280px] shrink-0 flex-col overflow-y-auto border-r border-rock-700 bg-rock-800">
      <ScenarioPanel />
      <DesignPanel />
      <LayerPanel />
    </aside>
  )
}
