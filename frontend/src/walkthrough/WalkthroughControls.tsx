import { useEffect } from 'react'
import { clearTransientInput, createInspectTrigger, type InspectTrigger } from './interactionRay'
import { isEditableTarget, type KeyState } from './movement'
import { type WalkthroughNavigationMode } from './navigation'

/**
 * Keyboard-only walkthrough input lifecycle (hotfix §2/§5, PR-4 third
 * person): WASD moves, J/L/I/K orbit the chase camera, R resets, E inspects
 * (STATIC_FINAL only), 1/2/3 switch the mode and V cycles the truck class.
 * No pointer lock and no mouse involvement — listeners are active for the
 * whole runtime mount. R, E and V are edge-triggered (one physical press →
 * one action; auto-repeat never re-fires). Shortcuts are ignored while an
 * input/textarea/select/contenteditable is focused. Window blur, unmount,
 * mode switch and scenario invalidation clear every transient key state.
 */
export function WalkthroughControls({
  keyState,
  inspectTrigger,
  allowInspect,
  onReset,
  onInspect,
  onNavigationMode,
  onCycleVehiclePreset,
}: {
  keyState: KeyState
  inspectTrigger: InspectTrigger
  allowInspect: boolean
  onReset: () => void
  onInspect: () => void
  onNavigationMode: (mode: WalkthroughNavigationMode) => void
  onCycleVehiclePreset?: () => void
}) {
  useEffect(() => {
    const inspect = inspectTrigger
    const reset = createInspectTrigger() // same edge-trigger mechanism for R
    const cycle = createInspectTrigger() // …and for V
    const down = (e: KeyboardEvent) => {
      if (isEditableTarget(e.target)) return
      if (e.code === 'KeyR') {
        if (!e.repeat && reset.press()) onReset()
        return
      }
      if (e.code === 'KeyV') {
        if (!e.repeat && cycle.press()) onCycleVehiclePreset?.()
        return
      }
      if (e.code === 'Digit1' || e.code === 'Digit2' || e.code === 'Digit3') {
        if (!e.repeat) {
          onNavigationMode(
            e.code === 'Digit1' ? 'PERSON' : e.code === 'Digit2' ? 'VEHICLE' : 'DRONE',
          )
        }
        return
      }
      if (e.code === 'KeyE') {
        if (allowInspect && !e.repeat && inspect.press()) onInspect()
        return
      }
      if (keyState.handleKey(e.code, true)) e.preventDefault() // incl. Space scroll
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
      if (e.code === 'KeyV') {
        cycle.release()
        return
      }
      keyState.handleKey(e.code, false)
    }
    const blur = () => {
      clearTransientInput(keyState, inspect)
      reset.clear()
      cycle.clear()
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
      cycle.clear()
    }
  }, [
    allowInspect,
    inspectTrigger,
    keyState,
    onCycleVehiclePreset,
    onInspect,
    onNavigationMode,
    onReset,
  ])
  return null
}
