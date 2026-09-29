import type { Scenario } from '@/types/api'
import { useResultsStore } from './resultsStore'
import { useScenarioStore } from './scenarioStore'
import { useSliceStore } from './sliceStore'
import { useTimelineStore } from './timelineStore'
import { useViewerStore } from './viewerStore'

/**
 * Scenario identity boundary (Phase 17.1 §1).
 *
 * Changing the active scenario is ONE transition, not per-component
 * cleanup: it clears the SceneManifest and every derived product, the
 * slice, the 4D day cursor, the selection and the walkthrough snapshot,
 * and it invalidates every in-flight asynchronous producer by bumping the
 * scenario epoch. Nothing derived is preserved because the new scenario
 * happens to share an orebody type — identity, not shape, is the boundary.
 *
 * The returned epoch must be carried by every asynchronous write made for
 * this scenario (`setScene` / `applyScene` / `setJob`), which is what makes
 * "a result from scenario A can never populate scenario B" structural
 * rather than a convention observed at each call site.
 *
 * This module — never a store — owns the cross-store transition, so the
 * stores stay free of import cycles.
 */
export function activateScenario(scenario: Scenario | null): number {
  const epoch = useScenarioStore.getState().setScenario(scenario)
  useSliceStore.getState().reset()
  useTimelineStore.getState().reset()
  useViewerStore.getState().resetScenarioScopedState()
  // Phase 23C: active simulation results, their clocks and overlays belong to
  // one scenario's results/ folder and never survive a scenario change
  useResultsStore.getState().reset()
  return epoch
}

/**
 * Scenario REVISION boundary (Phase 21B/C review blocker 2). A scenario PUT
 * keeps the id but replaces the document, and the backend clears every
 * derived artifact on it (rule 40): for the frontend that is a new revision
 * of the same scenario, never a same-id refresh. This transition therefore
 * ALWAYS advances the epoch and clears the scene manifest, the in-flight
 * job ids, the slice, the 4D day cursor and the scenario-scoped viewer state
 * — exactly what `activateScenario` does for a different id — so an
 * asynchronous result started under the previous revision is dropped by
 * `setScene` / `applyScene` / `setJob` instead of populating the new one.
 */
export function activateScenarioRevision(scenario: Scenario): number {
  const epoch = useScenarioStore.getState().replaceScenarioDocument(scenario)
  useSliceStore.getState().reset()
  useTimelineStore.getState().reset()
  useViewerStore.getState().resetScenarioScopedState()
  useResultsStore.getState().reset()
  return epoch
}

/** Current scenario epoch, for producers that start outside a transition. */
export function scenarioEpoch(): number {
  return useScenarioStore.getState().epoch
}
