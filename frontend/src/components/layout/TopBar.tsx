import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '@/api/client'
import { RibbonTabs } from '@/components/layout/Ribbon'
import { useShellStore } from '@/components/layout/shellStore'
import { openDemo } from '@/scenario/demos'
import { openScenario } from '@/scenario/openScenario'
import { LOCALES, useLocaleStore } from '@/i18n/locale'
import { tr } from '@/i18n/t'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useViewerStore } from '@/stores/viewerStore'

/**
 * Hardening H1 §4.2 / PR-3 — the top bar:
 *
 *   MineGen-AI · File ▾ · 1 Setup · 2 Design · … · 7 Export · View ·        backend
 *
 * The step tabs are the ribbon's TAB row (`RibbonTabs`): a step tab opens
 * its NEXT / failed stage (else its first stage) and the band under the bar
 * shows that step's tools; the View tab shows the viewport tools. The
 * 3D / 4D / Walk VIEW modes are not workflow steps: they live in the View
 * tab and in the switcher over the viewport. The File menu is the second
 * path to the same implementations (Open = the Setup stage's saved list,
 * Demos = the baked catalogue, Export = the Export stage, Import results =
 * Analysis › Simulation Results) — two paths, one implementation each; the
 * Setup band's Open… / Demos tools open this menu on that section.
 */
export function TopBar() {
  const demo = useScenarioStore((s) => s.demo)
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 15000 })

  return (
    <header className="flex h-10 items-center border-b border-rock-700/70 bg-gradient-to-b from-rock-800 to-rock-800/95 px-3 shadow-[0_1px_0_0_rgb(0_0_0/0.25)]">
      <div className="plate text-[16px] tracking-[0.12em] text-chalk">
        MineGen<span className="text-lamp">-AI</span>
      </div>
      <FileMenu />
      {demo ? (
        <span
          className="plate ml-2 rounded-sm border border-lamp/60 px-1.5 py-0.5 text-[10px] text-lamp"
          data-testid="demo-badge"
          title={tr('{title} — read-only demo; clone it to edit', { title: demo.title })}
        >
          {demo.labels.join(' · ')}
        </span>
      ) : null}

      <RibbonTabs />

      <div className="readout ml-auto flex items-center gap-2 text-[11px]">
        <LocaleSwitch />
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
              ? tr('backend unreachable')
              : 'connecting…'}
        </span>
      </div>
    </header>
  )
}

/** File ▾ — New mine / Open… / Demos / Export / Import results */
/**
 * PR-3 round 4 — the UI language (한국어 default, English). A presentation
 * choice remembered per browser; it changes no request, artifact or stage
 * (the app tree remounts, see `main.tsx`).
 */
function LocaleSwitch() {
  const locale = useLocaleStore((s) => s.locale)
  const setLocale = useLocaleStore((s) => s.setLocale)
  return (
    <div
      role="group"
      aria-label={tr('UI language')}
      data-testid="locale-switch"
      className="mr-2 flex rounded-sm border border-rock-700/80 p-px"
    >
      {LOCALES.map((l) => (
        <button
          key={l}
          type="button"
          onClick={() => setLocale(l)}
          aria-pressed={locale === l}
          data-locale={l}
          title={l === 'ko' ? '한국어' : 'English'}
          className={[
            'plate rounded-sm px-1.5 py-0.5 text-[10px] transition-colors',
            locale === l ? 'bg-rock-700 text-lamp' : 'text-mute hover:text-chalk',
          ].join(' ')}
        >
          {l === 'ko' ? '한' : 'EN'}
        </button>
      ))}
    </div>
  )
}

