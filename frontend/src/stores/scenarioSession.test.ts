/**
 * Scenario identity isolation (Phase 17.1 §1).
 *
 * The bug: derived results were written with `setScene({ ...scene, X })`,
 * where `scene` came from the render in which the mutation started. A job
 * launched under scenario A that resolved AFTER scenario B had loaded wrote
 * the whole stale scenario-A manifest back into the store, so A's decline,
 * tunnel, levels, network, stopes and timeline reappeared under B.
 *
 * These tests reproduce that asynchronous cross-contamination explicitly:
 * a derived write is STARTED under A, the scenario is switched to B, and
 * only then is A's result allowed to resolve.
 */
import { beforeEach, describe, expect, it } from 'vitest'
import type { Scenario } from '@/types/api'
import type { WorldScene } from '@/types/scene'
import { activateScenario, activateScenarioRevision, scenarioEpoch } from './scenarioSession'
import { useScenarioStore } from './scenarioStore'
import { useSliceStore } from './sliceStore'
import { useTimelineStore } from './timelineStore'
import { useViewerStore } from './viewerStore'
import { useResultsStore } from './resultsStore'

function scenario(id: string, orebodyType = 'TABULAR'): Scenario {
  return { id, name: id, orebody: { orebodyType } } as unknown as Scenario
}

/** A scene manifest carrying one marker per derived product. */
function scene(scenarioId: string, tag: string): WorldScene {
  return {
    scenarioId,
    accessTargets: { tag },
    decline: { tag },
    smoothedDecline: { tag },
    tunnelMesh: { tag },
    levels: { tag },
    network: { tag },
    stopes: { tag },
    timeline: { tag },
    communication: { tag },
    sensors: { tag },
  } as unknown as WorldScene
}

const DERIVED = [
  'accessTargets',
  'decline',
  'smoothedDecline',
  'tunnelMesh',
  'levels',
  'network',
  'stopes',
  'timeline',
  'communication',
  'sensors',
] as const

function state() {
  return useScenarioStore.getState()
}

beforeEach(() => {
  useScenarioStore.setState(useScenarioStore.getInitialState())
  useSliceStore.setState(useSliceStore.getInitialState())
  useTimelineStore.setState(useTimelineStore.getInitialState())
  useViewerStore.setState(useViewerStore.getInitialState())
  useResultsStore.setState(useResultsStore.getInitialState())
})

describe('Phase 23C simulation results are scenario-scoped', () => {
  const axis = { kind: 'ELAPSED_SECONDS', unit: 's', sampleCount: 3, start: 0, end: 600 } as const
  it('a scenario change releases the active results, their clocks and overlays', () => {
    activateScenario(scenario('A'))
    useResultsStore.getState().setActiveVentilation('aaaaaaaaaaaaaaaa', axis)
    useResultsStore.getState().setActiveOperations('bbbbbbbbbbbbbbbb', axis)
    useResultsStore.getState().setOperationsTime(300)
    useResultsStore.getState().playOperations()
    useResultsStore.getState().setVentilationRange({ min: 0, max: 5 })
    activateScenario(scenario('B'))
    const s = useResultsStore.getState()
    expect(s.activeVentilationResultId).toBeNull()
    expect(s.activeOperationsResultId).toBeNull()
    expect(s.operationsTime).toBe(0)
    expect(s.operationsPlaying).toBe(false)
    expect(s.ventilationRange).toBeNull()
    expect(s.ventilationOverlay).toBeNull()
  })

  it('a same-id scenario revision releases them too (results may be STALE now)', () => {
    activateScenario(scenario('A'))
    useResultsStore.getState().setActiveOperations('bbbbbbbbbbbbbbbb', axis)
    activateScenarioRevision(scenario('A'))
    expect(useResultsStore.getState().activeOperationsResultId).toBeNull()
  })

  it('the result clock is independent of the MineTimeline day cursor', () => {
    activateScenario(scenario('A'))
    useTimelineStore.getState().setRange(0, 900)
    useTimelineStore.getState().setCurrentDay(400)
    useResultsStore.getState().setActiveOperations('bbbbbbbbbbbbbbbb', axis)
    useResultsStore.getState().setOperationsTime(250)
    expect(useTimelineStore.getState().currentDay).toBe(400)
    useTimelineStore.getState().setCurrentDay(10)
    expect(useResultsStore.getState().operationsTime).toBe(250)
  })
})

