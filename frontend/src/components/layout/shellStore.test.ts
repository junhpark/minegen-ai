import { beforeEach, describe, expect, it } from 'vitest'
import { runningStages, stageTone, useShellStore } from './shellStore'

describe('shellStore (hardening H1 §4.2)', () => {
  beforeEach(() => {
    useShellStore.setState(useShellStore.getInitialState())
  })

  it('a mounted card reports its tone and withdraws it on unmount', () => {
    const { reportTone } = useShellStore.getState()
    reportTone('LEVELS', 'levels-card', 'RUNNING')
    reportTone('NETWORK', 'network-card', 'READY')
    expect(runningStages(useShellStore.getState().stageTones)).toEqual(new Set(['LEVELS']))
    reportTone('LEVELS', 'levels-card', null)
    expect(runningStages(useShellStore.getState().stageTones)).toEqual(new Set())
    expect(useShellStore.getState().stageTones).toEqual({ NETWORK: { 'network-card': 'READY' } })
  })

  it('reporting the same tone again is a no-op (no re-render churn)', () => {
    useShellStore.getState().reportTone('LAYOUT', 'layout-card', 'READY')
    const before = useShellStore.getState().stageTones
    useShellStore.getState().reportTone('LAYOUT', 'layout-card', 'READY')
    expect(useShellStore.getState().stageTones).toBe(before)
  })

  it('sibling cards of one stage never overwrite each other: RUNNING wins (round 2 S3)', () => {
    const { reportTone } = useShellStore.getState()
    reportTone('EXCAVATION', 'tunnel-card', 'RUNNING')
    reportTone('EXCAVATION', 'development-card', 'READY')
    let tones = useShellStore.getState().stageTones
    expect(stageTone(tones, 'EXCAVATION')).toBe('RUNNING')
    expect(runningStages(tones)).toEqual(new Set(['EXCAVATION']))
    // the READY sibling re-reporting (a re-render) does not clear the running job
    reportTone('EXCAVATION', 'development-card', 'NOT_GENERATED')
    tones = useShellStore.getState().stageTones
    expect(runningStages(tones)).toEqual(new Set(['EXCAVATION']))
    // the running card finishing clears it; the sibling's report survives
    reportTone('EXCAVATION', 'tunnel-card', 'READY')
    tones = useShellStore.getState().stageTones
    expect(runningStages(tones)).toEqual(new Set())
    expect(stageTone(tones, 'EXCAVATION')).toBe('READY')
    // a failure outranks a ready sibling; the running job outranks both
    reportTone('EXCAVATION', 'development-card', 'FAILED')
    expect(stageTone(useShellStore.getState().stageTones, 'EXCAVATION')).toBe('FAILED')
    reportTone('EXCAVATION', 'tunnel-card', 'RUNNING')
    expect(stageTone(useShellStore.getState().stageTones, 'EXCAVATION')).toBe('RUNNING')
    // withdrawing every reporter removes the stage entry
    reportTone('EXCAVATION', 'tunnel-card', null)
    reportTone('EXCAVATION', 'development-card', null)
    expect(useShellStore.getState().stageTones).toEqual({})
    expect(stageTone(useShellStore.getState().stageTones, 'EXCAVATION')).toBeNull()
  })
})
