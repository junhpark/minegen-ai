import { describe, expect, it } from 'vitest'
import { WALKTHROUGH_INTERACTION_CONFIG } from './interactionConfig'
import { computeFocus, createInspectTrigger, raySphereDistance } from './interactionRay'

const CFG = WALKTHROUGH_INTERACTION_CONFIG
const ORIGIN: [number, number, number] = [0, 0, 0]
const FORWARD: [number, number, number] = [0, 0, -1] // camera looks down -Z
const at = (
  id: string,
  z: number,
  x = 0,
): { id: string; positionThree: [number, number, number] } => ({
  id,
  positionThree: [x, 0, -z],
})

describe('center-ray targeting (rule 107, §30)', () => {
  it('ray/sphere math hits on-axis targets at the near surface', () => {
    const t = raySphereDistance(ORIGIN, FORWARD, [0, 0, -6], CFG.hitProxyRadiusM)
    expect(t).toBeCloseTo(6 - CFG.hitProxyRadiusM, 9)
    expect(raySphereDistance(ORIGIN, FORWARD, [5, 0, -6], CFG.hitProxyRadiusM)).toBeNull()
    expect(raySphereDistance(ORIGIN, FORWARD, [0, 0, 6], CFG.hitProxyRadiusM)).toBeNull() // behind
  })

  it('selects the nearest eligible target with deterministic output', () => {
    const targets = [at('FAR', 8), at('NEAR', 4), at('OFFAXIS', 4, 3)]
    expect(computeFocus(ORIGIN, FORWARD, targets, null, CFG)).toBe('NEAR')
    expect(computeFocus(ORIGIN, FORWARD, targets, null, CFG)).toBe('NEAR') // same input, same result
  })

  it('rejects targets beyond the max interaction distance', () => {
    expect(computeFocus(ORIGIN, FORWARD, [at('FAR', 12)], null, CFG)).toBeNull()
    expect(computeFocus(ORIGIN, FORWARD, [at('EDGE', 9.9)], null, CFG)).not.toBeNull()
  })

  it('never focuses through the tunnel wall (§21 occlusion order)', () => {
    // wall at 5 m, sensor 6 m Euclidean behind it: must NOT focus
    expect(computeFocus(ORIGIN, FORWARD, [at('BEHIND', 6)], 5, CFG)).toBeNull()
    // asset clearly before the wall: focusable
    expect(computeFocus(ORIGIN, FORWARD, [at('BEFORE', 3)], 5, CFG)).toBe('BEFORE')
    // asset essentially AT the wall (within epsilon): rejected
    const tAtWall = 5 - CFG.hitProxyRadiusM
    expect(
      computeFocus(ORIGIN, FORWARD, [at('ATWALL', 5)], tAtWall + CFG.occlusionEpsilonM / 2, CFG),
    ).toBeNull()
  })

  it('breaks exact ties lexicographically by id', () => {
    const tie = [at('B', 5), at('A', 5)]
    expect(computeFocus(ORIGIN, FORWARD, tie, null, CFG)).toBe('A')
    expect(computeFocus(ORIGIN, FORWARD, [...tie].reverse(), null, CFG)).toBe('A')
  })

  it('E trigger is edge-triggered: hold never repeats, lifecycle clears', () => {
    const trig = createInspectTrigger()
    expect(trig.press()).toBe(true) // one physical press -> one action
    expect(trig.press()).toBe(false) // held/auto-repeat never re-fires
    expect(trig.press()).toBe(false)
    trig.release()
    expect(trig.press()).toBe(true) // next physical press fires again
    trig.clear() // unlock/blur/unmount path
    expect(trig.press()).toBe(true)
  })
})
