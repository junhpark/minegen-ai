import { describe, expect, it } from 'vitest'
import {
  clipPolylineByFractions,
  developmentProgress,
  stateAt,
  staticExcavationVisibleIn4D,
} from '@/timeline/evaluate'
import { useTimelineStore } from '@/stores/timelineStore'
import type { DevelopmentTimeline } from '@/types/scene'

const dev: DevelopmentTimeline = {
  edgeId: 'RAMP:L01',
  edgeType: 'RAMP',
  geometryRef: { artifact: 'decline_smoothed.json', segmentIndex: 0 },
  taskId: 'TASK:DEVELOP:RAMP:L01',
  initialState: 'NOT_BUILT',
  transitions: [
    { day: 10, state: 'DEVELOPING' },
    { day: 20, state: 'ACTIVE' },
  ],
  progressStartDay: 10,
  progressEndDay: 20,
  pointChainageFractions: [0, 0.25, 0.75, 1],
}

// straight 3-segment polyline along +x matching the fractions above
const points = [0, 0, 0, 1, 0, 0, 3, 0, 0, 4, 0, 0]

describe('exact transition boundary lookup (rule 84)', () => {
  it('applies the latest transition with day <= day, exactly at the boundary', () => {
    expect(stateAt('NOT_BUILT', dev.transitions, 9.999999)).toBe('NOT_BUILT')
    expect(stateAt('NOT_BUILT', dev.transitions, 10)).toBe('DEVELOPING')
    expect(stateAt('NOT_BUILT', dev.transitions, 19.999999)).toBe('DEVELOPING')
    expect(stateAt('NOT_BUILT', dev.transitions, 20)).toBe('ACTIVE')
    expect(stateAt('NOT_BUILT', dev.transitions, 1e9)).toBe('ACTIVE')
  })
})

describe('development progress (rule 83)', () => {
  it('is 0 before, linear during, 1 after, clamped', () => {
    expect(developmentProgress(dev, 0)).toBe(0)
    expect(developmentProgress(dev, 10)).toBe(0)
    expect(developmentProgress(dev, 15)).toBeCloseTo(0.5, 12)
    expect(developmentProgress(dev, 20)).toBe(1)
    expect(developmentProgress(dev, 999)).toBe(1)
  })
})

describe('partial chainage clip (rule 31)', () => {
  it('never exposes centerline beyond the cut', () => {
    const half = clipPolylineByFractions(points, dev.pointChainageFractions, 0.5)
    // kept: fractions 0, 0.25; cut interpolated at 0.5 between 0.25 and 0.75
    expect(half).toEqual([0, 0, 0, 1, 0, 0, 2, 0, 0])
    const maxX = Math.max(...half.filter((_, i) => i % 3 === 0))
    expect(maxX).toBeLessThan(4)
  })
  it('handles the extremes and vertex-exact cuts', () => {
    expect(clipPolylineByFractions(points, dev.pointChainageFractions, 0)).toEqual([])
    expect(clipPolylineByFractions(points, dev.pointChainageFractions, 1)).toEqual(points)
    const atVertex = clipPolylineByFractions(points, dev.pointChainageFractions, 0.25)
    expect(atVertex).toEqual([0, 0, 0, 1, 0, 0, 1, 0, 0])
    const tiny = clipPolylineByFractions(points, dev.pointChainageFractions, 0.1)
    expect(tiny.slice(0, 3)).toEqual([0, 0, 0])
    expect(tiny[3]).toBeCloseTo(0.4, 12)
  })
})

describe('4D static suppression (§23)', () => {
  it('hides static excavation only while the timeline drives the scene', () => {
    expect(staticExcavationVisibleIn4D(true)).toBe(false)
    // Phase 01–09 design-mode rendering remains unchanged
    expect(staticExcavationVisibleIn4D(false)).toBe(true)
  })
})

describe('timeline store (§20)', () => {
  it('setRange resets currentDay and clamps scrubbing to the range', () => {
    const s = useTimelineStore.getState()
    s.setRange(0, 100)
    useTimelineStore.getState().setCurrentDay(-5)
    expect(useTimelineStore.getState().currentDay).toBe(0)
    useTimelineStore.getState().setCurrentDay(1000)
    expect(useTimelineStore.getState().currentDay).toBe(100)
    useTimelineStore.getState().setCurrentDay(42.5)
    expect(useTimelineStore.getState().currentDay).toBe(42.5)
  })
  it('play/pause and speed are explicit', () => {
    useTimelineStore.getState().play()
    expect(useTimelineStore.getState().playing).toBe(true)
    useTimelineStore.getState().setSpeed(20)
    expect(useTimelineStore.getState().speed).toBe(20)
    useTimelineStore.getState().pause()
    expect(useTimelineStore.getState().playing).toBe(false)
  })
})
