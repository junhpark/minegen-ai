import { describe, expect, it } from 'vitest'
import { methodChangeApplyEnabled } from './methodChangeGate'

describe('methodChangeApplyEnabled (hardening H1 review B2)', () => {
  it('a mine with a world applies only after the reset plan was read', () => {
    expect(methodChangeApplyEnabled(true, { isSuccess: false, isError: false })).toBe(false)
    expect(methodChangeApplyEnabled(true, { isSuccess: false, isError: true })).toBe(false)
    expect(methodChangeApplyEnabled(true, { isSuccess: true, isError: false })).toBe(true)
  })

  it('a scenario without a world has nothing to clear and applies at once', () => {
    expect(methodChangeApplyEnabled(false, { isSuccess: false, isError: false })).toBe(true)
    expect(methodChangeApplyEnabled(false, { isSuccess: false, isError: true })).toBe(true)
  })
})
