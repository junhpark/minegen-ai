import { beforeEach, describe, expect, it } from 'vitest'
import { useViewerStore } from './viewerStore'

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

  it('switches camera mode when entering WALKTHROUGH', () => {
    useViewerStore.getState().setMode('WALKTHROUGH')
    expect(useViewerStore.getState().cameraMode).toBe('walkthrough')
    useViewerStore.getState().setMode('DESIGN')
    expect(useViewerStore.getState().cameraMode).toBe('orbit')
  })
})
