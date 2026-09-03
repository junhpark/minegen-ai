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
  WarpedVeinConfig,
} from '@/types/api'
import type { OrebodyType } from '@/types/enums'

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

/** Human label of a realization preset. ELLIPSOID is presented as the
 * simple analytic geometric reference; the Phase 19 warped vein is the
 * irregular synthetic-morphology demonstration. */
export function presetLabel(preset: ScenarioPreset): string {
  switch (preset) {
    case 'BASELINE':
      return 'Baseline (fixed reference mine)'
    case 'RANDOM_TABULAR':
      return 'Randomized · tabular orebody'
    case 'RANDOM_ELLIPSOID':
      return 'Randomized · ellipsoid (geometric reference shape)'
    case 'RANDOM_WARPED_VEIN':
      return 'Randomized · irregular warped vein'
  }
}

/** Morphology one-liner for a WARPED_VEIN: warp / thickness variability /
 * pinch floor, echoed from the resolved backend controls. */
export function morphologySummary(vein: WarpedVeinConfig): string {
  return (
    `warp ±${vein.warpAmplitude.toFixed(0)} m · thickness ±${(vein.thicknessVariability * 100).toFixed(0)} % · ` +
    `pinch floor ${(vein.pinchFloorRatio * 100).toFixed(0)} %`
  )
}

/** Compact human summary of a realized scenario for the preview card. For
 * a WARPED_VEIN the dimensions are NOMINAL — the thickness is never
 * constant anywhere — so the wording says so. */
export function realizedSummary(sc: ScenarioCreate): string[] {
  const ob = sc.orebody
  const size = `${ob.length.toFixed(0)}×${ob.height.toFixed(0)}`
  if (ob.orebodyType === 'WARPED_VEIN' && ob.warpedVein) {
    return [
      `WARPED_VEIN orebody · nominal ${size} m · nominal thickness ${ob.thickness.toFixed(1)} m`,
      morphologySummary(ob.warpedVein),
      `center E ${ob.center.x.toFixed(0)} / N ${ob.center.y.toFixed(0)} / RL ${ob.center.z.toFixed(0)} m`,
      `strike ${ob.strikeDeg.toFixed(0)}° · dip ${ob.dipDeg.toFixed(0)}° · grade ${ob.meanGrade.toFixed(1)} g/t`,
      `faults ${sc.geology.faults.length}`,
    ]
  }
  return [
    `${ob.orebodyType} orebody · ${size}×${ob.thickness.toFixed(1)} m`,
    `center E ${ob.center.x.toFixed(0)} / N ${ob.center.y.toFixed(0)} / RL ${ob.center.z.toFixed(0)} m`,
    `strike ${ob.strikeDeg.toFixed(0)}° · dip ${ob.dipDeg.toFixed(0)}° · grade ${ob.meanGrade.toFixed(1)} g/t`,
    `faults ${sc.geology.faults.length}`,
  ]
}

/** Legacy-layout gate (mirror of the backend typed failure
 * UNSUPPORTED_OREBODY_FOR_LEGACY_LAYOUT): the Phase 03–18 design pipeline
 * supports TABULAR only; ELLIPSOID and WARPED_VEIN are world/visualization
 * only until Phase 20 (rule 140). */
export function designSupported(scenario: Pick<Scenario, 'orebody'> | null): boolean {
  return scenario === null || scenario.orebody.orebodyType === 'TABULAR'
}

export const DESIGN_UNSUPPORTED_NOTICE =
  'This orebody type is not supported by the legacy decline/access layout. ' +
  'World generation and visualization work; generalized layout arrives in ' +
  'Phase 20 — Parametric Layout Family Search.'

/** Orebody geometries a user may switch a draft INTO by hand. Reserved enum
 * members (PIPE, LENS) are deliberately NOT offered, and neither is
 * WARPED_VEIN: its morphology is backend-realized coefficient state the
 * client must never fabricate (rule 124/136) — it is reachable only through
 * the RANDOM_WARPED_VEIN preset. */
export const EDITABLE_OREBODY_TYPES = ['TABULAR', 'ELLIPSOID'] as const
export type EditableOrebodyType = (typeof EDITABLE_OREBODY_TYPES)[number]

/** Type options offered for a draft: the analytic ones always, plus
 * WARPED_VEIN only while the draft still carries its resolved morphology. */
export function orebodyTypeOptions(draft: ScenarioCreate): readonly OrebodyType[] {
  return draft.orebody.orebodyType === 'WARPED_VEIN' && draft.orebody.warpedVein
    ? ['WARPED_VEIN', ...EDITABLE_OREBODY_TYPES]
    : EDITABLE_OREBODY_TYPES
}

/** Switch the draft's orebody type. Leaving WARPED_VEIN discards its
 * resolved morphology (the backend forbids a dormant one on an analytic
 * type); entering WARPED_VEIN is only possible when the draft already
 * carries one — never fabricated here. */
export function editOrebodyType(draft: ScenarioCreate, type: OrebodyType): ScenarioCreate {
  if (type === 'WARPED_VEIN') {
    return draft.orebody.warpedVein
      ? { ...draft, orebody: { ...draft.orebody, orebodyType: type } }
      : draft
  }
  if (!EDITABLE_OREBODY_TYPES.includes(type as EditableOrebodyType)) return draft
  return { ...draft, orebody: { ...draft.orebody, orebodyType: type, warpedVein: null } }
}

/** Scalar edit of the resolved WARPED_VEIN morphology controls. The mode
 * coefficients are never touched here; only the explicit user-facing
 * controls the backend interprets. */
export function editWarpedVein(
  draft: ScenarioCreate,
  patch: Partial<
    Pick<
      WarpedVeinConfig,
      | 'warpAmplitude'
      | 'centerlineDeviation'
      | 'outlineIrregularity'
      | 'thicknessVariability'
      | 'pinchFloorRatio'
      | 'edgeTaper'
      | 'geometryResolution'
    >
  >,
): ScenarioCreate {
  const vein = draft.orebody.warpedVein
  if (draft.orebody.orebodyType !== 'WARPED_VEIN' || !vein) return draft
  return { ...draft, orebody: { ...draft.orebody, warpedVein: { ...vein, ...clean(patch) } } }
}

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
