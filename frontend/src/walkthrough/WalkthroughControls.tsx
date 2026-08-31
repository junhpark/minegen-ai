import { useEffect } from 'react'
import { clearTransientInput, type InspectTrigger } from './interactionRay'
import type { KeyState } from './movement'

/**
 * Pointer-lock-gated keyboard lifecycle (§10): WASD state is tracked only
 * while pointer lock is active; every exit path — lock release, window
 * blur, unmount, mode switch — clears pressed keys so movement can never
 * stick. R is edge-triggered and fires the deterministic reset; E is
 * edge-triggered inspect (one physical press → one action, auto-repeat
 * never re-fires). Esc keeps its normal browser pointer-lock behaviour and
 * never switches app mode.
 */
export function WalkthroughControls({
  keyState,
  lockedRef,
  inspectTrigger,
  onReset,
  onInspect,
}: {
  keyState: KeyState
  lockedRef: { current: boolean }
  inspectTrigger: InspectTrigger
  onReset: () => void
  onInspect: () => void
}) {
  useEffect(() => {
    const inspect = inspectTrigger
    const down = (e: KeyboardEvent) => {
      if (!lockedRef.current) return
      if (e.code === 'KeyR') {
        onReset()
        return
      }
      if (e.code === 'KeyE') {
        if (!e.repeat && inspect.press()) onInspect()
        return
      }
      if (keyState.handleKey(e.code, true)) e.preventDefault()
    }
    const up = (e: KeyboardEvent) => {
      if (e.code === 'KeyE') {
        inspect.release()
        return
      }
      keyState.handleKey(e.code, false)
    }
    const blur = () => clearTransientInput(keyState, inspect)
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    window.addEventListener('blur', blur)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
      window.removeEventListener('blur', blur)
      clearTransientInput(keyState, inspect)
    }
  }, [inspectTrigger, keyState, lockedRef, onInspect, onReset])
  return null
}
