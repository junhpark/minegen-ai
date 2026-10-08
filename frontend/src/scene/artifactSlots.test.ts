import { describe, expect, it } from 'vitest'
import type { WorldScene } from '@/types/scene'
import { ARTIFACT_SLOTS, clearDeletedArtifacts } from './artifactSlots'

const marker = (tag: string) => ({ status: 'SUCCESS', tag }) as unknown

function scene(over: Partial<Record<keyof WorldScene, unknown>> = {}): WorldScene {
  return {
    scenarioId: 's',
    accessTargets: marker('targets'),
    decline: marker('decline'),
    smoothedDecline: { owningArtifact: 'layout_v2_selected.json', segments: [] },
    legacySmoothedDecline: marker('legacy'),
    rampSource: { activeSource: 'LAYOUT_V2', owningArtifact: 'layout_v2_selected.json' },
    layoutV2: marker('catalogue'),
    layoutV2Selected: marker('selected'),
    levelAccesses: marker('accesses'),
    tunnelMesh: marker('tunnel'),
    developmentMesh: marker('dev'),
    levels: marker('levels'),
    shafts: marker('shafts'),
    network: marker('network'),
    capabilityGraph: marker('cap'),
    stopes: marker('stopes'),
    timeline: marker('timeline'),
    communication: marker('comm'),
    sensors: marker('sensors'),
    ...over,
  } as unknown as WorldScene
}

describe('reset → scene slots (hardening H1 §4.4)', () => {
  it('empties exactly the slots of the deleted files, in the backend order given', () => {
    const next = clearDeletedArtifacts(scene(), [
      'levels.json',
      'development_mesh.json',
      'development_mesh.glb', // no slot: ignored
      'network.json',
      'capability_graph.json',
    ])
    expect(next.levels).toBeNull()
    expect(next.developmentMesh).toBeNull()
    expect(next.network).toBeNull()
    expect(next.capabilityGraph).toBeNull()
    // everything else is untouched — the frontend applies the closure, it never widens it
    expect(next.tunnelMesh).toEqual(marker('tunnel'))
    expect(next.stopes).toEqual(marker('stopes'))
    expect(next.layoutV2).toEqual(marker('catalogue'))
    expect(next.smoothedDecline).not.toBeNull()
  })

  it('drops the ACTIVE Effective Ramp slot only when its owning artifact was deleted', () => {
    const v2 = clearDeletedArtifacts(scene(), ['layout_v2_selected.json', 'level_accesses.json'])
    expect(v2.layoutV2Selected).toBeNull()
    expect(v2.levelAccesses).toBeNull()
    expect(v2.smoothedDecline).toBeNull()
    const legacyActive = scene({
      smoothedDecline: { owningArtifact: 'decline_smoothed.json', segments: [] },
      rampSource: { activeSource: 'LEGACY', owningArtifact: 'decline_smoothed.json' },
    })
    const keep = clearDeletedArtifacts(legacyActive, ['layout_v2_selected.json'])
    expect(keep.smoothedDecline).not.toBeNull()
    const drop = clearDeletedArtifacts(legacyActive, ['decline_smoothed.json'])
    expect(drop.smoothedDecline).toBeNull()
    expect(drop.legacySmoothedDecline).toBeNull()
  })

  it('returns the same scene object when nothing it knows was deleted', () => {
    const s = scene({ levels: null })
    expect(clearDeletedArtifacts(s, [])).toBe(s)
    expect(clearDeletedArtifacts(s, ['ramp_source.json', 'levels.json', 'unknown.bin'])).toBe(s)
  })

  it('maps every registered derived json artifact to a scene slot', () => {
    expect(Object.keys(ARTIFACT_SLOTS).sort()).toEqual(
      [
        'capability_graph.json',
        'communication.json',
        'decline.json',
        'decline_smoothed.json',
        'development_mesh.json',
        'layout_v2.json',
        'layout_v2_selected.json',
        'level_accesses.json',
        'levels.json',
        'network.json',
        'sensors.json',
        'shaft_mesh.json',
        'shafts.json',
        'stopes.json',
        'targets.json',
        'timeline.json',
        'tunnel_mesh.json',
      ].sort(),
    )
  })
})
