import { useMemo } from 'react'
import { BottomBar } from '@/components/layout/BottomBar'
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
        <div className="flex min-h-0 flex-1">
          {walkthrough ? null : <LeftPanel />}
          <main className="relative min-w-0 flex-1">
            <MineCanvas />
            {mode === 'ANALYSIS' ? <AnalysisCenter /> : <ViewSwitcher />}
          </main>
          {walkthrough ? null : <RightPanel />}
        </div>
        {walkthrough ? null : <BottomBar />}
      </div>
    </CardLayoutContext.Provider>
  )
}
