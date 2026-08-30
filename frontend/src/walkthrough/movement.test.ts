import { describe, expect, it } from 'vitest'
import { createKeyState, desiredHorizontalVelocity, NO_KEYS, yawForForward } from './movement'

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

  it('key state tracks WASD only and clears on lifecycle exits', () => {
    const ks = createKeyState()
    expect(ks.handleKey('KeyW', true)).toBe(true)
    expect(ks.handleKey('KeyD', true)).toBe(true)
    expect(ks.handleKey('KeyQ', true)).toBe(false) // unrelated key ignored
    expect(ks.keys).toEqual({ forward: true, backward: false, left: false, right: true })
    ks.clear() // blur / unlock / unmount / mode switch path
    expect(ks.keys).toEqual(NO_KEYS)
  })
})
