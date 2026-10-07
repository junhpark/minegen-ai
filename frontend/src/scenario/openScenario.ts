import { api, ApiError } from '@/api/client'
import { activateScenario } from '@/stores/scenarioSession'
import { useScenarioStore } from '@/stores/scenarioStore'

/**
 * Load the scene manifest of `id` under the scenario epoch captured BEFORE
 * the request: a manifest that arrives after the user moved on to another
 * scenario is dropped by the store. A world that is not generated yet is a
 * normal empty scene, never an error.
 */
export async function loadScene(id: string, epoch: number): Promise<void> {
  const setScene = useScenarioStore.getState().setScene
  try {
    const sc = await api.getScene(id)
    setScene(sc, epoch)
  } catch (e) {
    if (e instanceof ApiError && e.code === 'WORLD_NOT_GENERATED') {
      setScene(null, epoch)
      return
    }
    throw e
  }
}

/** Open a saved scenario: ONE scenario-identity transition, then its scene.
 * Shared by the Setup stage and the File › Open menu (one implementation). */
export async function openScenario(id: string): Promise<void> {
  const s = await api.getScenario(id)
  const epoch = activateScenario(s)
  await loadScene(id, epoch)
}