describe('scenario identity boundary', () => {
  it('drops every derived product when the active scenario changes', () => {
    const epochA = activateScenario(scenario('A'))
    state().setScene(scene('A', 'a'), epochA)
    expect(state().scene).not.toBeNull()

    activateScenario(scenario('B'))
    expect(state().scene).toBeNull()
  })

  it('preserves nothing merely because the new scenario has the same orebody type', () => {
    const epochA = activateScenario(scenario('A', 'TABULAR'))
    state().setScene(scene('A', 'a'), epochA)
    activateScenario(scenario('B', 'TABULAR'))
    expect(state().scene).toBeNull()
  })

  it('clears slice, 4D day cursor, selection and walkthrough snapshot in one transition', () => {
    activateScenario(scenario('A'))
    useSliceStore.setState({ slice: { field: 'grade' } as never, index: 7, axis: 'x' })
    useTimelineStore.getState().setRange(0, 900)
    useTimelineStore.getState().setCurrentDay(400)
    useTimelineStore.getState().play()
    useViewerStore.setState({
      selectedObjectId: 'A:stope-3',
      walkthroughContext: 'TIMELINE_SNAPSHOT',
      walkthroughSnapshotDay: 400,
      walkthroughSnapshotIdentity: 'A-identity',
    })

    activateScenario(scenario('B'))

    expect(useSliceStore.getState().slice).toBeNull()
    expect(useSliceStore.getState().index).toBe(0)
    expect(useSliceStore.getState().axis).toBe('z')
    expect(useTimelineStore.getState().currentDay).toBe(0)
    expect(useTimelineStore.getState().endDay).toBe(0)
    expect(useTimelineStore.getState().playing).toBe(false)
    expect(useViewerStore.getState().selectedObjectId).toBeNull()
    expect(useViewerStore.getState().walkthroughContext).toBeNull()
    expect(useViewerStore.getState().walkthroughSnapshotDay).toBeNull()
    expect(useViewerStore.getState().walkthroughSnapshotIdentity).toBeNull()
  })

  it('keeps derived state when the SAME scenario is re-selected', () => {
    const epochA = activateScenario(scenario('A'))
    state().setScene(scene('A', 'a'), epochA)
    const again = activateScenario(scenario('A'))
    expect(again).toBe(epochA)
    expect(state().scene?.scenarioId).toBe('A')
  })

  it('clears in-flight job ids so a scenario-A job stops being polled', () => {
    const epochA = activateScenario(scenario('A'))
    state().setJob('decline', 'job-a', epochA)
    state().setJob('smooth', 'job-a2', epochA)
    expect(state().jobs.decline).toBe('job-a')

    activateScenario(scenario('B'))
    expect(state().jobs).toEqual({
      decline: null,
      smooth: null,
      tunnel: null,
      developmentMesh: null,
      layout: null,
    })
  })
})

