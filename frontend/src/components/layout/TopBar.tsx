import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api } from '@/api/client'
import { useStageGlyphs } from '@/components/layout/useStageGlyphs'
import { entryStageOf, stepOf, WORKFLOW_STEPS } from '@/components/layout/workflow'
import { openScenario } from '@/scenario/openScenario'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useViewerStore } from '@/stores/viewerStore'

/**
 * Hardening H1 §4.2 — the ribbon:
 *
 *   MineGen-AI · File ▾ · 1 Setup · 2 Design · 3 Network · 4 Mining · 5 Systems · 6 Analysis · 7 Export · backend
 *
 * A ribbon step opens its NEXT / failed stage (else its first stage). The
 * 3D / 4D / Walk VIEW modes are not here: they are a view switcher over the
 * viewport, because a view is not a workflow step. The File menu is the
 * second path to the same implementations (Open = the Setup stage's saved
 * list, Export = the Export stage, Import results = Analysis › Simulation
 * Results) — two paths, one implementation each.
 */
export function TopBar() {
  const stage = useViewerStore((s) => s.stage)
  const setStage = useViewerStore((s) => s.setStage)
  const glyphs = useStageGlyphs()
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 15000 })
  const currentStep = stepOf(stage)

  return (
    <header className="flex h-10 items-center border-b border-rock-700 bg-rock-800 px-3">
      <div className="plate text-[16px] text-chalk">
        MineGen<span className="text-lamp">-AI</span>
      </div>
      <FileMenu />

      <nav className="ml-4 flex gap-0.5" aria-label="workflow steps">
        {WORKFLOW_STEPS.map((step) => {
          const active = step.id === currentStep
          return (
            <button
              key={step.id}
              type="button"
              onClick={() => setStage(entryStageOf(step.id, glyphs))}
              aria-current={active ? 'step' : undefined}
              data-step={step.id}
              className={[
                'plate whitespace-nowrap rounded-sm px-2 py-1 text-[12px] transition-colors',
                active
                  ? 'bg-rock-700 text-lamp shadow-[inset_0_-2px_0_0_var(--color-lamp)]'
                  : 'text-chalk-dim hover:bg-rock-700/60 hover:text-chalk',
              ].join(' ')}
            >
              <span className="readout mr-1 text-[10px] text-mute">{step.index}</span>
              {step.label}
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

/** File ▾ — New mine / Open… / Demos / Export / Import results */
function FileMenu() {
  const [open, setOpen] = useState(false)
  const [openList, setOpenList] = useState(false)
  const ref = useRef<HTMLDivElement | null>(null)
  const setStage = useViewerStore((s) => s.setStage)
  const setAnalysisTab = useViewerStore((s) => s.setAnalysisTab)
  const current = useScenarioStore((s) => s.scenario)
  const qc = useQueryClient()
  const list = useQuery({
    queryKey: ['scenarios'],
    queryFn: api.listScenarios,
    enabled: open && openList,
  })
  const load = useMutation({
    mutationFn: openScenario,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['scenarios'] })
      setStage('SCENARIO')
    },
  })

  useEffect(() => {
    if (!open) return undefined
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
        setOpenList(false)
      }
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  const close = () => {
    setOpen(false)
    setOpenList(false)
  }
  const item = (label: string, onClick: () => void, disabled = false, hint?: string) => (
    <button
      type="button"
      role="menuitem"
      disabled={disabled}
      onClick={() => {
        onClick()
      }}
      className="flex w-full items-center justify-between gap-3 px-3 py-1.5 text-left text-[12px] text-chalk hover:bg-rock-700 disabled:cursor-not-allowed disabled:text-mute"
    >
      <span>{label}</span>
      {hint ? <span className="readout text-[10px] text-mute">{hint}</span> : null}
    </button>
  )

  return (
    <div ref={ref} className="relative ml-3">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="plate rounded-sm px-2 py-1 text-[12px] text-chalk-dim hover:bg-rock-700/60 hover:text-chalk"
      >
        File ▾
      </button>
      {open ? (
        <div
          role="menu"
          aria-label="file"
          className="absolute left-0 top-full z-40 mt-1 w-56 rounded-sm border border-rock-600 bg-rock-800 py-1 shadow-xl"
        >
          {item('New mine', () => {
            setStage('SCENARIO')
            close()
          })}
          {item('Open…', () => setOpenList((v) => !v), false, openList ? '▾' : '▸')}
          {openList ? (
            <ul className="max-h-48 overflow-y-auto border-y border-rock-700 bg-rock-900/60">
              {list.isSuccess && list.data.length === 0 ? (
                <li className="px-4 py-1 text-[11px] text-mute">No saved mines</li>
              ) : null}
              {list.isSuccess
                ? list.data.map((s) => (
                    <li key={s.id}>
                      <button
                        type="button"
                        role="menuitem"
                        onClick={() => {
                          load.mutate(s.id)
                          close()
                        }}
                        className={[
                          'flex w-full items-center justify-between px-4 py-1 text-left text-[11px] hover:bg-rock-700',
                          current?.id === s.id ? 'text-chalk' : 'text-chalk-dim',
                        ].join(' ')}
                      >
                        <span className="truncate">{s.name}</span>
                        <span className="readout text-[10px] text-mute">#{s.seed}</span>
                      </button>
                    </li>
                  ))
                : null}
              {list.isPending ? (
                <li className="px-4 py-1 text-[11px] text-mute">Loading…</li>
              ) : null}
            </ul>
          ) : null}
          {item('Demos', () => undefined, true, 'coming')}
          <div className="my-1 border-t border-rock-700" />
          {item(
            'Export…',
            () => {
              setStage('EXPORT')
              close()
            },
            current === null,
          )}
          {item(
            'Import results…',
            () => {
              setStage('ANALYSIS')
              setAnalysisTab('SIMULATION')
              close()
            },
            current === null,
          )}
        </div>
      ) : null}
    </div>
  )
}
