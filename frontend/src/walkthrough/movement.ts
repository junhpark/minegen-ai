/**
 * Pure first-person movement + keyboard-look math (rule 101, hotfix §2–5):
 * walking direction uses camera YAW only — pitch never produces vertical
 * motion. The walkthrough is KEYBOARD-ONLY: WASD walks, J/L yaw, I/K
 * pitch; mouse movement never rotates the camera and no pointer lock is
 * required. Runtime controller math, never engineering geometry.
 */
export interface MovementKeys {
  forward: boolean
  backward: boolean
  left: boolean
  right: boolean
}

export interface LookKeys {
  yawLeft: boolean
  yawRight: boolean
  pitchUp: boolean
  pitchDown: boolean
}

export const NO_KEYS: MovementKeys = { forward: false, backward: false, left: false, right: false }
export const NO_LOOK: LookKeys = {
  yawLeft: false,
  yawRight: false,
  pitchUp: false,
  pitchDown: false,
}

/**
 * Desired horizontal walking velocity in Three coordinates (XZ plane).
 * yaw follows the Three camera convention: yaw=0 looks down -Z.
 * Diagonal input is normalized so speed never exceeds walkSpeed.
 */
export function desiredHorizontalVelocity(
  keys: MovementKeys,
  yaw: number,
  walkSpeedMps: number,
): [number, number] {
  const fx = -Math.sin(yaw)
  const fz = -Math.cos(yaw)
  const rx = Math.cos(yaw)
  const rz = -Math.sin(yaw)
  let dx = 0
  let dz = 0
  if (keys.forward) {
    dx += fx
    dz += fz
  }
  if (keys.backward) {
    dx -= fx
    dz -= fz
  }
  if (keys.right) {
    dx += rx
    dz += rz
  }
  if (keys.left) {
    dx -= rx
    dz -= rz
  }
  const len = Math.hypot(dx, dz)
  if (len < 1e-9) return [0, 0]
  return [(dx / len) * walkSpeedMps, (dz / len) * walkSpeedMps]
}

/** Yaw for a horizontal Three-space forward vector (camera convention). */
export function yawForForward(fx: number, fz: number): number {
  return Math.atan2(-fx, -fz)
}

export interface LookState {
  yaw: number
  pitch: number
}

/**
 * Frame-rate-independent keyboard look (§3): angular delta = speed × dt.
 * Three yaw convention: positive yaw turns LEFT, so J (look left)
 * increases yaw and L decreases it; I pitches up (positive camera X
 * rotation), K down. Pitch clamps at ±maxPitchDeg. No roll, ever.
 */
export function applyLook(
  state: LookState,
  keys: LookKeys,
  dtSeconds: number,
  config: { yawSpeedDegPerSec: number; pitchSpeedDegPerSec: number; maxPitchDeg: number },
): LookState {
  const yawStep = ((config.yawSpeedDegPerSec * Math.PI) / 180) * dtSeconds
  const pitchStep = ((config.pitchSpeedDegPerSec * Math.PI) / 180) * dtSeconds
  let yaw = state.yaw
  let pitch = state.pitch
  if (keys.yawLeft) yaw += yawStep
  if (keys.yawRight) yaw -= yawStep
  if (keys.pitchUp) pitch += pitchStep
  if (keys.pitchDown) pitch -= pitchStep
  const clamp = (config.maxPitchDeg * Math.PI) / 180
  if (pitch > clamp) pitch = clamp
  if (pitch < -clamp) pitch = -clamp
  return { yaw, pitch }
}

/**
 * Mutable pressed-key state (WASD movement + IJKL look) with explicit
 * lifecycle: cleared on window blur, unmount, mode switch and scenario
 * invalidation so keys can never stick.
 */
export interface KeyState {
  keys: MovementKeys
  look: LookKeys
  handleKey: (code: string, down: boolean) => boolean
  clear: () => void
}

export function createKeyState(): KeyState {
  const keys: MovementKeys = { ...NO_KEYS }
  const look: LookKeys = { ...NO_LOOK }
  return {
    keys,
    look,
    handleKey(code: string, down: boolean): boolean {
      switch (code) {
        case 'KeyW':
          keys.forward = down
          return true
        case 'KeyS':
          keys.backward = down
          return true
        case 'KeyA':
          keys.left = down
          return true
        case 'KeyD':
          keys.right = down
          return true
        case 'KeyJ':
          look.yawLeft = down
          return true
        case 'KeyL':
          look.yawRight = down
          return true
        case 'KeyI':
          look.pitchUp = down
          return true
        case 'KeyK':
          look.pitchDown = down
          return true
        default:
          return false
      }
    },
    clear() {
      Object.assign(keys, NO_KEYS)
      Object.assign(look, NO_LOOK)
    },
  }
}

/**
 * Walkthrough shortcuts must never fire while the user is typing (§5):
 * INPUT / TEXTAREA / SELECT / contenteditable targets are excluded.
 */
export function isEditableTarget(target: unknown): boolean {
  const t = target as { tagName?: string; isContentEditable?: boolean } | null
  if (!t) return false
  if (t.isContentEditable) return true
  const tag = t.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
}
