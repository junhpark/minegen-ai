import { describe, expect, it } from 'vitest'
import type { WorldScene } from '@/types/scene'
import { resolveSelectedObject, SENSOR_PROXY_DISCLAIMER } from './selectionResolver'

const SCENE = {
  accessTargets: {
    levels: [{ candidates: [{ id: 'ACC:1', position: [1, 2, 3] }] }],
  },
  communication: {
    status: 'SUCCESS',
    model: { coverageModel: 'NETWORK_DISTANCE_THRESHOLD_V0_1', coverageRangeM: 40 },
    selectedAssets: [
      {
        id: 'RTR:1',
        assetType: 'MESH_ROUTER',
        candidateId: 'C:1',
        position: [0, 0, 0],
        hopCount: 2,
        backhaulParentAssetId: null,
      },
    ],
  },
  sensors: {
    status: 'SUCCESS',
    model: { coverageModel: 'NETWORK_DISTANCE_MONITORING_THRESHOLD_V0_1', monitoringRangeM: 60 },
    selectedSensors: [
      { id: 'SEN:1', assetType: 'GAS_SENSOR', candidateId: 'S:1', position: [5, 6, 7] },
    ],
  },
} as unknown as WorldScene

describe('canonical selection resolver (rule 109, §32)', () => {
  it('resolves the existing access-candidate identity unchanged', () => {
    const r = resolveSelectedObject(SCENE, 'ACC:1')
    expect(r?.kind).toBe('ACCESS_CANDIDATE')
  })

  it('resolves MESH_ROUTER and GAS_SENSOR by authoritative id', () => {
    const rtr = resolveSelectedObject(SCENE, 'RTR:1')
    expect(rtr?.kind).toBe('MESH_ROUTER')
    expect(rtr?.kind === 'MESH_ROUTER' && rtr.asset.hopCount).toBe(2)
    expect(rtr?.kind === 'MESH_ROUTER' && rtr.model?.coverageRangeM).toBe(40)
    const sen = resolveSelectedObject(SCENE, 'SEN:1')
    expect(sen?.kind).toBe('GAS_SENSOR')
    expect(sen?.kind === 'GAS_SENSOR' && sen.model?.monitoringRangeM).toBe(60)
  })

  it('returns null for unknown and stale ids (assets removed by regeneration)', () => {
    expect(resolveSelectedObject(SCENE, 'NOPE')).toBeNull()
    expect(resolveSelectedObject(null, 'RTR:1')).toBeNull()
    const regenerated = {
      ...SCENE,
      communication: { ...(SCENE.communication as object), selectedAssets: [] },
    } as unknown as WorldScene
    expect(resolveSelectedObject(regenerated, 'RTR:1')).toBeNull()
  })

  it('keeps the Phase 12 proxy disclaimer verbatim', () => {
    expect(SENSOR_PROXY_DISCLAIMER).toBe(
      'Network-distance monitoring-layout proxy. Not a gas-dispersion or physical detection model.',
    )
  })
})
