/**
 * Phase 20C.2B frontend mirrors of the shaft / capability-graph lifecycle
 * (rules 184–185): levels → shafts → network → capability graph. The
 * backend deletes the files; these helpers keep the in-memory manifest
 * consistent without a reload.
 */
import { describe, expect, it } from 'vitest'
import type {
  CapabilityGraphPayload,
  LevelsPayload,
  NetworkPayload,
  ShaftsPayload,
  WorldScene,
} from '@/types/scene'
import {
  afterCapabilityGraphRegen,
  afterLevelsRegen,
  afterNetworkRegen,
  afterShaftsRegen,
  afterUpstreamRegen,
} from './invalidation'

const marker = (tag: string) => ({ status: 'SUCCESS', tag }) as unknown

function scene(): WorldScene {
  return {
    scenarioId: 's',
    levels: marker('levels') as LevelsPayload,
    developmentMesh: marker('devmesh'),
    shafts: marker('shafts') as ShaftsPayload,
    network: marker('network') as NetworkPayload,
    capabilityGraph: marker('cap') as CapabilityGraphPayload,
    stopes: marker('stopes'),
    timeline: marker('timeline'),
    communication: marker('comm'),
    sensors: marker('sensors'),
    tunnelMesh: marker('tunnel'),
  } as unknown as WorldScene
}

describe('shaft / capability invalidation mirrors', () => {
  it('levels regeneration drops shafts, network and the capability graph', () => {
    const next = afterLevelsRegen(scene(), marker('levels2') as LevelsPayload)
    expect(next.shafts).toBeNull()
    expect(next.network).toBeNull()
    expect(next.capabilityGraph).toBeNull()
    expect(next.tunnelMesh).not.toBeNull() // rule 74: the ramp tunnel survives
  })

  it('shaft regeneration drops the network chain but keeps levels, meshes and stopes', () => {
    const payload = marker('shafts2') as ShaftsPayload
    const next = afterShaftsRegen(scene(), payload)
    expect(next.shafts).toBe(payload)
    expect(next.network).toBeNull()
    expect(next.capabilityGraph).toBeNull()
    expect(next.timeline).toBeNull()
    expect(next.communication).toBeNull()
    expect(next.sensors).toBeNull()
    expect(next.levels).not.toBeNull()
    expect(next.developmentMesh).not.toBeNull()
    expect(next.stopes).not.toBeNull()
  })

  it('network regeneration drops the capability graph and keeps the shafts', () => {
    const next = afterNetworkRegen(scene(), marker('network2') as NetworkPayload)
    expect(next.capabilityGraph).toBeNull()
    expect(next.shafts).not.toBeNull()
    expect(next.stopes).not.toBeNull()
  })

  it('capability regeneration touches nothing else; upstream regeneration clears both', () => {
    const cap = marker('cap2') as CapabilityGraphPayload
    const next = afterCapabilityGraphRegen(scene(), cap)
    expect(next.capabilityGraph).toBe(cap)
    expect(next.network).not.toBeNull()
    expect(next.shafts).not.toBeNull()
    const up = afterUpstreamRegen(scene())
    expect(up.shafts).toBeNull()
    expect(up.capabilityGraph).toBeNull()
  })
})
