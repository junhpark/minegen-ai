import { useCallback } from 'react'
import { SceneMigrationNotice } from '@/components/layout/SceneMigrationNotice'
import { useShellStore } from '@/components/layout/shellStore'
import { stepOf, stepSpec } from '@/components/layout/workflow'
import { InspectorPanel } from '@/components/panels/InspectorPanel'
import { ViewPanel } from '@/components/panels/ViewPanel'
import { FourDResults } from '@/components/timeline/FourDResults'
import { useViewerStore } from '@/stores/viewerStore'

/**
 * Hardening H1 §4.2 — the STATUS & RESULTS column (the current step's stage
 * statuses, key metrics, backend `failureReason` and Details, rendered by
 * the staged cards into the results host) over the VIEW panel (camera
 * presets, Visibility tree, field slice) and the Inspector.
 */
export function RightPanel() {
  const stage = useViewerStore((s) => s.stage)
  const fourD = useViewerStore((s) => s.mode) === '4D'
  const setResultsHost = useShellStore((s) => s.setResultsHost)
  const host = useCallback((el: HTMLElement | null) => setResultsHost(el), [setResultsHost])
  const step = stepSpec(stepOf(stage))
  return (
    <aside className="flex w-[340px] shrink-0 flex-col overflow-y-auto border-l border-rock-700 bg-rock-800">
      <header className="flex items-center justify-between border-b border-rock-700 px-4 py-2">
        <h2 className="plate text-[12px] text-chalk-dim">Status &amp; results</h2>
        <span className="readout text-[10px] text-mute">
          {step.index} {step.label}
        </span>
      </header>
      {/* PR #54 review B2: what the scene read migrated (normally nothing) */}
      <SceneMigrationNotice />
      <div ref={host} data-testid="results-host" />
      {/* hardening PR-2 H3 §7: the 4D view's quantitative results (backend time series) */}
      {fourD ? <FourDResults /> : null}
      <ViewPanel />
      <InspectorPanel />
    </aside>
  )
}
