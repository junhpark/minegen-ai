import { describe, expect, it } from 'vitest'
import { methodChangeApplyEnabled } from './methodChangeGate'

const read = { isSuccess: true, isError: false, isFetching: false }

describe('methodChangeApplyEnabled (hardening H1 review B2 / round 2 B1)', () => {
  it('a mine with a world applies only after the reset plan was read', () => {
    expect(methodChangeApplyEnabled(true, { ...read, isSuccess: false })).toBe(false)
    expect(
      methodChangeApplyEnabled(true, { isSuccess: false, isError: true, isFetching: false }),
    ).toBe(false)
    expect(methodChangeApplyEnabled(true, read)).toBe(true)
  })

  it('a cached success that is being refetched is not a read of THIS dialog (B1)', () => {
    expect(methodChangeApplyEnabled(true, { ...read, isFetching: true })).toBe(false)
    expect(
      methodChangeApplyEnabled(true, { isSuccess: false, isError: true, isFetching: true }),
    ).toBe(false)
  })

  it('a scenario without a world has nothing to clear and applies at once', () => {
    expect(
      methodChangeApplyEnabled(false, { isSuccess: false, isError: false, isFetching: true }),
    ).toBe(true)
    expect(
      methodChangeApplyEnabled(false, { isSuccess: false, isError: true, isFetching: false }),
    ).toBe(true)
  })
})
