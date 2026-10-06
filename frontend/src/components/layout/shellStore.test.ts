import { beforeEach, describe, expect, it } from 'vitest'
import { runningStages, useShellStore } from './shellStore'

describe('shellStore (hardening H1 §4.2)', () => {
  beforeEach(() => {
    useShellStore.setState(useShellStore.getInitialState())
  })

  it('a mounted card reports its tone and withdraws it on unmount', () => {
    const { reportTone } = useShellStore.getState()
    reportTone('LEVELS', 'RUNNING')
    reportTone('NETWORK', 'READY')
    expect(runningStages(useShellStore.getState().stageTones)).toEqual(new Set(['LEVELS']))
    reportTone('LEVELS', null)
    expect(runningStages(useShellStore.getState().stageTones)).toEqual(new Set())
    expect(useShellStore.getState().stageTones).toEqual({ NETWORK: 'READY' })
  })

  it('reporting the same tone again is a no-op (no re-render churn)', () => {
    useShellStore.getState().reportTone('LAYOUT', 'READY')
    const before = useShellStore.getState().stageTones
    useShellStore.getState().reportTone('LAYOUT', 'READY')
    expect(useShellStore.getState().stageTones).toBe(before)
  })
})
