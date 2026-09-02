/**
 * Phase 17 — pure scenario-builder model (rule 124: the frontend never
 * computes geometry; it only assembles the realize request and displays
 * the backend-realized ScenarioCreate verbatim).
 */
import type { Scenario, ScenarioCreate, ScenarioPreset, ScenarioRealizeRequest } from '@/types/api'

export interface BuilderState {
  preset: ScenarioPreset
  seed: number
  faultCount: number
}

export const DEFAULT_BUILDER: BuilderState = { preset: 'BASELINE', seed: 42, faultCount: 2 }

/** BASELINE has exactly one fixed fault; the count control is meaningful
 * for the RANDOM_* presets only. */
export function faultCountEnabled(preset: ScenarioPreset): boolean {
  return preset !== 'BASELINE'
}

export function realizeRequest(state: BuilderState): ScenarioRealizeRequest {
  return {
    preset: state.preset,
    seed: state.seed,
    faultCount: faultCountEnabled(state.preset) ? state.faultCount : null,
  }
}

/** Compact human summary of a realized scenario for the preview card. */
export function realizedSummary(sc: ScenarioCreate): string[] {
  const ob = sc.orebody
  return [
    `${ob.orebodyType} orebody · ${ob.length.toFixed(0)}×${ob.height.toFixed(0)}×${ob.thickness.toFixed(1)} m`,
    `center E ${ob.center.x.toFixed(0)} / N ${ob.center.y.toFixed(0)} / RL ${ob.center.z.toFixed(0)} m`,
    `strike ${ob.strikeDeg.toFixed(0)}° · dip ${ob.dipDeg.toFixed(0)}° · grade ${ob.meanGrade.toFixed(1)} g/t`,
    `faults ${sc.geology.faults.length}`,
  ]
}

/** Phase 17 gate (mirror of the backend typed failure): the legacy design
 * pipeline supports TABULAR only; other types are view/world-only until
 * Phase 18. */
export function designSupported(scenario: Pick<Scenario, 'orebody'> | null): boolean {
  return scenario === null || scenario.orebody.orebodyType === 'TABULAR'
}

export const DESIGN_UNSUPPORTED_NOTICE =
  'This orebody type is not supported by the legacy decline/access layout yet. ' +
  'World generation and visualization work; generalized layout arrives in Phase 18.'
