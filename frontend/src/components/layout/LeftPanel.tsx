import { ScenarioPanel } from '@/components/panels/ScenarioPanel'
import { LayerPanel } from '@/components/panels/LayerPanel'
import { AnalysisWorkspace } from '@/components/layout/AnalysisWorkspace'
import { DesignWorkspace } from '@/components/layout/DesignWorkspace'
import { SystemsWorkspace } from '@/components/layout/SystemsWorkspace'
import { useViewerStore } from '@/stores/viewerStore'

/**
 * Left panel (Phase 20E §4–§6):
 *
 *   Scenario summary          — always on top
 *   workflow tabs             — Design: Layout | Develop | Network | Mining
 *                               Systems: Communication | Sensors
 *                               Analysis: Overview | Economics (Phase 22A/B)
 *   Layers                    — viewer control, always reachable, collapsed
 *
 * Infrastructure features remain independent components shown by mode and are
 * never appended to DesignPanel. The internal `INFRASTRUCTURE` mode value is
 * unchanged; only its user-facing label reads "Systems" (§3).
 */
export function LeftPanel() {
  const mode = useViewerStore((s) => s.mode)
  return (
    <aside className="flex w-[320px] shrink-0 flex-col overflow-y-auto border-r border-rock-700 bg-rock-800">
      <ScenarioPanel />
      {mode === 'INFRASTRUCTURE' ? (
        <SystemsWorkspace />
      ) : mode === 'ANALYSIS' ? (
        <AnalysisWorkspace />
      ) : (
        <DesignWorkspace />
      )}
      <LayerPanel />
    </aside>
  )
}
