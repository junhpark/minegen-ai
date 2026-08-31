import { beforeEach, describe, expect, it } from 'vitest'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useTimelineStore } from '@/stores/timelineStore'
import type { WorldScene } from '@/types/scene'
import { temporalSessionIdentity } from './temporalPlan'
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

function sessionScene(rev: string): WorldScene {
  return {
    timeline: { status: 'SUCCESS', sourceRevision: rev, developments: [] },
    smoothedDecline: {
      status: 'SUCCESS',
      segments: [
        {
          levelId: 'SEG:A',
          effectiveCenterline: { points: [0, 0, 0, 9, 0, -1], pointCount: 2 },
        },
      ],
    },
    tunnelMesh: { status: 'SUCCESS', meshUrl: '/files/tunnel.glb' },
  } as unknown as WorldScene
}

describe('temporal session artifact immutability (rule 112, PR #12 blocker 2)', () => {
  beforeEach(() => {
    useViewerStore.getState().setMode('DESIGN')
    useScenarioStore.setState({ scene: sessionScene('rev-1') })
    useTimelineStore.setState({ startDay: 0, endDay: 1000, currentDay: 200 })
  })

  it('identity is content-based: no-op refetch keeps it, regeneration changes it', () => {
    const a = temporalSessionIdentity(sessionScene('rev-1'))
    const b = temporalSessionIdentity(sessionScene('rev-1')) // new objects, same content
    const c = temporalSessionIdentity(sessionScene('rev-2')) // regenerated timeline
    expect(a).not.toBeNull()
    expect(b).toBe(a)
    expect(c).not.toBe(a)
    expect(temporalSessionIdentity(null)).toBeNull()
  })

  it('enter snapshot -> replace artifact -> captured session is NOT recomputed; exit condition fires', () => {
    useViewerStore.getState().setMode('4D')
    useViewerStore.getState().setMode('WALKTHROUGH')
    const captured = useViewerStore.getState().walkthroughSnapshotIdentity
    expect(captured).toBe(temporalSessionIdentity(sessionScene('rev-1')))
    // another VALID timeline artifact replaces the scene mid-session
    useScenarioStore.setState({ scene: sessionScene('rev-2') })
    const s = useViewerStore.getState()
    // the captured snapshot never re-snapshots to the new topology…
    expect(s.walkthroughSnapshotIdentity).toBe(captured)
    expect(s.walkthroughSnapshotDay).toBe(200)
    // …and the production exit condition (MineCanvas gate) now detects it
    const live = temporalSessionIdentity(useScenarioStore.getState().scene)
    expect(live).not.toBe(captured)
  })

  it('leaving WALKTHROUGH clears the captured session identity', () => {
    useViewerStore.getState().setMode('4D')
    useViewerStore.getState().setMode('WALKTHROUGH')
    useViewerStore.getState().setMode('4D')
    expect(useViewerStore.getState().walkthroughSnapshotIdentity).toBeNull()
  })
})
