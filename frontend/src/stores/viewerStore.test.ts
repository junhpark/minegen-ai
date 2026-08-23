import { beforeEach, describe, expect, it } from 'vitest'
import { useViewerStore } from './viewerStore'

describe('viewerStore', () => {
  beforeEach(() => {
    useViewerStore.setState(useViewerStore.getInitialState())
  })

  it('toggles layers without mutating previous set', () => {
    const before = useViewerStore.getState().visibleLayers
    useViewerStore.getState().toggleLayer('routers')
    const after = useViewerStore.getState().visibleLayers
    expect(after).not.toBe(before)
    expect(after.has('routers')).toBe(true)
    useViewerStore.getState().toggleLayer('routers')
    expect(useViewerStore.getState().visibleLayers.has('routers')).toBe(false)
  })

  it('switches camera mode when entering WALKTHROUGH', () => {
    useViewerStore.getState().setMode('WALKTHROUGH')
    expect(useViewerStore.getState().cameraMode).toBe('walkthrough')
    useViewerStore.getState().setMode('DESIGN')
    expect(useViewerStore.getState().cameraMode).toBe('orbit')
  })
})
