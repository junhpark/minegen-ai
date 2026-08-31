import { beforeEach, describe, expect, it } from 'vitest'
import { useTimelineStore } from '@/stores/timelineStore'
import { useViewerStore } from '@/stores/viewerStore'

describe('walkthrough temporal context (rules 111/112, §32)', () => {
  beforeEach(() => {
    useViewerStore.getState().setMode('DESIGN')
    useTimelineStore.setState({ startDay: 0, endDay: 1000, currentDay: 0 })
  })

  it('DESIGN/INFRASTRUCTURE -> Walk enters STATIC_FINAL with no snapshot', () => {
    for (const from of ['DESIGN', 'INFRASTRUCTURE'] as const) {
      useViewerStore.getState().setMode(from)
      useViewerStore.getState().setMode('WALKTHROUGH')
      const s = useViewerStore.getState()
      expect(s.walkthroughContext).toBe('STATIC_FINAL')
      expect(s.walkthroughSnapshotDay).toBeNull()
      expect(s.walkthroughReturnMode).toBe('DESIGN')
    }
  })

  it('4D -> Walk captures the exact current day as TIMELINE_SNAPSHOT', () => {
    useViewerStore.getState().setMode('4D')
    useTimelineStore.setState({ currentDay: 420.5 })
    useViewerStore.getState().setMode('WALKTHROUGH')
    const s = useViewerStore.getState()
    expect(s.walkthroughContext).toBe('TIMELINE_SNAPSHOT')
    expect(s.walkthroughSnapshotDay).toBe(420.5)
    expect(s.walkthroughReturnMode).toBe('4D')
  })

  it('HARD snapshot gate: later timeline changes never move the captured day', () => {
    useViewerStore.getState().setMode('4D')
    useTimelineStore.setState({ currentDay: 420.5 })
    useViewerStore.getState().setMode('WALKTHROUGH')
    useTimelineStore.getState().setCurrentDay(999)
    expect(useTimelineStore.getState().currentDay).toBe(999)
    expect(useViewerStore.getState().walkthroughSnapshotDay).toBe(420.5) // immutable
  })

  it('leaving WALKTHROUGH clears the temporal snapshot state', () => {
    useViewerStore.getState().setMode('4D')
    useTimelineStore.setState({ currentDay: 300 })
    useViewerStore.getState().setMode('WALKTHROUGH')
    useViewerStore.getState().setMode('4D')
    const s = useViewerStore.getState()
    expect(s.walkthroughContext).toBeNull()
    expect(s.walkthroughSnapshotDay).toBeNull()
    expect(s.cameraMode).toBe('orbit')
  })
})
