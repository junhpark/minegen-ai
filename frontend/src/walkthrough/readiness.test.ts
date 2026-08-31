import { describe, expect, it } from 'vitest'
import type { WorldScene } from '@/types/scene'
import {
  deriveVisibleLayers,
  temporalWalkthroughReadiness,
  walkthroughReadiness,
} from './readiness'
import { useViewerStore } from '@/stores/viewerStore'

const POINTS: number[] = []
for (let i = 0; i <= 20; i++) POINTS.push(0, 3 * i, 200 - 0.3 * i)

const READY_SCENE = {
  tunnelMesh: { status: 'SUCCESS', meshUrl: '/files/tunnel.glb' },
  smoothedDecline: {
    status: 'SUCCESS',
    segments: [{ effectiveCenterline: { points: POINTS, pointCount: POINTS.length / 3 } }],
  },
} as unknown as WorldScene

describe('walkthrough readiness (§13)', () => {
  it('grades each prerequisite explicitly', () => {
    expect(walkthroughReadiness(null)).toBe('NO_SCENE')
    expect(walkthroughReadiness({} as WorldScene)).toBe('TUNNEL_NOT_GENERATED')
    expect(
      walkthroughReadiness({ tunnelMesh: { status: 'FAILED' } } as unknown as WorldScene),
    ).toBe('TUNNEL_FAILED')
    expect(
      walkthroughReadiness({
        tunnelMesh: { status: 'SUCCESS', meshUrl: '/x.glb' },
      } as unknown as WorldScene),
    ).toBe('SMOOTHED_NOT_AVAILABLE')
    expect(
      walkthroughReadiness({
        tunnelMesh: { status: 'SUCCESS', meshUrl: '/x.glb' },
        smoothedDecline: { status: 'SUCCESS', segments: [] },
      } as unknown as WorldScene),
    ).toBe('INVALID_SPAWN_GEOMETRY')
    expect(walkthroughReadiness(READY_SCENE)).toBe('READY')
  })
})

describe('walkthrough derived visibility (§15)', () => {
  const stored = new Set([
    'terrain',
    'tunnelMesh',
    'orebody',
    'faults',
    'accessTargets',
    'rawSearchPath',
    'smoothedDecline',
    'network',
    'networkGraph',
    'stopes',
    'backfill',
    'routers',
    'coverage',
    'sensors',
    'sensorCoverage',
  ])

  it('keeps the physical tunnel and passive terrain only in walkthrough', () => {
    const derived = deriveVisibleLayers('WALKTHROUGH', stored)
    expect([...derived].sort()).toEqual(['terrain', 'tunnelMesh'])
  })

  it('suppresses engineering, 4D, communication and sensor overlays', () => {
    const derived = deriveVisibleLayers('WALKTHROUGH', stored)
    for (const layer of [
      'orebody',
      'faults',
      'accessTargets',
      'rawSearchPath',
      'smoothedDecline',
      'network',
      'networkGraph',
      'stopes',
      'backfill',
      'routers',
      'coverage',
      'sensors',
      'sensorCoverage',
    ]) {
      expect(derived.has(layer)).toBe(false)
    }
  })

  it('returns the stored set untouched in every other mode', () => {
    expect(deriveVisibleLayers('DESIGN', stored)).toBe(stored)
    expect(deriveVisibleLayers('INFRASTRUCTURE', stored)).toBe(stored)
    expect(deriveVisibleLayers('4D', stored)).toBe(stored)
  })
})

describe('viewer camera-mode contract (§14)', () => {
  it('maps modes to a single camera-control owner without touching layers', () => {
    const before = useViewerStore.getState().visibleLayers
    useViewerStore.getState().setMode('WALKTHROUGH')
    expect(useViewerStore.getState().cameraMode).toBe('walkthrough')
    useViewerStore.getState().setMode('DESIGN')
    expect(useViewerStore.getState().cameraMode).toBe('orbit')
    useViewerStore.getState().setMode('WALKTHROUGH')
    useViewerStore.getState().setMode('DESIGN')
    expect(useViewerStore.getState().cameraMode).toBe('orbit')
    // mode churn never mutates the user's stored visible layers
    expect(useViewerStore.getState().visibleLayers).toBe(before)
  })
})

describe('temporal scenario/ramp prerequisite (PR #12 blocker 3)', () => {
  const temporalScene = {
    ...READY_SCENE,
    timeline: {
      status: 'SUCCESS',
      sourceRevision: 'rev',
      developments: [
        {
          edgeId: 'E:RAMP0',
          edgeType: 'RAMP',
          geometryRef: { artifact: 'decline_smoothed.json', segmentIndex: 0 },
          initialState: 'NOT_BUILT',
          transitions: [{ day: 10, state: 'ACTIVE' }],
        },
      ],
    },
  } as unknown as WorldScene

  it('fails closed without Scenario-authored ramp dimensions', () => {
    expect(temporalWalkthroughReadiness(temporalScene, 50, null)).toBe('SCENARIO_RAMP_UNAVAILABLE')
    expect(temporalWalkthroughReadiness(temporalScene, 50, undefined)).toBe(
      'SCENARIO_RAMP_UNAVAILABLE',
    )
    expect(
      temporalWalkthroughReadiness(temporalScene, 50, { tunnelWidth: Number.NaN, tunnelHeight: 5 }),
    ).toBe('SCENARIO_RAMP_UNAVAILABLE')
    expect(
      temporalWalkthroughReadiness(temporalScene, 50, { tunnelWidth: 5, tunnelHeight: 0 }),
    ).toBe('SCENARIO_RAMP_UNAVAILABLE')
  })

  it('is READY with authored dimensions and an ACTIVE first segment', () => {
    expect(
      temporalWalkthroughReadiness(temporalScene, 50, { tunnelWidth: 5, tunnelHeight: 5.5 }),
    ).toBe('READY')
    expect(
      temporalWalkthroughReadiness(temporalScene, 5, { tunnelWidth: 5, tunnelHeight: 5.5 }),
    ).toBe('NO_COMPLETED_SEGMENT')
  })
})
