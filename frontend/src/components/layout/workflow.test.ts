import { describe, expect, it } from 'vitest'
import type { WorldScene } from '@/types/scene'
import { STAGE_IDS } from '@/types/workflow'
import {
  designTabFor,
  entryStageOf,
  modeForStage,
  nextStage,
  resetStageFor,
  resettable,
  stageStatuses,
  stepOf,
  WORKFLOW_STEPS,
} from './workflow'

const ok = (tag: string) => ({ status: 'SUCCESS', tag }) as unknown
const failed = (tag: string) => ({ status: 'FAILED', tag }) as unknown

function scene(over: Partial<Record<keyof WorldScene, unknown>> = {}): WorldScene {
  return {
    scenarioId: 's',
    rampSource: { activeSource: 'LAYOUT_V2', available: false },
    layoutV2: null,
    levels: null,
    tunnelMesh: null,
    developmentMesh: null,
    shafts: null,
    network: null,
    capabilityGraph: null,
    stopes: null,
    timeline: null,
    communication: null,
    sensors: null,
    ...over,
  } as unknown as WorldScene
}

const none = new Set<never>()

describe('workflow model (hardening H1 §4.1–4.3)', () => {
  it('declares the seven ribbon steps in order with every stage exactly once', () => {
    expect(WORKFLOW_STEPS.map((s) => `${String(s.index)} ${s.label}`)).toEqual([
      '1 Setup',
      '2 Design',
      '3 Network',
      '4 Mining',
      '5 Systems',
      '6 Analysis',
      '7 Export',
    ])
    const all = WORKFLOW_STEPS.flatMap((s) => s.stages)
    expect(all).toEqual([...STAGE_IDS])
    for (const st of STAGE_IDS)
      expect(WORKFLOW_STEPS.find((s) => s.id === stepOf(st))?.stages).toContain(st)
  })

  it('maps stages to the application mode of their controls and to the pre-shell tabs', () => {
    expect(modeForStage('LAYOUT')).toBe('DESIGN')
    expect(modeForStage('COMMUNICATION')).toBe('INFRASTRUCTURE')
    expect(modeForStage('ANALYSIS')).toBe('ANALYSIS')
    expect(modeForStage('EXPORT')).toBe('DESIGN')
    expect(designTabFor('METHOD')).toBe('MINING')
    expect(designTabFor('EXCAVATION')).toBe('DEVELOP')
    expect(designTabFor('CAPABILITY')).toBe('NETWORK')
    expect(designTabFor('LAYOUT')).toBe('LAYOUT')
  })

  it('maps each stage to its backend reset stage explicitly (Setup → WORLD preview only)', () => {
    expect(resetStageFor('SCENARIO')).toBe('WORLD')
    expect(resetStageFor('METHOD')).toBe('WORLD')
    expect(resetStageFor('LEVELS')).toBe('LEVELS')
    expect(resetStageFor('EXCAVATION')).toBe('EXCAVATION')
    expect(resetStageFor('ANALYSIS')).toBeNull()
    expect(resetStageFor('EXPORT')).toBeNull()
    expect(resettable('SCENARIO')).toBe(false)
    expect(resettable('LEVELS')).toBe(true)
    expect(resettable('EXPORT')).toBe(false)
  })

  it('with nothing loaded the first stage is NEXT and everything else waits', () => {
    const g = stageStatuses({
      scenario: false,
      scene: null,
      shaftSpecCount: 0,
      running: none,
      completed: none,
    })
    expect(g.SCENARIO).toBe('NEXT')
    expect(g.METHOD).toBe('WAITING')
    expect(g.LAYOUT).toBe('WAITING')
    expect(g.SHAFTS).toBe('OPTIONAL')
    expect(g.ANALYSIS).toBe('WAITING')
    expect(g.EXPORT).toBe('WAITING')
    expect(Object.values(g).filter((x) => x === 'NEXT')).toHaveLength(1)
  })

  it('reads the chain from the scene: done stages, one NEXT, a failure marked where it is', () => {
    const g = stageStatuses({
      scenario: true,
      scene: scene({
        rampSource: { activeSource: 'LAYOUT_V2', available: true },
        levels: ok('levels'),
        tunnelMesh: ok('tunnel'),
        developmentMesh: null,
        network: failed('network'),
      }),
      shaftSpecCount: 0,
      running: none,
      completed: none,
    })
    expect(g.SCENARIO).toBe('DONE')
    expect(g.METHOD).toBe('DONE')
    expect(g.LAYOUT).toBe('DONE')
    expect(g.LEVELS).toBe('DONE')
    expect(g.EXCAVATION).toBe('NEXT') // one of the two meshes is missing
    expect(g.SHAFTS).toBe('OPTIONAL')
    expect(g.NETWORK).toBe('FAILED')
    expect(g.CAPABILITY).toBe('WAITING')
    expect(g.PRODUCTION).toBe('WAITING')
    expect(Object.values(g).filter((x) => x === 'NEXT')).toHaveLength(1)
  })

  it('an ACCESS-ONLY development mesh next to failed levels is not a completed Excavation (S1)', () => {
    const base = {
      rampSource: { activeSource: 'LAYOUT_V2', available: true },
      levels: failed('levels'),
      tunnelMesh: ok('tunnel'),
    }
    const accessOnly = stageStatuses({
      scenario: true,
      scene: scene({
        ...base,
        developmentMesh: { status: 'SUCCESS', sources: { levels: false, levelAccesses: true } },
      }),
      shaftSpecCount: 0,
      running: none,
      completed: none,
    })
    expect(accessOnly.LEVELS).toBe('FAILED')
    expect(accessOnly.EXCAVATION).not.toBe('DONE')
    // round 2 S1: Excavation waits for Levels — the failed stage is the focus,
    // nothing is NEXT while it blocks the chain
    expect(accessOnly.EXCAVATION).toBe('WAITING')
    expect(Object.values(accessOnly).filter((x) => x === 'NEXT')).toHaveLength(0)
    expect(entryStageOf('DESIGN', accessOnly)).toBe('LEVELS')
    const full = stageStatuses({
      scenario: true,
      scene: scene({
        ...base,
        levels: ok('levels'),
        developmentMesh: { status: 'SUCCESS', sources: { levels: true, levelAccesses: true } },
      }),
      shaftSpecCount: 0,
      running: none,
      completed: none,
    })
    expect(full.EXCAVATION).toBe('DONE')
  })

  it('a layout with no feasible candidate is a failed stage; a running job shows as running', () => {
    const g = stageStatuses({
      scenario: true,
      scene: scene({ layoutV2: { status: 'NO_FEASIBLE_CANDIDATE' } }),
      shaftSpecCount: 2,
      running: new Set(['LEVELS'] as const),
      completed: none,
    })
    expect(g.LAYOUT).toBe('FAILED')
    expect(g.LEVELS).toBe('RUNNING')
    expect(g.SHAFTS).toBe('WAITING') // declared shafts are a real stage
  })

  it('Analysis follows the last Systems stage and Export follows Analysis; the viewer completes them (S2)', () => {
    const built = scene({
      rampSource: { activeSource: 'LAYOUT_V2', available: true },
      levels: ok('levels'),
      tunnelMesh: ok('tunnel'),
      developmentMesh: { status: 'SUCCESS', sources: { levels: true, levelAccesses: true } },
      network: ok('network'),
      capabilityGraph: ok('capability'),
      stopes: ok('stopes'),
      timeline: ok('timeline'),
      communication: ok('communication'),
      sensors: ok('sensors'),
    })
    const input = { scenario: true, scene: built, shaftSpecCount: 0, running: none }
    const g = stageStatuses({ ...input, completed: none })
    expect(g.SENSORS).toBe('DONE')
    expect(g.ANALYSIS).toBe('NEXT')
    expect(g.EXPORT).toBe('WAITING')
    expect(Object.values(g).filter((x) => x === 'NEXT')).toHaveLength(1)
    // opening Analysis completes it for this viewer; Export becomes next
    const analysed = stageStatuses({ ...input, completed: new Set(['ANALYSIS'] as const) })
    expect(analysed.ANALYSIS).toBe('DONE')
    expect(analysed.EXPORT).toBe('NEXT')
    // a downloaded package completes Export: the whole flow is done, nothing is next
    const exported = stageStatuses({
      ...input,
      completed: new Set(['ANALYSIS', 'EXPORT'] as const),
    })
    expect(exported.EXPORT).toBe('DONE')
    expect(Object.values(exported).filter((x) => x === 'NEXT')).toHaveLength(0)
    // a viewer completion never counts while its chain is broken (the mine
    // was reset): Analysis waits again, and so does the Export behind it
    const reset = stageStatuses({
      ...input,
      scene: scene({ ...built, sensors: null }),
      completed: new Set(['ANALYSIS', 'EXPORT'] as const),
    })
    expect(reset.SENSORS).toBe('NEXT')
    expect(reset.ANALYSIS).toBe('WAITING')
    expect(reset.EXPORT).toBe('WAITING')
    // Analysis is still before Export even when the user never opened it
    const skipped = stageStatuses({ ...input, completed: new Set(['EXPORT'] as const) })
    expect(skipped.ANALYSIS).toBe('NEXT')
    expect(skipped.EXPORT).toBe('WAITING')
  })

  it('a ribbon step opens its next / failed stage, else its first stage', () => {
    const g = stageStatuses({
      scenario: true,
      scene: scene({ rampSource: { activeSource: 'LAYOUT_V2', available: true } }),
      shaftSpecCount: 0,
      running: none,
      completed: none,
    })
    expect(entryStageOf('DESIGN', g)).toBe('LEVELS')
    expect(entryStageOf('SETUP', g)).toBe('SCENARIO')
    expect(entryStageOf('NETWORK', g)).toBe('NETWORK')
    expect(nextStage('SCENARIO')).toBe('METHOD')
    expect(nextStage('EXPORT')).toBeNull()
  })
})
