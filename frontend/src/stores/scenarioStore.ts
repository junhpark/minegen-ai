import { create } from 'zustand'
import type { Scenario } from '@/types/api'
import type { WorldScene } from '@/types/scene'

/** Asynchronous design jobs owned by the ACTIVE scenario (Phase 17.1 §1).
 * They live in the store, not in component state, so a scenario change
 * cancels them structurally instead of relying on a component unmount. */
export type DesignJobKind = 'decline' | 'smooth' | 'tunnel'

const NO_JOBS: Record<DesignJobKind, string | null> = {
  decline: null,
  smooth: null,
  tunnel: null,
}

export interface ScenarioState {
  scenario: Scenario | null
  scene: WorldScene | null
  /**
   * Scenario-identity token (Phase 17.1 §1). It increments on every change
   * of the active scenario. Every asynchronous producer captures the epoch
   * it started under and hands it back on write; a write whose epoch is
   * stale is DROPPED, so a result computed for scenario A can never
   * populate scenario B.
   */
  epoch: number
  jobs: Record<DesignJobKind, string | null>
  /** Switch the active scenario and return the NEW epoch. Clears the scene
   * manifest, every derived product and all in-flight job ids in one set(). */
  setScenario: (scenario: Scenario | null) => number
  setScene: (scene: WorldScene | null, epoch: number) => void
  /**
   * The ONLY way to write a derived product. `update` receives the scene as
   * it is IN THE STORE, never a value captured by a render closure, which is
   * what previously let a late scenario-A result restore a whole stale
   * manifest over scenario B.
   */
  applyScene: (epoch: number, update: (scene: WorldScene) => WorldScene) => void
  setJob: (kind: DesignJobKind, jobId: string | null, epoch: number) => void
}

export const useScenarioStore = create<ScenarioState>()((set, get) => ({
  scenario: null,
  scene: null,
  epoch: 0,
  jobs: { ...NO_JOBS },

  setScenario: (scenario) => {
    const prev = get()
    // re-selecting the SAME scenario is not an identity change: refresh the
    // document and keep the derived state that belongs to it
    if (scenario !== null && prev.scenario?.id === scenario.id) {
      set({ scenario })
      return prev.epoch
    }
    const epoch = prev.epoch + 1
    set({ scenario, scene: null, epoch, jobs: { ...NO_JOBS } })
    return epoch
  },

  setScene: (scene, epoch) => set((s) => (epoch === s.epoch ? { scene } : {})),

  applyScene: (epoch, update) =>
    set((s) => (epoch === s.epoch && s.scene ? { scene: update(s.scene) } : {})),

  setJob: (kind, jobId, epoch) =>
    set((s) => (epoch === s.epoch ? { jobs: { ...s.jobs, [kind]: jobId } } : {})),
}))
