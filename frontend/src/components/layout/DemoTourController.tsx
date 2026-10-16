import { useEffect } from 'react'
import { nextTourPreset, TOUR_INTERVAL_MS } from '@/scenario/demos'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useViewerStore } from '@/stores/viewerStore'

/**
 * Hardening PR-2 H4 — the demo Auto tour: while a demo is open, the tour is
 * on and the viewport is an orbit view (3D / 4D; never Walk, never the
 * Analysis workspace), the camera preset advances ISO → TOP → FIT every
 * `TOUR_INTERVAL_MS` through the same `requestCameraPreset` the View panel
 * uses. Viewer-local; it touches no scenario, artifact or timeline.
 */
export function DemoTourController() {
  const demo = useScenarioStore((s) => s.demo !== null)
  const tour = useViewerStore((s) => s.demoTour)
  const mode = useViewerStore((s) => s.mode)
  const cameraMode = useViewerStore((s) => s.cameraMode)
  const active = demo && tour && cameraMode === 'orbit' && mode !== 'ANALYSIS'
  useEffect(() => {
    if (!active) return undefined
    const id = window.setInterval(() => {
      const s = useViewerStore.getState()
      s.requestCameraPreset(nextTourPreset(s.cameraPreset.kind))
    }, TOUR_INTERVAL_MS)
    return () => window.clearInterval(id)
  }, [active])
  return null
}
