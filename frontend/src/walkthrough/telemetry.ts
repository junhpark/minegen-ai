/**
 * Shared mutable navigation telemetry (§15/§27): the player writes into a
 * plain ref-like object every physics frame (cheap field writes only);
 * DOM consumers (minimap, readout) sample it at ~8 Hz and mutate
 * SVG/text nodes directly. No Zustand, no React state, no persistence.
 */
import type { WalkthroughNavigationMode } from './navigation'

export interface WalkthroughTelemetry {
  /** Three-space position of the body center */
  x: number
  y: number
  z: number
  /** heading yaw for the map arrow (vehicle: steering heading) */
  headingYaw: number
  /** speed magnitude, m/s */
  speed: number
  mode: WalkthroughNavigationMode
  write: (
    x: number,
    y: number,
    z: number,
    headingYaw: number,
    speed: number,
    mode: WalkthroughNavigationMode,
  ) => void
  /** mine-space position (x=E, y=N, z=RL) derived from the Three fields */
  mine: () => [number, number, number]
}

export function createTelemetry(): WalkthroughTelemetry {
  const t: WalkthroughTelemetry = {
    x: 0,
    y: 0,
    z: 0,
    headingYaw: 0,
    speed: 0,
    mode: 'PERSON',
    write(x, y, z, headingYaw, speed, mode) {
      t.x = x
      t.y = y
      t.z = z
      t.headingYaw = headingYaw
      t.speed = speed
      t.mode = mode
    },
    // inverse of mineToThree (x,y,z)->(x,z,-y): mine = (x, -z, y)
    mine: () => [t.x, -t.z, t.y],
  }
  return t
}