describe('asynchronous cross-contamination (the actual bug)', () => {
  it('a scenario-A job resolving after B loaded cannot restore the A manifest', () => {
    // --- scenario A: world + a full derived chain
    const epochA = activateScenario(scenario('A'))
    state().setScene(scene('A', 'a'), epochA)

    // --- a decline job STARTS under A and captures A's epoch
    const startedEpoch = scenarioEpoch()
    expect(startedEpoch).toBe(epochA)

    // --- the user switches to B and generates its (empty) world
    const epochB = activateScenario(scenario('B'))
    const emptyB = {
      ...scene('B', 'b'),
      accessTargets: null,
      decline: null,
      smoothedDecline: null,
      tunnelMesh: null,
      levels: null,
      network: null,
      stopes: null,
      timeline: null,
      communication: null,
      sensors: null,
    } as unknown as WorldScene
    state().setScene(emptyB, epochB)

    // --- ONLY NOW does A's job resolve, exactly as the panel would apply it
    state().applyScene(startedEpoch, (current) => ({
      ...current,
      decline: { tag: 'a' } as never,
      smoothedDecline: null,
      tunnelMesh: null,
    }))

    const after = state().scene
    expect(after?.scenarioId).toBe('B')
    for (const key of DERIVED) expect(after?.[key]).toBeNull()
  })

  it('a late scenario-A scene manifest cannot replace scenario B', () => {
    const epochA = activateScenario(scenario('A'))
    const epochB = activateScenario(scenario('B'))
    state().setScene(scene('B', 'b'), epochB)

    // GET /scenes/A resolves after the switch
    state().setScene(scene('A', 'a'), epochA)
    expect(state().scene?.scenarioId).toBe('B')

    // ...and so does its WORLD_NOT_GENERATED branch, which nulls the scene
    state().setScene(null, epochA)
    expect(state().scene?.scenarioId).toBe('B')
  })

  it('a late scenario-A job id cannot start polling under scenario B', () => {
    const epochA = activateScenario(scenario('A'))
    activateScenario(scenario('B'))
    state().setJob('decline', 'job-a', epochA)
    expect(state().jobs.decline).toBeNull()
  })

  it('applyScene reads the CURRENT store scene, never a captured copy', () => {
    const epochA = activateScenario(scenario('A'))
    state().setScene(scene('A', 'first'), epochA)
    const captured = state().scene // the stale render closure
    state().setScene({ ...scene('A', 'second'), network: null }, epochA)

    // a producer that started before the second write must not resurrect
    // the network it saw in `captured`
    state().applyScene(epochA, (current) => ({ ...current, stopes: { tag: 'new' } as never }))

    expect(captured?.network).not.toBeNull()
    expect(state().scene?.network).toBeNull()
    expect(state().scene?.stopes).toEqual({ tag: 'new' })
  })

  it('applyScene is a no-op when there is no scene at all', () => {
    const epochA = activateScenario(scenario('A'))
    state().applyScene(epochA, (current) => ({ ...current, decline: { tag: 'x' } as never }))
    expect(state().scene).toBeNull()
  })
})

