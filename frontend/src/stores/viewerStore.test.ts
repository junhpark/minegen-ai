import { beforeEach, describe, expect, it } from 'vitest'
import { completedStagesFor, useViewerStore } from './viewerStore'

describe('viewerStore', () => {
  beforeEach(() => {
    useViewerStore.setState(useViewerStore.getInitialState())
  })

  it('toggles layers without mutating previous set', () => {
    const before = useViewerStore.getState().visibleLayers
    expect(before.has('routers')).toBe(true) // infrastructure defaults ON (hotfix 2)
    useViewerStore.getState().toggleLayer('routers')
    const after = useViewerStore.getState().visibleLayers
    expect(after).not.toBe(before)
    expect(after.has('routers')).toBe(false)
    useViewerStore.getState().toggleLayer('routers')
    expect(useViewerStore.getState().visibleLayers.has('routers')).toBe(true)
  })

  it('infrastructure families are visible by default (hotfix 2, item 6)', () => {
    const layers = useViewerStore.getState().visibleLayers
    for (const id of ['routers', 'coverage', 'sensors', 'sensorCoverage'] as const) {
      expect(layers.has(id)).toBe(true)
    }
  })

  it('has no grade-blocks layer at all (Phase 18, rule 127)', () => {
    const layers = useViewerStore.getState().visibleLayers
    expect([...layers]).not.toContain('gradeBlocks')
  })

  it('diagnostic layers default OFF (Phase 17.1 §2/§3)', () => {
    const layers = useViewerStore.getState().visibleLayers
    expect(layers.has('rawSearchPath')).toBe(false) // §2 raw Hybrid-A* path
    expect(layers.has('rockQuality')).toBe(false) // §3 Field Slice
    // the layers they could obscure stay on
    expect(layers.has('smoothedDecline')).toBe(true)
    expect(layers.has('tunnelMesh')).toBe(true)
  })

  it('resetScenarioScopedState drops object identity but keeps layer preferences', () => {
    useViewerStore.getState().toggleLayer('rawSearchPath')
    useViewerStore.setState({ selectedObjectId: 'A:stope-1' })
    useViewerStore.getState().resetScenarioScopedState()
    expect(useViewerStore.getState().selectedObjectId).toBeNull()
    expect(useViewerStore.getState().visibleLayers.has('rawSearchPath')).toBe(true)
  })

  it('a viewer completion counts only for the scene revision it was made on (round 3 B2)', () => {
    const st = () => useViewerStore.getState()
    st().markViewerStageComplete('ANALYSIS', 7)
    expect(completedStagesFor(st().completedViewerStages, 7)).toEqual(new Set(['ANALYSIS']))
    // the mine moved on (reset / regeneration): nothing carries over
    expect(completedStagesFor(st().completedViewerStages, 8)).toEqual(new Set())
    st().markViewerStageComplete('EXPORT', 7)
    expect(completedStagesFor(st().completedViewerStages, 7)).toEqual(
      new Set(['ANALYSIS', 'EXPORT']),
    )
    // a completion on a NEW revision starts a new set (no revival of the old one)
    st().markViewerStageComplete('ANALYSIS', 8)
    expect(completedStagesFor(st().completedViewerStages, 8)).toEqual(new Set(['ANALYSIS']))
    expect(completedStagesFor(st().completedViewerStages, 7)).toEqual(new Set())
    // a completion of an older revision never clobbers the current set
    st().markViewerStageComplete('EXPORT', 7)
    expect(completedStagesFor(st().completedViewerStages, 8)).toEqual(new Set(['ANALYSIS']))
    expect(completedStagesFor(st().completedViewerStages, 7)).toEqual(new Set())
    // marking the same completion again is a no-op (no re-render churn)
    const before = st().completedViewerStages
    st().markViewerStageComplete('ANALYSIS', 8)
    expect(st().completedViewerStages).toBe(before)
    // the scenario-scoped reset drops every completion
    st().resetScenarioScopedState()
    expect(completedStagesFor(st().completedViewerStages, 8)).toEqual(new Set())
  })

  it('a stage click never completes Analysis; opening it from 4D / Walk leaves that view (round 3 B1)', () => {
    const st = () => useViewerStore.getState()
    st().setStage('ANALYSIS')
    expect(completedStagesFor(st().completedViewerStages, 0)).toEqual(new Set())
    expect(st().mode).toBe('ANALYSIS')
    // from 4D: the Analysis workspace renders only in the ANALYSIS mode, so
    // the view is left explicitly instead of surviving the stage change
    st().setStage('LEVELS')
    st().setViewMode('4D')
    expect(st().mode).toBe('4D')
    st().setStage('ANALYSIS')
    expect(st().mode).toBe('ANALYSIS')
    // from Walk: the exit clears the walkthrough snapshot state (rule 112)
    st().setStage('LEVELS')
    st().setMode('WALKTHROUGH')
    expect(st().mode).toBe('WALKTHROUGH')
    st().setStage('ANALYSIS')
    expect(st().mode).toBe('ANALYSIS')
    expect(st().cameraMode).toBe('orbit')
    expect(st().walkthroughContext).toBeNull()
    // every other stage keeps a 4D view (a VIEW choice survives a stage change)
    st().setViewMode('4D')
    st().setStage('EXPORT')
    expect(st().mode).toBe('4D')
  })

  it('switches camera mode when entering WALKTHROUGH', () => {
    useViewerStore.getState().setMode('WALKTHROUGH')
    expect(useViewerStore.getState().cameraMode).toBe('walkthrough')
    useViewerStore.getState().setMode('DESIGN')
    expect(useViewerStore.getState().cameraMode).toBe('orbit')
  })
})
