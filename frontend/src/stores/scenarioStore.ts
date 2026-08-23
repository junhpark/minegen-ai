import { create } from 'zustand'
import type { Scenario } from '@/types/api'
import type { WorldScene } from '@/types/scene'

export interface ScenarioState {
  scenario: Scenario | null
  scene: WorldScene | null
  setScenario: (scenario: Scenario | null) => void
  setScene: (scene: WorldScene | null) => void
}

export const useScenarioStore = create<ScenarioState>()((set) => ({
  scenario: null,
  scene: null,
  setScenario: (scenario) =>
    set((s) => ({ scenario, scene: s.scene?.scenarioId === scenario?.id ? s.scene : null })),
  setScene: (scene) => set({ scene }),
}))
