import { beforeEach, describe, expect, it } from 'vitest'
import { useShellStore } from './shellStore'

/** Hardening PR-3 — the reset-dialog and file-menu requests the ribbon,
 * the flow dock and the controls column send to their ONE host. */
describe('shell store requests (hardening PR-3)', () => {
  beforeEach(() => {
    useShellStore.setState({ resetDialog: null, fileMenuRequest: null })
  })

  it('opens a stage reset or the mine reset, each request with a fresh nonce', () => {
    const s = useShellStore.getState()
    expect(s.resetDialog).toBeNull()
    s.openResetDialog({ kind: 'STAGE', stage: 'LEVELS' })
    expect(useShellStore.getState().resetDialog).toEqual({
      kind: 'STAGE',
      stage: 'LEVELS',
      nonce: 1,
    })
    s.openResetDialog({ kind: 'MINE' })
    expect(useShellStore.getState().resetDialog).toEqual({ kind: 'MINE', nonce: 2 })
    s.closeResetDialog()
    expect(useShellStore.getState().resetDialog).toBeNull()
    // a repeated request is a new opening (the dialog host keys on the nonce)
    s.openResetDialog({ kind: 'MINE' })
    expect(useShellStore.getState().resetDialog?.nonce).toBe(1)
  })

  it('requests the File menu on a section and clears the request once consumed', () => {
    const s = useShellStore.getState()
    s.requestFileMenu('DEMOS')
    expect(useShellStore.getState().fileMenuRequest).toEqual({ section: 'DEMOS', nonce: 1 })
    s.requestFileMenu('OPEN')
    expect(useShellStore.getState().fileMenuRequest).toEqual({ section: 'OPEN', nonce: 2 })
    s.clearFileMenuRequest()
    expect(useShellStore.getState().fileMenuRequest).toBeNull()
  })
})
