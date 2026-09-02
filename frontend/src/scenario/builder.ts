/**
 * Phase 17 — pure scenario-builder model (rule 124).
 *
 * The backend owns stochastic realization and ALL orebody/fault
 * engineering geometry. This module only assembles realize REQUESTS and
 * applies explicit scalar edits the user typed into the realized draft;
 * it never draws random numbers (no Math.random anywhere in the client)
 * and never derives geometry. The draft the user finally submits is the
 * authoritative persisted scenario.
 */
import type {
  FaultConfig,
  GeologyConfig,
  OrebodyConfig,
  Point3D,
  RockQualityConfig,
  Scenario,
  ScenarioCreate,
  ScenarioPreset,
  ScenarioRealizeRequest,
} from '@/types/api'

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

/** Orebody geometries with a real backend implementation. Reserved enum
 * members (PIPE, LENS) are deliberately NOT offered. */
export const EDITABLE_OREBODY_TYPES = ['TABULAR', 'ELLIPSOID'] as const
export type EditableOrebodyType = (typeof EDITABLE_OREBODY_TYPES)[number]

export const MAX_FAULTS = 6

/** Immutable scalar edit of the realized draft. Values come from user
 * input only; non-finite input is ignored so a half-typed field can never
 * corrupt the draft. */
export function editOrebody(
  draft: ScenarioCreate,
  patch: Partial<Omit<OrebodyConfig, 'center'>> & { center?: Partial<Point3D> },
): ScenarioCreate {
  const { center, ...scalars } = patch
  const next: OrebodyConfig = { ...draft.orebody, ...clean(scalars) }
  if (center) next.center = { ...draft.orebody.center, ...clean(center) }
  return { ...draft, orebody: next }
}

export function editRockQuality(
  draft: ScenarioCreate,
  patch: Partial<RockQualityConfig>,
): ScenarioCreate {
  const geology: GeologyConfig = {
    ...draft.geology,
    rockQuality: { ...draft.geology.rockQuality, ...clean(patch) },
  }
  return { ...draft, geology }
}

export function editFault(
  draft: ScenarioCreate,
  index: number,
  patch: Partial<Omit<FaultConfig, 'origin'>> & { origin?: Partial<Point3D> },
): ScenarioCreate {
  const existing = draft.geology.faults[index]
  if (!existing) return draft
  const { origin, ...scalars } = patch
  const next: FaultConfig = { ...existing, ...clean(scalars) }
  if (origin) next.origin = { ...existing.origin, ...clean(origin) }
  const faults = draft.geology.faults.map((f, i) => (i === index ? next : f))
  return { ...draft, geology: { ...draft.geology, faults } }
}

/** Append a fault by COPYING the last one (or a neutral template when the
 * list is empty) — no random draw, no geometry derivation. */
export function addFault(draft: ScenarioCreate): ScenarioCreate {
  if (draft.geology.faults.length >= MAX_FAULTS) return draft
  const last = draft.geology.faults[draft.geology.faults.length - 1]
  const template: FaultConfig = last
    ? { ...last, origin: { ...last.origin } }
    : {
        origin: { x: 0, y: 0, z: 0 },
        strikeDeg: 90,
        dipDeg: 70,
        coreHalfWidth: 2.5,
        influenceHalfWidth: 20,
        corePenalty: 50,
        damageZonePenalty: 10,
      }
  return {
    ...draft,
    geology: { ...draft.geology, faults: [...draft.geology.faults, template] },
  }
}

export function removeFault(draft: ScenarioCreate, index: number): ScenarioCreate {
  const faults = draft.geology.faults.filter((_, i) => i !== index)
  return { ...draft, geology: { ...draft.geology, faults } }
}

/** Drop undefined and non-finite numbers so partially typed inputs never
 * reach the draft. */
function clean<T extends object>(patch: T): Partial<T> {
  const out: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(patch)) {
    if (v === undefined) continue
    if (typeof v === 'number' && !Number.isFinite(v)) continue
    out[k] = v
  }
  return out as Partial<T>
}
