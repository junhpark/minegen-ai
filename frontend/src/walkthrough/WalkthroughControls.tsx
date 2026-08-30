import { useEffect } from 'react'
import type { KeyState } from './movement'

/**
 * Pointer-lock-gated keyboard lifecycle (§10): WASD state is tracked only
 * while pointer lock is active; every exit path — lock release, window
 * blur, unmount, mode switch — clears pressed keys so movement can never
 * stick. R is edge-triggered and fires the deterministic reset. Esc keeps
 * its normal browser pointer-lock behaviour and never switches app mode.
 */
export function WalkthroughControls({
  keyState,
  lockedRef,
  onReset,
}: {
  keyState: KeyState
  lockedRef: { current: boolean }
  onReset: () => void
}) {
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (!lockedRef.current) return
      if (e.code === 'KeyR') {
        onReset()
        return
      }
      if (keyState.handleKey(e.code, true)) e.preventDefault()
    }
    const up = (e: KeyboardEvent) => {
      keyState.handleKey(e.code, false)
    }
    const blur = () => keyState.clear()
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    window.addEventListener('blur', blur)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
      window.removeEventListener('blur', blur)
      keyState.clear()
    }
  }, [keyState, lockedRef, onReset])
  return null
}
