import { useEffect } from 'react'
import { clearTransientInput, createInspectTrigger, type InspectTrigger } from './interactionRay'
import { isEditableTarget, type KeyState } from './movement'

/**
 * Keyboard-only walkthrough input lifecycle (hotfix §2/§5): WASD walks,
 * J/L/I/K look, R resets, E inspects (STATIC_FINAL only). No pointer lock
 * and no mouse involvement — listeners are active for the whole runtime
 * mount. R and E are edge-triggered (one physical press → one action;
 * auto-repeat never re-fires). Shortcuts are ignored while an
 * input/textarea/select/contenteditable is focused. Window blur, unmount,
 * mode switch and scenario invalidation clear every transient key state.
 */
export function WalkthroughControls({
  keyState,
  inspectTrigger,
  allowInspect,
  onReset,
  onInspect,
}: {
  keyState: KeyState
  inspectTrigger: InspectTrigger
  allowInspect: boolean
  onReset: () => void
  onInspect: () => void
}) {
  useEffect(() => {
    const inspect = inspectTrigger
    const reset = createInspectTrigger() // same edge-trigger mechanism for R
    const down = (e: KeyboardEvent) => {
      if (isEditableTarget(e.target)) return
      if (e.code === 'KeyR') {
        if (!e.repeat && reset.press()) onReset()
        return
      }
      if (e.code === 'KeyE') {
        if (allowInspect && !e.repeat && inspect.press()) onInspect()
        return
      }
      if (keyState.handleKey(e.code, true)) e.preventDefault()
    }
    const up = (e: KeyboardEvent) => {
      if (e.code === 'KeyR') {
        reset.release()
        return
      }
      if (e.code === 'KeyE') {
        inspect.release()
        return
      }
      keyState.handleKey(e.code, false)
    }
    const blur = () => {
      clearTransientInput(keyState, inspect)
      reset.clear()
    }
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    window.addEventListener('blur', blur)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
      window.removeEventListener('blur', blur)
      clearTransientInput(keyState, inspect)
      reset.clear()
    }
  }, [allowInspect, inspectTrigger, keyState, onInspect, onReset])
  return null
}
