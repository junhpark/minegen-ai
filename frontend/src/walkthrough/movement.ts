/**
 * Pure first-person movement math (rule 101): walking direction uses camera
 * YAW only — pitch never produces vertical motion. Runtime controller math,
 * never engineering geometry.
 */
export interface MovementKeys {
  forward: boolean
  backward: boolean
  left: boolean
  right: boolean
}

export const NO_KEYS: MovementKeys = { forward: false, backward: false, left: false, right: false }

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
  // right = forward × up for Y-up: (-fz, 0, fx) with our forward = (cos yaw, 0, -sin yaw)
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

/**
 * Mutable pressed-key state with explicit lifecycle: cleared on blur,
 * pointer-lock release, unmount and mode switch so keys can never stick.
 */
export interface KeyState {
  keys: MovementKeys
  handleKey: (code: string, down: boolean) => boolean
  clear: () => void
}

export function createKeyState(): KeyState {
  const keys: MovementKeys = { ...NO_KEYS }
  return {
    keys,
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
        default:
          return false
      }
    },
    clear() {
      keys.forward = false
      keys.backward = false
      keys.left = false
      keys.right = false
    },
  }
}
