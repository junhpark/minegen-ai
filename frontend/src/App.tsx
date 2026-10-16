import { useMemo } from 'react'
import { BottomBar } from '@/components/layout/BottomBar'
import { DemoTourController } from '@/components/layout/DemoTourController'
import { AnalysisCenter, LeftPanel } from '@/components/layout/LeftPanel'
import { RightPanel } from '@/components/layout/RightPanel'
import { useShellStore } from '@/components/layout/shellStore'
import { StepperBar } from '@/components/layout/StepperBar'
import { TopBar } from '@/components/layout/TopBar'
import { ViewSwitcher } from '@/components/layout/ViewSwitcher'
import { stagesOfStep, stepOf } from '@/components/layout/workflow'
import { CardLayoutContext, type CardLayout } from '@/components/ui/cardLayout'
import { SimulationOverlayController } from '@/results/SimulationOverlayController'
import { MineCanvas } from '@/scene/MineCanvas'
import { useViewerStore } from '@/stores/viewerStore'

/**
 * Main layout (hardening H1 §4.2 — the guided workflow shell):
 *
 *   ┌ MineGen-AI · File ▾ · 1 Setup … 7 Export ·                    backend ┐
 *   │ [Scenario ✓][Method ✓] │ [Layout ●][Levels ○] …                       │
 *   ├────────────┬──────────────────────────────────┬─────────────────────────┤
 *   │ CONTROLS   │      3D / 4D / Walk viewport     │ STATUS & RESULTS        │
 *   │ stage      │      (view switcher)             │ step statuses · metrics │
 *   │ [action]   │      Analysis: centre workspace  │ failureReason · Details │
 *   │ Reset…     │                                  │ VIEW · Inspector        │
 *   ├────────────┴──────────────────────────────────┴─────────────────────────┤
 *   │ status bar: World · Ramp · Levels · Network · Timeline │ 4D control     │
 *   └─────────────────────────────────────────────────────────────────────────┘
 *
 * WALK is immersive: the columns and the status bar are hidden and the
 * canvas takes the full area (the view switcher stays, to leave). The
 * Analysis step covers the viewport with its workspace, so the view
 * switcher yields to it there — a stage chip leads back to the 3D view.
 */
export default function App() {
  const mode = useViewerStore((s) => s.mode)
  const stage = useViewerStore((s) => s.stage)
  // hardening PR-2 H3 §8: the Analysis workspace has NO full-size canvas by
  // default; "Show 3D context" mounts it beside the workspace (split view)
  const analysisShow3d = useViewerStore((s) => s.analysisShow3d)
  const analysis = mode === 'ANALYSIS'
  const controlsHost = useShellStore((s) => s.controlsHost)
  const resultsHost = useShellStore((s) => s.resultsHost)
  const walkthrough = mode === 'WALKTHROUGH'
  const layout = useMemo<CardLayout>(
    () => ({
      placement: 'SPLIT',
      stage,
      stepStages: stagesOfStep(stepOf(stage)),
      controlsHost,
      resultsHost,
    }),
    [stage, controlsHost, resultsHost],
  )
  return (
    <CardLayoutContext.Provider value={layout}>
      <div className="flex h-full flex-col">
        <TopBar />
        {walkthrough ? null : <StepperBar />}
        <SimulationOverlayController />
        <DemoTourController />
        <div className="flex min-h-0 flex-1">
          {walkthrough ? null : <LeftPanel />}
          <main className="relative min-w-0 flex-1">
            {analysis && !analysisShow3d ? null : <MineCanvas />}
            {analysis ? <AnalysisCenter split={analysisShow3d} /> : <ViewSwitcher />}
          </main>
          {walkthrough ? null : <RightPanel />}
        </div>
        {walkthrough ? null : <BottomBar />}
      </div>
    </CardLayoutContext.Provider>
  )
}
