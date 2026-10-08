import { useCallback, useEffect } from 'react'
import { AnalysisWorkspace } from '@/components/layout/AnalysisWorkspace'
import { DemoPanel } from '@/components/layout/DemoPanel'
import { DesignWorkspace } from '@/components/layout/DesignWorkspace'
import { ResetFromHere } from '@/components/layout/ResetFromHere'
import { useShellStore } from '@/components/layout/shellStore'
import { SystemsWorkspace } from '@/components/layout/SystemsWorkspace'
import { STAGE_LABEL, stepOf } from '@/components/layout/workflow'
import { ExportPanel } from '@/components/panels/ExportPanel'
import { SetupPanel } from '@/components/panels/ScenarioPanel'
import { useScenarioStore } from '@/stores/scenarioStore'
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
 *
 * Hardening PR-2 H4 — demo mode: while a baked demo is open the column shows
 * the `DemoPanel` (viewer-only: no generation controls, no "Reset from
 * here") instead of the controls host, except on the Export stage, whose
 * action stays available for a demo. The feature panels stay MOUNTED: their
 * results halves keep rendering into the right column.
 */
export function LeftPanel() {
  const stage = useViewerStore((s) => s.stage)
  const demo = useScenarioStore((s) => s.demo !== null)
  const demoControls = demo && stage !== 'EXPORT'
  // the workspace of the current STEP stays mounted in every view (3D / 4D):
  // the 4D view of a Systems stage still shows the Systems cards
  const step = stepOf(stage)
  const setControlsHost = useShellStore((s) => s.setControlsHost)
  const host = useCallback((el: HTMLElement | null) => setControlsHost(el), [setControlsHost])
  return (
    <aside className="flex w-[320px] shrink-0 flex-col overflow-y-auto border-r border-rock-700 bg-rock-800">
      <header className="flex items-center justify-between border-b border-rock-700 px-4 py-2">
        <h2 className="plate text-[12px] text-chalk-dim">{demo ? 'Demo' : 'Controls'}</h2>
        <span className="readout text-[10px] text-mute">{STAGE_LABEL[stage]}</span>
      </header>
      {demoControls ? <DemoPanel /> : <div ref={host} data-testid="controls-host" className="flex-1" />}
      {stage === 'ANALYSIS' && !demo ? (
        <p className="px-4 py-3 text-[11px] leading-relaxed text-mute">
          Analysis is a read-only projection of the generated mine — there is nothing to generate
          here. The workspace opens in the centre.
        </p>
      ) : null}
      {demo ? null : <ResetFromHere />}
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
 * panel placed full-window; charts follow in PR-2). Round 3 B1: being
 * MOUNTED — actually shown — over a scene is what completes the Analysis
 * stage for that scene revision; a stage click alone never does. A scene
 * that changes while the workspace stays open completes again for the new
 * revision (the user is looking at the new mine's analysis). */
export function AnalysisCenter({ split = false }: { split?: boolean }) {
  const hasScene = useScenarioStore((s) => s.scene !== null)
  const sceneRevision = useScenarioStore((s) => s.sceneRevision)
  const markViewerStageComplete = useViewerStore((s) => s.markViewerStageComplete)
  useEffect(() => {
    if (hasScene) markViewerStageComplete('ANALYSIS', sceneRevision)
  }, [hasScene, sceneRevision, markViewerStageComplete])
  return (
    <div
      className={`absolute inset-y-0 right-0 z-10 overflow-y-auto bg-rock-900 ${
        split ? 'w-[58%] border-l border-rock-700' : 'left-0'
      }`}
      data-testid="analysis-center"
      data-split={split}
    >
      <div className={`mx-auto border-x border-rock-700 bg-rock-800 ${split ? '' : 'max-w-[1180px]'}`}>
        <AnalysisWorkspace />
      </div>
    </div>
  )
}
