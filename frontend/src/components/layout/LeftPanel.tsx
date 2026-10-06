import { useCallback } from 'react'
import { AnalysisWorkspace } from '@/components/layout/AnalysisWorkspace'
import { DesignWorkspace } from '@/components/layout/DesignWorkspace'
import { ResetFromHere } from '@/components/layout/ResetFromHere'
import { useShellStore } from '@/components/layout/shellStore'
import { SystemsWorkspace } from '@/components/layout/SystemsWorkspace'
import { STAGE_LABEL, stepOf } from '@/components/layout/workflow'
import { ExportPanel } from '@/components/panels/ExportPanel'
import { SetupPanel } from '@/components/panels/ScenarioPanel'
import { useViewerStore } from '@/stores/viewerStore'

/**
 * Hardening H1 §4.2 — the CONTROLS column: the current stage's parameters
 * and its ONE primary action, then "Reset from here".
 *
 * Every feature panel stays MOUNTED here for every stage (one container,
 * one set of hooks each, exactly as before the shell): a staged card renders
 * its action into the controls host above and its status / metrics /
 * failure / details into the results column. The workspace follows the
 * current STEP (not the view mode), so the 4D view of a Systems stage keeps
 * its cards. The Analysis workspace is the exception — it is a full-window
 * workspace rendered in the centre by `App`, never a column.
 */
export function LeftPanel() {
  const stage = useViewerStore((s) => s.stage)
  // the workspace of the current STEP stays mounted in every view (3D / 4D):
  // the 4D view of a Systems stage still shows the Systems cards
  const step = stepOf(stage)
  const setControlsHost = useShellStore((s) => s.setControlsHost)
  const host = useCallback((el: HTMLElement | null) => setControlsHost(el), [setControlsHost])
  return (
    <aside className="flex w-[320px] shrink-0 flex-col overflow-y-auto border-r border-rock-700 bg-rock-800">
      <header className="flex items-center justify-between border-b border-rock-700 px-4 py-2">
        <h2 className="plate text-[12px] text-chalk-dim">Controls</h2>
        <span className="readout text-[10px] text-mute">{STAGE_LABEL[stage]}</span>
      </header>
      <div ref={host} data-testid="controls-host" className="flex-1" />
      {stage === 'ANALYSIS' ? (
        <p className="px-4 py-3 text-[11px] leading-relaxed text-mute">
          Analysis is a read-only projection of the generated mine — there is nothing to generate
          here. The workspace opens in the centre.
        </p>
      ) : null}
      <ResetFromHere />
      {/* mounted feature panels (their cards portal into the two columns) */}
      <div data-testid="workflow-panels">
        <SetupPanel />
        {step === 'SYSTEMS' ? <SystemsWorkspace /> : null}
        {step === 'SYSTEMS' || step === 'ANALYSIS' ? null : <DesignWorkspace />}
        <ExportPanel />
      </div>
    </aside>
  )
}

/** the centre workspace of the Analysis step (PR-1: the existing Analysis
 * panel placed full-window; charts follow in PR-2) */
export function AnalysisCenter() {
  return (
    <div
      className="absolute inset-0 z-10 overflow-y-auto bg-rock-900"
      data-testid="analysis-center"
    >
      <div className="mx-auto max-w-[920px] border-x border-rock-700 bg-rock-800">
        <AnalysisWorkspace />
      </div>
    </div>
  )
}
