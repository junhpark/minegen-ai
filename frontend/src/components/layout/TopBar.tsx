import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useViewerStore } from '@/stores/viewerStore'
import { READINESS_MESSAGES, walkthroughReadiness } from '@/walkthrough/readiness'
import { APP_MODES, type AppMode } from '@/types/enums'

const MODE_LABELS: Record<AppMode, string> = {
  DESIGN: 'Design',
  INFRASTRUCTURE: 'Infra',
  '4D': '4D',
  WALKTHROUGH: 'Walk',
  ANALYSIS: 'Analysis',
}

export function TopBar() {
  const mode = useViewerStore((s) => s.mode)
  const setMode = useViewerStore((s) => s.setMode)
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 15000 })
  const scene = useScenarioStore((s) => s.scene)
  const readiness = walkthroughReadiness(scene)
  const walkTooltip = readiness === 'READY' ? undefined : READINESS_MESSAGES[readiness]

  return (
    <header className="flex h-11 items-center border-b border-rock-700 bg-rock-800 px-4">
      <div className="plate text-[17px] text-chalk">
        MineGen<span className="text-lamp">-AI</span>
      </div>
      <span className="readout ml-3 text-[10px] text-mute">v0.1</span>

      <nav className="ml-8 flex gap-1" aria-label="application mode">
        {APP_MODES.map((m) => {
          const active = m === mode
          const walkDisabled = m === 'WALKTHROUGH' && readiness !== 'READY'
          return (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              aria-pressed={active}
              disabled={walkDisabled}
              title={m === 'WALKTHROUGH' ? walkTooltip : undefined}
              className={[
                'plate rounded-sm px-3 py-1 text-[13px] transition-colors',
                active
                  ? 'bg-rock-700 text-lamp shadow-[inset_0_-2px_0_0_var(--color-lamp)]'
                  : 'text-chalk-dim hover:bg-rock-700/60 hover:text-chalk',
              ].join(' ')}
            >
              {MODE_LABELS[m]}
            </button>
          )
        })}
      </nav>

      <div className="readout ml-auto flex items-center gap-2 text-[11px]">
        <span
          className={[
            'inline-block h-2 w-2 rounded-full',
            health.isSuccess ? 'bg-lamp' : health.isError ? 'bg-danger' : 'bg-mute',
          ].join(' ')}
          aria-hidden
        />
        <span className="text-chalk-dim">
          {health.isSuccess
            ? `backend ${health.data.version} · ${health.data.coordinateSystem}`
            : health.isError
              ? 'backend unreachable'
              : 'connecting…'}
        </span>
      </div>
    </header>
  )
}
