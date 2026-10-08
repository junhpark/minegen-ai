import { api } from '@/api/client'
import { loadScene } from '@/scenario/openScenario'
import { activateScenario } from '@/stores/scenarioSession'
import { useTimelineStore } from '@/stores/timelineStore'
import { useViewerStore } from '@/stores/viewerStore'
import type { DemoCatalogEntry, Scenario, ScenarioCreate } from '@/types/api'

/**
 * Hardening PR-2 H4 — baked demos.
 *
 * `openDemo` opens a demo IN PLACE: the ordinary scenario + scene reads of
 * its id (the backend resolves the baked directory read-only; no derived
 * artifact is copied, so every revision binding stays intact), ONE
 * scenario-identity transition that records the demo, 4D Loop on and the
 * Auto tour on. Nothing is generated and nothing is written.
 *
 * `cloneDemo` is "Clone to edit": the demo DOCUMENT becomes a new saved
 * scenario (POST /scenarios with a fresh id), whose world is regenerated from
 * the same seed (rule 119) — the clone is an ordinary editable mine and the
 * demo is untouched.
 */
export async function openDemo(entry: DemoCatalogEntry): Promise<void> {
  const s = await api.getScenario(entry.id)
  const epoch = activateScenario(s, entry)
  useTimelineStore.getState().setLoop(true)
  useViewerStore.getState().setDemoTour(true)
  await loadScene(entry.id, epoch)
}

/** the ScenarioCreate of a clone: the demo document without its identity */
export function cloneDraft(scenario: Scenario, name?: string): ScenarioCreate {
  const create: ScenarioCreate & Partial<Pick<Scenario, 'id' | 'schemaVersion'>> = {
    ...scenario,
  }
  delete create.id
  delete create.schemaVersion
  return { ...create, name: name ?? `${scenario.name} (copy)` }
}

export async function cloneDemo(entry: DemoCatalogEntry): Promise<Scenario> {
  const source = await api.getScenario(entry.id)
  const created = await api.createScenario(cloneDraft(source))
  const epoch = activateScenario(created, null)
  useViewerStore.getState().setDemoTour(false)
  await api.generateWorld(created.id)
  await loadScene(created.id, epoch)
  return created
}

export type TourPreset = 'ISO' | 'TOP' | 'FIT'

/** the Auto tour cycle over the View panel's camera presets */
export const TOUR_ORDER: readonly TourPreset[] = ['ISO', 'TOP', 'FIT']

export const TOUR_INTERVAL_MS = 7000

export function nextTourPreset(current: TourPreset): TourPreset {
  const i = TOUR_ORDER.indexOf(current)
  return TOUR_ORDER[(i + 1) % TOUR_ORDER.length] ?? 'ISO'
}
