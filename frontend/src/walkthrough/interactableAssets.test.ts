import { describe, expect, it } from 'vitest'
import type { WorldScene } from '@/types/scene'
import { resolveWalkthroughAssets } from './interactableAssets'

function scene(over: Record<string, unknown> = {}): WorldScene {
  return {
    network: {
      status: 'SUCCESS',
      nodes: [{ id: 'N:PORTAL' }, { id: 'N:J1' }, { id: 'N:LEVEL' }, { id: 'N:DRIFT_END' }],
      edges: [
        { id: 'E:RAMP1', type: 'RAMP', fromNode: 'N:PORTAL', toNode: 'N:J1' },
        { id: 'E:DRIFT1', type: 'DRIFT', fromNode: 'N:J1', toNode: 'N:LEVEL' },
        { id: 'E:XC1', type: 'CROSSCUT', fromNode: 'N:LEVEL', toNode: 'N:DRIFT_END' },
      ],
    },
    communication: {
      status: 'SUCCESS',
      candidates: [
        { id: 'C:RAMP', locationKind: 'EDGE', edgeId: 'E:RAMP1', nodeId: null },
        { id: 'C:DRIFT', locationKind: 'EDGE', edgeId: 'E:DRIFT1', nodeId: null },
        { id: 'C:NODE_RAMP', locationKind: 'NODE', nodeId: 'N:J1', edgeId: null },
        { id: 'C:NODE_DRIFT', locationKind: 'NODE', nodeId: 'N:LEVEL', edgeId: null },
        { id: 'C:GHOST_EDGE', locationKind: 'EDGE', edgeId: 'E:MISSING', nodeId: null },
      ],
      selectedAssets: [
        { id: 'RTR:1', assetType: 'MESH_ROUTER', candidateId: 'C:RAMP', position: [0, 10, -5] },
        { id: 'RTR:2', assetType: 'MESH_ROUTER', candidateId: 'C:DRIFT', position: [9, 9, -9] },
        { id: 'RTR:3', assetType: 'MESH_ROUTER', candidateId: 'C:NODE_RAMP', position: [1, 2, -3] },
      ],
    },
    sensors: {
      status: 'SUCCESS',
      candidates: [
        { id: 'S:RAMP', locationKind: 'EDGE', edgeId: 'E:RAMP1', nodeId: null },
        { id: 'S:XC', locationKind: 'EDGE', edgeId: 'E:XC1', nodeId: null },
        { id: 'S:NODE_DRIFT', locationKind: 'NODE', nodeId: 'N:DRIFT_END', edgeId: null },
      ],
      selectedSensors: [
        { id: 'SEN:1', assetType: 'GAS_SENSOR', candidateId: 'S:RAMP', position: [0, 20, -7] },
        { id: 'SEN:2', assetType: 'GAS_SENSOR', candidateId: 'S:XC', position: [40, 20, -7] },
        { id: 'SEN:3', assetType: 'GAS_SENSOR', candidateId: 'S:NODE_DRIFT', position: [50, 0, 0] },
      ],
    },
    ...over,
  } as unknown as WorldScene
}

describe('walkthrough interactable-asset resolver (rule 106, §29)', () => {
  it('keeps RAMP-domain assets and excludes drift/crosscut-only assets', () => {
    const { assets } = resolveWalkthroughAssets(scene())
    const ids = assets.map((a) => a.id)
    expect(ids).toContain('RTR:1') // router on RAMP edge
    expect(ids).toContain('RTR:3') // node incident to a RAMP edge
    expect(ids).toContain('SEN:1') // sensor on RAMP
    expect(ids).not.toContain('RTR:2') // DRIFT edge
    expect(ids).not.toContain('SEN:2') // CROSSCUT edge
    expect(ids).not.toContain('SEN:3') // node with no incident RAMP
  })

  it('maps positions through the canonical mine->Three transform only', () => {
    const { assets } = resolveWalkthroughAssets(scene())
    const rtr = assets.find((a) => a.id === 'RTR:1')!
    expect(rtr.positionMine).toEqual([0, 10, -5])
    expect(rtr.positionThree).toEqual([0, -5, -10])
    expect(rtr.kind).toBe('MESH_ROUTER')
    expect(rtr.source).toBe('COMMUNICATION')
  })

  it('records malformed candidate references as issues, never crashes', () => {
    const s = scene()
    ;(s.communication!.selectedAssets as unknown[]).push({
      id: 'RTR:GHOST',
      assetType: 'MESH_ROUTER',
      candidateId: 'C:GHOST_EDGE',
      position: [0, 0, 0],
    })
    ;(s.communication!.selectedAssets as unknown[]).push({
      id: 'RTR:NOCAND',
      assetType: 'MESH_ROUTER',
      candidateId: 'C:NOT_A_CANDIDATE',
      position: [0, 0, 0],
    })
    const { assets, issues } = resolveWalkthroughAssets(s)
    expect(assets.map((a) => a.id)).not.toContain('RTR:GHOST')
    expect(assets.map((a) => a.id)).not.toContain('RTR:NOCAND')
    expect(issues.some((i) => i.includes('RTR:GHOST'))).toBe(true)
    expect(issues.some((i) => i.includes('RTR:NOCAND'))).toBe(true)
  })

  it('rejects duplicate asset ids deterministically (first wins, issue recorded)', () => {
    const s = scene()
    ;(s.sensors!.selectedSensors as unknown[]).push({
      id: 'SEN:1',
      assetType: 'GAS_SENSOR',
      candidateId: 'S:RAMP',
      position: [0, 25, -8],
    })
    const a = resolveWalkthroughAssets(s)
    const b = resolveWalkthroughAssets(s)
    expect(a.assets.filter((x) => x.id === 'SEN:1')).toHaveLength(1)
    expect(a.assets.find((x) => x.id === 'SEN:1')!.positionMine).toEqual([0, 20, -7])
    expect(a.issues).toContain('duplicate asset id SEN:1 rejected')
    expect(a.assets.map((x) => x.id)).toEqual(b.assets.map((x) => x.id))
  })

  it('yields an empty list when payloads are missing or failed — walkthrough keeps working', () => {
    expect(resolveWalkthroughAssets(null).assets).toEqual([])
    expect(resolveWalkthroughAssets(scene({ communication: null, sensors: null })).assets).toEqual(
      [],
    )
    expect(resolveWalkthroughAssets(scene({ network: null })).assets).toEqual([])
    const failed = scene()
    ;(failed.sensors as { status: string }).status = 'FAILED'
    const ids = resolveWalkthroughAssets(failed).assets.map((a) => a.id)
    expect(ids).toContain('RTR:1')
    expect(ids.some((i) => i.startsWith('SEN:'))).toBe(false)
  })
})
