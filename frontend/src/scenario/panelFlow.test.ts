/**
 * Draft-state semantics of the scenario panel (Phase 17 acceptance §1.3),
 * exercised as pure state transitions so the contract is pinned
 * independently of rendering: realize seeds the draft, explicit edits stay,
 * Create submits the edited draft (never a fresh realization), and any
 * change to preset/seed/fault count invalidates the draft.
 */
import { describe, expect, it, vi } from 'vitest'
import type { ScenarioCreate } from '@/types/api'
import { editOrebody, editWarpedVein, realizeRequest } from './builder'

function backendRealization(seed: number): ScenarioCreate {
  return {
    name: 'Random Tabular mine',
    seed,
    orebody: {
      orebodyType: 'TABULAR',
      center: { x: 10, y: 20, z: -60 },
      strikeDeg: 30,
      dipDeg: 65,
      length: 400,
      height: 250,
      thickness: 12,
      meanGrade: 4,
      gradeVariability: 0.3,
      gradeCorrelationLengthXy: 80,
      gradeCorrelationLengthZ: 40,
      density: 2.8,
    },
    geology: { rockQuality: {}, faults: [] },
  } as unknown as ScenarioCreate
}

/** minimal model of the panel's realize/draft/create wiring */
function makePanel(realizeFn: (seed: number) => ScenarioCreate) {
  let seed = 42
  let draft: ScenarioCreate | null = null
  return {
    get draft() {
      return draft
    },
    randomize() {
      draft = realizeFn(seed)
    },
    edit(patch: Parameters<typeof editOrebody>[1]) {
      if (draft) draft = editOrebody(draft, patch)
    },
    setSeed(next: number) {
      seed = next
      draft = null // invalidate
    },
    create() {
      return draft ?? realizeFn(seed)
    },
  }
}

describe('scenario panel draft flow', () => {
  it('realization initializes the editable draft', () => {
    const realize = vi.fn(backendRealization)
    const panel = makePanel(realize)
    expect(panel.draft).toBeNull()
    panel.randomize()
    expect(realize).toHaveBeenCalledTimes(1)
    expect(panel.draft?.orebody.thickness).toBe(12)
  })

  it('user edits survive Create — no re-realization overwrite', () => {
    const realize = vi.fn(backendRealization)
    const panel = makePanel(realize)
    panel.randomize()
    panel.edit({ thickness: 27, dipDeg: 51 })
    const payload = panel.create()
    expect(payload.orebody.thickness).toBe(27)
    expect(payload.orebody.dipDeg).toBe(51)
    expect(realize).toHaveBeenCalledTimes(1) // create did NOT re-realize
  })

  it('changing seed invalidates the draft; Create then realizes fresh', () => {
    const realize = vi.fn(backendRealization)
    const panel = makePanel(realize)
    panel.randomize()
    panel.edit({ thickness: 99 })
    panel.setSeed(777)
    expect(panel.draft).toBeNull() // stale preview cannot be shown or sent
    const payload = panel.create()
    expect(payload.orebody.thickness).toBe(12)
    expect(payload.seed).toBe(777)
    expect(realize).toHaveBeenCalledTimes(2)
  })

  it('the realize request mirrors the current inputs', () => {
    expect(realizeRequest({ preset: 'RANDOM_TABULAR', seed: 777, faultCount: 4 })).toEqual({
      preset: 'RANDOM_TABULAR',
      seed: 777,
      faultCount: 4,
    })
  })
})

function backendVeinRealization(seed: number): ScenarioCreate {
  const base = backendRealization(seed)
  return {
    ...base,
    orebody: {
      ...base.orebody,
      orebodyType: 'WARPED_VEIN',
      warpedVein: {
        shapeModelVersion: 1,
        warpAmplitude: 20,
        centerlineDeviation: 40,
        outlineIrregularity: 0.25,
        thicknessVariability: 0.4,
        pinchFloorRatio: 0.5,
        edgeTaper: 0.5,
        geometryResolution: 5,
        warpModes: [{ ku: 1, kv: 0, phaseU: 0, phaseV: 0, weight: 1 }],
        deviationModes: [{ ku: 0, kv: 1, phaseU: 0, phaseV: 0, weight: 1 }],
        outlineModes: [{ ku: 1, kv: 0, phaseU: 0, phaseV: 0, weight: 1 }],
        thicknessModes: [{ ku: 1, kv: 1, phaseU: 0, phaseV: 0, weight: 1 }],
      },
    },
  }
}

describe('scenario panel draft flow — Phase 19 warped vein', () => {
  it('realization creates an editable WARPED_VEIN draft whose edits reach Create', () => {
    const realize = vi.fn(backendVeinRealization)
    const panel = makePanel(realize)
    panel.randomize()
    expect(panel.draft?.orebody.orebodyType).toBe('WARPED_VEIN')
    expect(panel.draft?.orebody.warpedVein?.shapeModelVersion).toBe(1)
    const edited = editWarpedVein(panel.draft!, { warpAmplitude: 33 })
    expect(edited.orebody.warpedVein?.warpAmplitude).toBe(33)
    expect(edited.orebody.warpedVein?.warpModes).toEqual(
      backendVeinRealization(42).orebody.warpedVein!.warpModes,
    )
    expect(realize).toHaveBeenCalledTimes(1)
  })

  it('changing the seed discards the realized morphology instead of re-running it silently', () => {
    const realize = vi.fn(backendVeinRealization)
    const panel = makePanel(realize)
    panel.randomize()
    panel.setSeed(8)
    expect(panel.draft).toBeNull()
    expect(panel.create().seed).toBe(8)
    expect(realize).toHaveBeenCalledTimes(2)
  })
})
