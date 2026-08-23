import { InspectorPanel } from '@/components/panels/InspectorPanel'

export function RightPanel() {
  return (
    <aside className="flex w-[300px] shrink-0 flex-col overflow-y-auto border-l border-rock-700 bg-rock-800">
      <InspectorPanel />
    </aside>
  )
}