describe('scenario REVISION boundary (a PUT under the same id — review blocker 2)', () => {
  it('replacing the document of the SAME scenario id advances the epoch and clears derived state', () => {
    const epochA = activateScenario(scenario('A'))
    state().setScene(scene('A', 'a'), epochA)
    state().setJob('layout', 'job-a', epochA)
    useSliceStore.getState().setAxis('x')
    useTimelineStore.getState().setRange(0, 100)
    useTimelineStore.getState().setCurrentDay(12)
    useViewerStore.setState({ selectedObjectId: 'x' } as never)
    expect(useTimelineStore.getState().currentDay).toBe(12)

    const revised = { ...scenario('A'), name: 'A (Cut & Fill)' }
    const epochA2 = activateScenarioRevision(revised)

    expect(epochA2).toBe(epochA + 1)
    expect(state().scenario?.name).toBe('A (Cut & Fill)')
    expect(state().scene).toBeNull()
    expect(state().jobs).toEqual({
      decline: null,
      smooth: null,
      tunnel: null,
      developmentMesh: null,
      layout: null,
    })
    expect(useTimelineStore.getState().currentDay).toBe(0)
    expect(useViewerStore.getState().selectedObjectId).toBeNull()
    expect(useSliceStore.getState().axis).toBe(useSliceStore.getInitialState().axis)
  })

  it('an old-revision asynchronous result is dropped after the same-id replacement', () => {
    // a Longhole design job starts under revision 1 of scenario A
    const epochA = activateScenario(scenario('A'))
    state().setScene(scene('A', 'a'), epochA)
    const startedEpoch = scenarioEpoch()

    // the user changes the mining method: PUT (backend clears every derived
    // artifact) → revision 2 → world regenerated → empty scene loaded
    const epochA2 = activateScenarioRevision({ ...scenario('A'), name: 'A2' })
    const emptyA2 = {
      ...scene('A', 'a2'),
      ...Object.fromEntries(DERIVED.map((k) => [k, null])),
    }
    state().setScene(emptyA2, epochA2)

    // ONLY NOW does the revision-1 job resolve — its write must be dropped
    state().applyScene(startedEpoch, (current) => ({ ...current, stopes: { tag: 'a' } as never }))
    state().setJob('layout', 'job-stale', startedEpoch)
    state().setScene(scene('A', 'stale'), startedEpoch)

    expect(state().epoch).toBe(epochA2)
    for (const key of DERIVED) expect(state().scene?.[key]).toBeNull()
    expect(state().jobs.layout).toBeNull()
    // a revision-2 write is accepted
    state().applyScene(epochA2, (current) => ({ ...current, stopes: { tag: 'a2' } as never }))
    expect((state().scene?.stopes as unknown as { tag: string }).tag).toBe('a2')
  })

  it('plain re-selection of the same id is still a refresh, not a revision', () => {
    const epochA = activateScenario(scenario('A'))
    state().setScene(scene('A', 'a'), epochA)
    expect(activateScenario(scenario('A'))).toBe(epochA)
    expect(state().scene).not.toBeNull()
  })

  it('every accepted scene write and every scenario transition advances the scene revision (round 3 B2)', () => {
    const r = () => state().sceneRevision
    const r0 = r()
    const epochA = activateScenario(scenario('A'))
    expect(r()).toBe(r0 + 1)
    state().setScene(scene('A', 'a'), epochA)
    expect(r()).toBe(r0 + 2)
    state().applyScene(epochA, (s) => ({ ...s }))
    expect(r()).toBe(r0 + 3)
    // an updater that keeps the scene object moved nothing
    state().applyScene(epochA, (s) => s)
    expect(r()).toBe(r0 + 3)
    // a write under a stale epoch is dropped and moves nothing
    state().setScene(scene('A', 'stale'), epochA - 1)
    state().applyScene(epochA - 1, (s) => ({ ...s }))
    expect(r()).toBe(r0 + 3)
    // a same-id document replacement (scenario PUT) is a new revision too
    activateScenarioRevision(scenario('A'))
    expect(r()).toBe(r0 + 4)
    // re-selecting the same id is a refresh of the document, not of the scene
    activateScenario(scenario('A'))
    expect(r()).toBe(r0 + 4)
  })
})

describe('demo identity (hardening PR-2 H4)', () => {
  const entry = {
    id: 'demo-a',
    title: 'Demo A',
    description: '',
    orebodyType: 'TABULAR',
    miningMethod: 'LONGHOLE_OPEN_STOPING',
    preset: 'BASELINE',
    seed: 1,
    faultCount: 1,
    stages: ['WORLD'],
    labels: ['DEMO', 'SYNTHETIC'],
    available: true,
    reason: null,
  }
  it('is part of the scenario transition and never survives the next one', () => {
    activateScenario(scenario('demo-a'), entry)
    expect(state().demo).toEqual(entry)
    // re-selecting the same id refreshes the document and keeps the demo fact
    activateScenario(scenario('demo-a'), entry)
    expect(state().demo).toEqual(entry)
    // a saved scenario clears it; so does a revision replace and a null scenario
    activateScenario(scenario('B'))
    expect(state().demo).toBeNull()
    activateScenario(scenario('demo-a'), entry)
    activateScenarioRevision(scenario('demo-a'))
    expect(state().demo).toBeNull()
    activateScenario(scenario('demo-a'), entry)
    activateScenario(null)
    expect(state().demo).toBeNull()
  })
})
