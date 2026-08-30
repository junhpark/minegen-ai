import { describe, expect, it } from 'vitest'
import {
  communicationLayersActive,
  communicationVisibleIn4D,
  demandRenderData,
  routerMarkers,
} from '@/infrastructure/view'
import {
  afterCommunicationRegen,
  afterLevelsRegen,
  afterNetworkRegen,
  afterStopesRegen,
  afterTimelineRegen,
  afterUpstreamRegen,
} from '@/scene/invalidation'
import type { CommunicationPayload, WorldScene } from '@/types/scene'

const communication: CommunicationPayload = {
  status: 'SUCCESS',
  failureReason: null,
  sourceRevision: 'rev',
  model: {
    assetType: 'MESH_ROUTER',
    coverageModel: 'NETWORK_DISTANCE_THRESHOLD_V0_1',
    solver: 'CONNECTED_GREEDY_PATH_SET_COVER_V0_1',
    optimalityClaim: false,
    coverageRangeM: 100,
    backhaulRangeM: 120,
    requiredCoverageFraction: 1,
  },
  candidates: [],
  demands: [
    {
      id: 'COMM:DEMAND:NODE:P',
      locationKind: 'NODE',
      nodeId: 'P',
      edgeId: null,
      chainageM: null,
      position: [0, 0, 0],
      weight: 1,
    },
    {
      id: 'COMM:DEMAND:EDGE:E:P1',
      locationKind: 'EDGE',
      nodeId: null,
      edgeId: 'E',
      chainageM: 20,
      position: [20, 0, 0],
      weight: 1,
    },
  ],
  selectedAssets: [
    {
      id: 'COMM:ASSET:COMM:CAND:NODE:P',
      assetType: 'MESH_ROUTER',
      candidateId: 'COMM:CAND:NODE:P',
      position: [1.5, 2.5, -3.5],
      backhaulParentAssetId: null,
      hopCount: 0,
    },
  ],
  demandCoverage: [
    {
      demandId: 'COMM:DEMAND:NODE:P',
      covered: true,
      servingAssetId: 'COMM:ASSET:COMM:CAND:NODE:P',
      networkDistanceM: 0,
    },
    {
      demandId: 'COMM:DEMAND:EDGE:E:P1',
      covered: false,
      servingAssetId: null,
      networkDistanceM: null,
    },
  ],
  metrics: null,
}

// only the fields the pure helpers touch matter for these contracts
const scene = {
  levels: { status: 'SUCCESS' },
  network: { status: 'SUCCESS' },
  stopes: { status: 'SUCCESS' },
  timeline: { status: 'SUCCESS' },
  communication,
} as unknown as WorldScene

describe('communication view assembly (rules 88/91/92)', () => {
  it('activates layers only in INFRASTRUCTURE mode with SUCCESS payload', () => {
    expect(communicationLayersActive('INFRASTRUCTURE', communication)).toBe(true)
    expect(communicationLayersActive('DESIGN', communication)).toBe(false)
    expect(communicationLayersActive('4D', communication)).toBe(false)
    expect(communicationLayersActive('INFRASTRUCTURE', null)).toBe(false)
    expect(
      communicationLayersActive('INFRASTRUCTURE', { ...communication, status: 'FAILED' }),
    ).toBe(false)
  })

  it('never presents static routers as installed in 4D (rule 91)', () => {
    expect(communicationVisibleIn4D()).toBe(false)
  })

  it('passes backend router positions through untransformed', () => {
    expect(routerMarkers(communication)).toEqual([
      { id: 'COMM:ASSET:COMM:CAND:NODE:P', position: [1.5, 2.5, -3.5], hopCount: 0 },
    ])
  })

  it('splits demand points by backend coverage only — no distance math', () => {
    const { covered, uncovered } = demandRenderData(communication)
    expect(covered).toEqual([[0, 0, 0]])
    expect(uncovered).toEqual([[20, 0, 0]])
  })
})

describe('frontend invalidation mirror (rules 74/79/86/92)', () => {
  it('upstream regeneration clears the whole design chain', () => {
    const next = afterUpstreamRegen(scene)
    expect(next.levels).toBeNull()
    expect(next.network).toBeNull()
    expect(next.stopes).toBeNull()
    expect(next.timeline).toBeNull()
    expect(next.communication).toBeNull()
  })

  it('levels regeneration cascades to communication', () => {
    const next = afterLevelsRegen(scene, scene.levels!)
    expect(next.network).toBeNull()
    expect(next.stopes).toBeNull()
    expect(next.timeline).toBeNull()
    expect(next.communication).toBeNull()
  })

  it('network regeneration clears timeline AND communication, keeps stopes', () => {
    const next = afterNetworkRegen(scene, scene.network!)
    expect(next.timeline).toBeNull()
    expect(next.communication).toBeNull()
    expect(next.stopes).toBe(scene.stopes)
  })

  it('stopes regeneration clears timeline but PRESERVES communication', () => {
    const next = afterStopesRegen(scene, scene.stopes!)
    expect(next.timeline).toBeNull()
    expect(next.communication).toBe(communication)
  })

  it('timeline regeneration preserves communication (siblings)', () => {
    const next = afterTimelineRegen(scene, scene.timeline!)
    expect(next.communication).toBe(communication)
    expect(next.network).toBe(scene.network)
  })

  it('communication regeneration touches nothing else', () => {
    const next = afterCommunicationRegen(scene, communication)
    expect(next.network).toBe(scene.network)
    expect(next.stopes).toBe(scene.stopes)
    expect(next.timeline).toBe(scene.timeline)
    expect(next.communication).toBe(communication)
  })
})

describe('panel enable contract (§27)', () => {
  it('pins the network gate: null/FAILED disabled, SUCCESS enabled', async () => {
    const { canGenerateCommunication } = await import('@/infrastructure/view')
    expect(canGenerateCommunication(null)).toBe(false)
    expect(canGenerateCommunication({ status: 'FAILED' })).toBe(false)
    expect(canGenerateCommunication({ status: 'SUCCESS' })).toBe(true)
  })
})
