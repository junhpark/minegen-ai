import { describe, expect, it } from 'vitest'
import {
  canGenerateSensors,
  sensorDemandRenderData,
  sensorLayersActive,
  sensorMarkers,
  sensorsVisibleIn4D,
} from '@/infrastructure/view'
import {
  afterCommunicationRegen,
  afterLevelsRegen,
  afterNetworkRegen,
  afterSensorsRegen,
  afterStopesRegen,
  afterTimelineRegen,
  afterUpstreamRegen,
} from '@/scene/invalidation'
import type { CommunicationPayload, SensorPayload, WorldScene } from '@/types/scene'

const sensors: SensorPayload = {
  status: 'SUCCESS',
  failureReason: null,
  sourceRevision: 'rev',
  model: {
    assetType: 'GAS_SENSOR',
    coverageModel: 'NETWORK_DISTANCE_MONITORING_THRESHOLD_V0_1',
    solver: 'GREEDY_SET_COVER_V0_1',
    optimalityClaim: false,
    monitoringRangeM: 60,
    requiredCoverageFraction: 1,
  },
  candidates: [],
  demands: [
    {
      id: 'SENSOR:DEMAND:NODE:P',
      locationKind: 'NODE',
      nodeId: 'P',
      edgeId: null,
      chainageM: null,
      position: [0, 0, 0],
      weight: 1,
    },
    {
      id: 'SENSOR:DEMAND:EDGE:E:P1',
      locationKind: 'EDGE',
      nodeId: null,
      edgeId: 'E',
      chainageM: 20,
      position: [20, 0, 0],
      weight: 1,
    },
  ],
  selectedSensors: [
    {
      id: 'SENSOR:ASSET:SENSOR:CAND:NODE:P',
      assetType: 'GAS_SENSOR',
      candidateId: 'SENSOR:CAND:NODE:P',
      position: [7.5, -2.5, 3.5],
    },
  ],
  demandCoverage: [
    {
      demandId: 'SENSOR:DEMAND:NODE:P',
      covered: true,
      servingSensorId: 'SENSOR:ASSET:SENSOR:CAND:NODE:P',
      networkDistanceM: 0,
    },
    {
      demandId: 'SENSOR:DEMAND:EDGE:E:P1',
      covered: false,
      servingSensorId: null,
      networkDistanceM: null,
    },
  ],
  metrics: null,
}

const scene = {
  levels: { status: 'SUCCESS' },
  network: { status: 'SUCCESS' },
  stopes: { status: 'SUCCESS' },
  timeline: { status: 'SUCCESS' },
  communication: { status: 'SUCCESS' } as unknown as CommunicationPayload,
  sensors,
} as unknown as WorldScene

describe('sensor view assembly (rules 95/97/98)', () => {
  it('pins the generation gate: null/FAILED disabled, SUCCESS enabled', () => {
    expect(canGenerateSensors(null)).toBe(false)
    expect(canGenerateSensors({ status: 'FAILED' })).toBe(false)
    expect(canGenerateSensors({ status: 'SUCCESS' })).toBe(true)
  })

  it('activates layers only in INFRASTRUCTURE mode with SUCCESS payload', () => {
    expect(sensorLayersActive('INFRASTRUCTURE', sensors)).toBe(true)
    expect(sensorLayersActive('DESIGN', sensors)).toBe(false)
    expect(sensorLayersActive('4D', sensors)).toBe(false)
    expect(sensorLayersActive('INFRASTRUCTURE', null)).toBe(false)
    expect(sensorLayersActive('INFRASTRUCTURE', { ...sensors, status: 'FAILED' })).toBe(false)
  })

  it('never presents static sensors as installed in 4D (rule 97)', () => {
    expect(sensorsVisibleIn4D()).toBe(false)
  })

  it('passes backend sensor positions through untransformed', () => {
    expect(sensorMarkers(sensors)).toEqual([
      { id: 'SENSOR:ASSET:SENSOR:CAND:NODE:P', position: [7.5, -2.5, 3.5] },
    ])
  })

  it('splits monitoring demands by backend coverage only — no distance math', () => {
    const { covered, uncovered } = sensorDemandRenderData(sensors)
    expect(covered).toEqual([[0, 0, 0]])
    expect(uncovered).toEqual([[20, 0, 0]])
  })
})

describe('sensor invalidation mirror (rules 92/98 siblings)', () => {
  it('network regeneration clears sensors (and communication)', () => {
    const next = afterNetworkRegen(scene, scene.network!)
    expect(next.sensors).toBeNull()
    expect(next.communication).toBeNull()
    expect(next.stopes).toBe(scene.stopes)
  })

  it('levels/upstream regeneration clears sensors', () => {
    expect(afterLevelsRegen(scene, scene.levels!).sensors).toBeNull()
    expect(afterUpstreamRegen(scene).sensors).toBeNull()
  })

  it('stopes and timeline regeneration preserve sensors', () => {
    expect(afterStopesRegen(scene, scene.stopes!).sensors).toBe(sensors)
    expect(afterTimelineRegen(scene, scene.timeline!).sensors).toBe(sensors)
  })

  it('communication regeneration preserves sensors', () => {
    const next = afterCommunicationRegen(scene, scene.communication!)
    expect(next.sensors).toBe(sensors)
  })

  it('sensor regeneration preserves communication, timeline, network, stopes', () => {
    const next = afterSensorsRegen(scene, sensors)
    expect(next.communication).toBe(scene.communication)
    expect(next.timeline).toBe(scene.timeline)
    expect(next.network).toBe(scene.network)
    expect(next.stopes).toBe(scene.stopes)
    expect(next.sensors).toBe(sensors)
  })
})
