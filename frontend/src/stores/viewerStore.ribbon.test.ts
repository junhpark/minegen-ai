import { beforeEach, describe, expect, it } from 'vitest'
import { useViewerStore } from './viewerStore'

/** Hardening PR-3 — the ribbon tab, the flow dock and the pane flags are
 * viewer-local presentation state. */
describe('viewer store — ribbon / flow dock / panes (hardening PR-3)', () => {
  beforeEach(() => {
    useViewerStore.setState({
      mode: 'DESIGN',
      stage: 'SCENARIO',
      ribbonTab: null,
      flowDock: true,
      panes: { controls: true, results: true },
    })
  })

  it('the View tab is an explicit selection that any stage change clears', () => {
    const s = useViewerStore.getState()
    expect(s.ribbonTab).toBeNull()
    s.setRibbonTab('VIEW')
    expect(useViewerStore.getState().ribbonTab).toBe('VIEW')
    s.setStage('LAYOUT')
    expect(useViewerStore.getState().stage).toBe('LAYOUT')
    expect(useViewerStore.getState().ribbonTab).toBeNull()
  })

  it('the flow dock and the two columns toggle independently; nothing else moves', () => {
    const s = useViewerStore.getState()
    s.setFlowDock(false)
    expect(useViewerStore.getState().flowDock).toBe(false)
    s.setPane('results', false)
    expect(useViewerStore.getState().panes).toEqual({ controls: true, results: false })
    s.setPane('controls', false)
    s.setPane('results', true)
    expect(useViewerStore.getState().panes).toEqual({ controls: false, results: true })
    expect(useViewerStore.getState().stage).toBe('SCENARIO')
    expect(useViewerStore.getState().mode).toBe('DESIGN')
  })

  it('a scenario transition keeps the viewing preferences (they name no object)', () => {
    const s = useViewerStore.getState()
    s.setFlowDock(false)
    s.setPane('controls', false)
    s.resetScenarioScopedState()
    expect(useViewerStore.getState().flowDock).toBe(false)
    expect(useViewerStore.getState().panes.controls).toBe(false)
  })
})