function FileMenu() {
  const [open, setOpen] = useState(false)
  const [openList, setOpenList] = useState(false)
  const [demoList, setDemoList] = useState(false)
  const ref = useRef<HTMLDivElement | null>(null)
  // PR-3: the Setup band's Open… / Demos tools open this menu on a section
  const request = useShellStore((s) => s.fileMenuRequest)
  const clearRequest = useShellStore((s) => s.clearFileMenuRequest)
  useEffect(() => {
    if (!request) return
    setOpen(true)
    setOpenList(request.section === 'OPEN')
    setDemoList(request.section === 'DEMOS')
    clearRequest()
  }, [request, clearRequest])
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
  // hardening PR-2 H4: the baked demo catalogue; a demo opens read-only in place
  const demos = useQuery({
    queryKey: ['demos'],
    queryFn: api.listDemos,
    enabled: open && demoList,
    retry: false,
    // PR #54 review B1: while the backend is baking the demos in the
    // background, re-read the catalogue so each one appears as it completes
    refetchInterval: (query) =>
      query.state.data?.materialization?.status === 'BAKING' ? 3000 : false,
  })
  const baking = demos.data?.materialization ?? null
  const loadDemo = useMutation({
    mutationFn: openDemo,
    onSuccess: () => setStage('SCENARIO'),
  })
  const demoError = loadDemo.error
  const demoErrorText =
    demoError instanceof ApiError
      ? `${demoError.code}: ${demoError.message}`
      : demoError
        ? demoError.message
        : null

  useEffect(() => {
    if (!open) return undefined
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
        setOpenList(false)
        setDemoList(false)
      }
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  const close = () => {
    setOpen(false)
    setOpenList(false)
    setDemoList(false)
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
      <span>{tr(label)}</span>
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
        {tr('File ▾')}
      </button>
      {demoErrorText ? (
        <span
          role="alert"
          className="ml-2 max-w-[520px] truncate align-middle text-[11px] text-danger"
          title={demoErrorText}
          data-testid="demo-open-error"
        >
          {tr('demo did not open — {error}', { error: demoErrorText })}
        </span>
      ) : null}
      {open ? (
        <div
          role="menu"
          aria-label="file"
          className="absolute left-0 top-full z-40 mt-1 w-56 rounded-md border border-rock-600/80 bg-rock-800/95 py-1 shadow-float backdrop-blur"
        >
          {item('New mine', () => {
            setStage('SCENARIO')
            close()
          })}
          {item('Open…', () => setOpenList((v) => !v), false, openList ? '▾' : '▸')}
          {openList ? (
            <ul className="max-h-48 overflow-y-auto border-y border-rock-700 bg-rock-900/60">
              {list.isSuccess && list.data.length === 0 ? (
                <li className="px-4 py-1 text-[11px] text-mute">{tr('No saved mines')}</li>
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
                <li className="px-4 py-1 text-[11px] text-mute">{tr('Loading…')}</li>
              ) : null}
            </ul>
          ) : null}
          {item('Demos', () => setDemoList((v) => !v), false, demoList ? '▾' : '▸')}
          {demoList ? (
            <ul
              className="max-h-56 overflow-y-auto border-y border-rock-700 bg-rock-900/60"
              data-testid="demo-list"
            >
              {baking?.status === 'BAKING' ? (
                <li
                  className="px-4 py-1 text-[11px] text-chalk-dim"
                  data-testid="demo-baking"
                  role="status"
                >
                  {tr('Baking demos…')}{' '}
                  <span className="readout text-[10px] text-mute">
                    {baking.recipeId ?? ''}
                    {baking.stage ? ` · ${baking.stage}` : ''}
                    {baking.pendingRecipes.length > 0
                      ? ` · ${tr('{n} more', { n: baking.pendingRecipes.length })}`
                      : ''}
                  </span>
                </li>
              ) : null}
              {baking && Object.keys(baking.failedRecipes).length > 0
                ? Object.entries(baking.failedRecipes).map(([id, reason]) => (
                    <li
                      key={id}
                      className="px-4 py-1 text-[11px] text-danger"
                      data-testid="demo-bake-failed"
                      title={reason}
                    >
                      {tr('{id} did not bake — {reason}', { id, reason })}
                    </li>
                  ))
                : null}
              {demos.isSuccess &&
              demos.data.status === 'NOT_BAKED' &&
              baking?.status !== 'BAKING' ? (
                <li className="px-4 py-1 text-[11px] text-mute">
                  {baking?.status === 'DISABLED'
                    ? tr('No demos baked on this backend (automatic baking is off)')
                    : tr('No demos baked on this backend')}
                </li>
              ) : null}
              {demos.isSuccess
                ? demos.data.demos.map((d) => (
                    <li key={d.id}>
                      <button
                        type="button"
                        role="menuitem"
                        disabled={!d.available || loadDemo.isPending}
                        title={d.available ? d.description : (d.reason ?? tr('unavailable'))}
                        onClick={() => {
                          loadDemo.mutate(d)
                          close()
                        }}
                        className={[
                          'flex w-full flex-col items-start px-4 py-1 text-left text-[11px] hover:bg-rock-700 disabled:cursor-not-allowed disabled:text-mute',
                          current?.id === d.id ? 'text-chalk' : 'text-chalk-dim',
                        ].join(' ')}
                      >
                        <span className="truncate">{d.title}</span>
                        <span className="readout text-[10px] text-mute">
                          {d.labels.join(' · ')} · {d.orebodyType} · {d.miningMethod}
                          {d.available ? '' : ` · ${tr('unavailable')}`}
                        </span>
                      </button>
                    </li>
                  ))
                : null}
              {demos.isPending ? (
                <li className="px-4 py-1 text-[11px] text-mute">{tr('Loading…')}</li>
              ) : null}
              {demos.isError ? (
                <li className="px-4 py-1 text-[11px] text-danger">
                  {demos.error instanceof ApiError
                    ? `${demos.error.code}: ${demos.error.message}`
                    : tr('demo catalogue unavailable')}
                </li>
              ) : null}
            </ul>
          ) : null}
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
