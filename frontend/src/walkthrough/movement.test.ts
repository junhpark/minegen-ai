import { describe, expect, it } from 'vitest'
import {
  applyLook,
  createKeyState,
  desiredHorizontalVelocity,
  isEditableTarget,
  NO_KEYS,
  NO_LOOK,
  yawForForward,
} from './movement'
import { WALKTHROUGH_CONFIG } from './config'

const K = (over: Partial<typeof NO_KEYS>) => ({ ...NO_KEYS, ...over })

describe('walkthrough movement math (rule 101)', () => {
  it('W walks along camera forward at walk speed', () => {
    const [vx, vz] = desiredHorizontalVelocity(K({ forward: true }), 0, 2)
    expect(vx).toBeCloseTo(0, 12)
    expect(vz).toBeCloseTo(-2, 12) // yaw 0 looks down -Z
  })

  it('S walks backward, A/D strafe perpendicular', () => {
    expect(desiredHorizontalVelocity(K({ backward: true }), 0, 2)[1]).toBeCloseTo(2, 12)
    const [dx, dz] = desiredHorizontalVelocity(K({ right: true }), 0, 2)
    expect(dx).toBeCloseTo(2, 12)
    expect(dz).toBeCloseTo(0, 12)
    expect(desiredHorizontalVelocity(K({ left: true }), 0, 2)[0]).toBeCloseTo(-2, 12)
  })

  it('normalizes diagonals to walk speed', () => {
    const [vx, vz] = desiredHorizontalVelocity(K({ forward: true, right: true }), 0, 2)
    expect(Math.hypot(vx, vz)).toBeCloseTo(2, 12)
  })

  it('is yaw-driven and never vertical: pitch has no input at all', () => {
    const yaw = Math.PI / 2 // facing -X
    const [vx, vz] = desiredHorizontalVelocity(K({ forward: true }), yaw, 2)
    expect(vx).toBeCloseTo(-2, 12)
    expect(vz).toBeCloseTo(0, 12)
    // the signature admits only yaw — vertical motion cannot be expressed
    expect(desiredHorizontalVelocity(K({ forward: true }), yaw, 2)).toHaveLength(2)
  })

  it('opposing keys and no input give zero velocity', () => {
    expect(desiredHorizontalVelocity(K({ forward: true, backward: true }), 1.3, 2)).toEqual([0, 0])
    expect(desiredHorizontalVelocity(NO_KEYS, 0.7, 2)).toEqual([0, 0])
  })

  it('yawForForward inverts the camera forward convention', () => {
    expect(yawForForward(0, -1)).toBeCloseTo(0, 12)
    expect(yawForForward(-1, 0)).toBeCloseTo(Math.PI / 2, 12)
  })

  it('key state tracks WASD + IJKL and clears BOTH on lifecycle exits', () => {
    const ks = createKeyState()
    expect(ks.handleKey('KeyW', true)).toBe(true)
    expect(ks.handleKey('KeyD', true)).toBe(true)
    expect(ks.handleKey('KeyJ', true)).toBe(true)
    expect(ks.handleKey('KeyI', true)).toBe(true)
    expect(ks.handleKey('KeyQ', true)).toBe(false) // unrelated key ignored
    expect(ks.keys).toEqual({ forward: true, backward: false, left: false, right: true })
    expect(ks.look).toEqual({ yawLeft: true, yawRight: false, pitchUp: true, pitchDown: false })
    ks.clear() // blur / unmount / mode switch / scenario invalidation
    expect(ks.keys).toEqual(NO_KEYS)
    expect(ks.look).toEqual(NO_LOOK)
  })
})

describe('keyboard look (hotfix §3/§17)', () => {
  const CFG = WALKTHROUGH_CONFIG
  const L = (over: Partial<typeof NO_LOOK>) => ({ ...NO_LOOK, ...over })

  it('J turns left (+yaw), L turns right, I pitches up, K pitches down, dt-scaled', () => {
    const s0 = { yaw: 0, pitch: 0 }
    const j = applyLook(s0, L({ yawLeft: true }), 0.5, CFG)
    expect(j.yaw).toBeCloseTo(((CFG.yawSpeedDegPerSec * Math.PI) / 180) * 0.5, 12)
    const l = applyLook(s0, L({ yawRight: true }), 0.5, CFG)
    expect(l.yaw).toBeCloseTo(-j.yaw, 12)
    const i = applyLook(s0, L({ pitchUp: true }), 0.25, CFG)
    expect(i.pitch).toBeCloseTo(((CFG.pitchSpeedDegPerSec * Math.PI) / 180) * 0.25, 12)
    const k = applyLook(s0, L({ pitchDown: true }), 0.25, CFG)
    expect(k.pitch).toBeCloseTo(-i.pitch, 12)
    expect(j.pitch).toBe(0) // no roll, no cross-axis
  })

  it('is frame-rate independent: many small steps == one big step', () => {
    let a = { yaw: 0.3, pitch: -0.1 }
    for (let n = 0; n < 60; n++) a = applyLook(a, L({ yawLeft: true, pitchUp: true }), 1 / 60, CFG)
    const b = applyLook({ yaw: 0.3, pitch: -0.1 }, L({ yawLeft: true, pitchUp: true }), 1, CFG)
    expect(a.yaw).toBeCloseTo(b.yaw, 9)
    expect(a.pitch).toBeCloseTo(b.pitch, 9)
  })

  it('clamps pitch at ±80° and never rolls', () => {
    const up = applyLook({ yaw: 0, pitch: 0 }, L({ pitchUp: true }), 100, CFG)
    expect(up.pitch).toBeCloseTo((80 * Math.PI) / 180, 12)
    const down = applyLook({ yaw: 0, pitch: 0 }, L({ pitchDown: true }), 100, CFG)
    expect(down.pitch).toBeCloseTo((-80 * Math.PI) / 180, 12)
  })

  it('pitch never reaches translation: velocity is a pure function of yaw', () => {
    const flat = desiredHorizontalVelocity({ ...NO_KEYS, forward: true }, 1.1, 2)
    // looking at the roof or floor cannot change the walk vector — pitch is
    // not even an input to the movement function
    expect(desiredHorizontalVelocity({ ...NO_KEYS, forward: true }, 1.1, 2)).toEqual(flat)
    expect(flat[0] * flat[0] + flat[1] * flat[1]).toBeCloseTo(4, 9)
  })
})

describe('editable-target shortcut exclusion (hotfix §5/§18)', () => {
  it('ignores INPUT/TEXTAREA/SELECT/contenteditable, accepts canvas/body', () => {
    expect(isEditableTarget({ tagName: 'INPUT' })).toBe(true)
    expect(isEditableTarget({ tagName: 'TEXTAREA' })).toBe(true)
    expect(isEditableTarget({ tagName: 'SELECT' })).toBe(true)
    expect(isEditableTarget({ tagName: 'DIV', isContentEditable: true })).toBe(true)
    expect(isEditableTarget({ tagName: 'CANVAS' })).toBe(false)
    expect(isEditableTarget({ tagName: 'BODY', isContentEditable: false })).toBe(false)
    expect(isEditableTarget(null)).toBe(false)
  })
})
