import { useScenarioStore } from '@/stores/scenarioStore'
import { useTimelineStore } from '@/stores/timelineStore'
import { useViewerStore } from '@/stores/viewerStore'
import type { ViewMode } from '@/types/workflow'
import {
  temporalReadinessMessage,
  temporalWalkthroughReadiness,
  walkthroughReadiness,
} from '@/walkthrough/readiness'

const VIEWS: { id: ViewMode; label: string }[] = [
  { id: '3D', label: '3D' },
  { id: '4D', label: '4D' },
  { id: 'WALK', label: 'Walk' },
]

/**
 * Hardening H1 §4.1 — 3D | 4D | Walk are VIEW modes of the viewport, not
 * workflow steps, so they live over the canvas and not in the ribbon. Walk
 * keeps its readiness gate: from 4D the TEMPORAL readiness at the current
 * day (rule 111), otherwise the static walkthrough readiness. Switching the
 * view never changes the stage, generates or mutates anything.
 */
export function ViewSwitcher() {
  const view = useViewerStore((s) => s.viewMode())
  const mode = useViewerStore((s) => s.mode)
  const setViewMode = useViewerStore((s) => s.setViewMode)
  const scene = useScenarioStore((s) => s.scene)
  const scenario = useScenarioStore((s) => s.scenario)
  const currentDay = useTimelineStore((s) => s.currentDay)
  const readiness =
    mode === '4D'
      ? temporalWalkthroughReadiness(scene, currentDay, scenario?.ramp ?? null)
      : walkthroughReadiness(scene)
  const walkTooltip = temporalReadinessMessage(readiness)
  return (
    <div
      className="pointer-events-auto absolute right-3 top-3 z-20 flex rounded-sm border border-rock-600 bg-rock-800/90 p-0.5 shadow"
      role="group"
      aria-label="view mode"
      data-testid="view-switcher"
    >
      {VIEWS.map((v) => {
        const active = v.id === view
        const walkDisabled = v.id === 'WALK' && readiness !== 'READY' && !active
        return (
          <button
            key={v.id}
            type="button"
            onClick={() => setViewMode(v.id)}
            aria-pressed={active}
            disabled={walkDisabled}
            title={v.id === 'WALK' ? walkTooltip : undefined}
            data-view={v.id}
            className={[
              'plate rounded-sm px-2.5 py-0.5 text-[12px] transition-colors disabled:cursor-not-allowed disabled:opacity-40',
              active
                ? 'bg-rock-700 text-lamp'
                : 'text-chalk-dim hover:bg-rock-700/60 hover:text-chalk',
            ].join(' ')}
          >
            {v.label}
          </button>
        )
      })}
    </div>
  )
}
