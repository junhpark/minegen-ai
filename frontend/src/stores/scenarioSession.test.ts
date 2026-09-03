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
import { activateScenario, scenarioEpoch } from './scenarioSession'
import { useScenarioStore } from './scenarioStore'
import { useSliceStore } from './sliceStore'
import { useTimelineStore } from './timelineStore'
import { useViewerStore } from './viewerStore'

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
    expect(state().jobs).toEqual({ decline: null, smooth: null, tunnel: null, layout: null })
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
