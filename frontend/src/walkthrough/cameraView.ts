/**
 * Walk camera VIEW (hardening PR-6, Park: "트럭이 앞을 너무 가려서 … 투명도를
 * 높이거나 3/1인칭 전환"). Two presentation contracts over the unchanged
 * PR-4 body / physics / spawn rules (rules 101 / 102 / 226):
 *
 *   CHASE  the PR-4 third-person chase camera (`chaseCamera.ts`); the
 *          VEHICLE avatar is drawn as a GHOST — translucent body with its
 *          planning-box edges outlined — so the drive ahead is read through
 *          the truck while its envelope stays legible
 *   CAB    first person: the camera sits AT the body's own eye point (the
 *          driver's seat inside the truck cab, the miner's eye, the drone
 *          body front) and looks along the orbit yaw / pitch; the cab shell
 *          is not drawn from inside, the rest of the truck stays the GHOST
 *          (looking down shows the own hood as an outline over the floor —
 *          measured on the acceptance tour: a solid hood filled the lower
 *          half of the frame with one flat lamp-lit plane), person / drone
 *          avatars are hidden
 *
 * Pure: no three.js objects, no store, nothing persisted (rule 99). The eye
 * point of either view feeds the interaction ray and the headlamp (rule
 * 107) — in CAB the camera IS at that eye.
 */
import type { ChaseConfig, Vec3 } from './chaseCamera'
import { viewDirection } from './chaseCamera'
import { navigationBody, type WalkthroughNavigationMode } from './navigation'
import { truckLayout, type VehiclePreset } from './vehicle'

export type WalkCameraView = 'CHASE' | 'CAB'
export const WALK_CAMERA_VIEWS: readonly WalkCameraView[] = ['CHASE', 'CAB']
export const DEFAULT_WALK_CAMERA_VIEW: WalkCameraView = 'CHASE'

/** F toggles between the two views. */
export function toggleCameraView(view: WalkCameraView): WalkCameraView {
  return view === 'CHASE' ? 'CAB' : 'CHASE'
}

export function isWalkCameraView(v: unknown): v is WalkCameraView {
  return WALK_CAMERA_VIEWS.some((x) => x === v)
}

/** HUD label of the first-person view per body (English source string). */
export function cabViewLabel(mode: WalkthroughNavigationMode): string {
  return mode === 'VEHICLE' ? 'Cab view' : 'First person'
}

/** Legend entry of the F key per body (English source string). */
export function cabViewLegend(mode: WalkthroughNavigationMode): string {
  return mode === 'VEHICLE' ? 'Cab / Chase' : 'First person / Chase'
}

/** Opacity of the ghost body in the chase view. */
export const GHOST_OPACITY = 0.32

/** CAB view pitch clamp (deg): a seated driver looks further up than the
 * chase line (roof, back-face of a turnout) and down to the floor ahead. */
export const CAB_PITCH_MIN_DEG = -60
export const CAB_PITCH_MAX_DEG = 45
/** CAB view starts level (the chase default looks DOWN at the avatar). */
export const CAB_DEFAULT_PITCH_DEG = 0

/** The orbit config the view applies: CAB replaces only the pitch clamp. */
export function orbitConfigFor(view: WalkCameraView, chase: ChaseConfig): ChaseConfig {
  if (view === 'CHASE') return chase
  return { ...chase, pitchMinDeg: CAB_PITCH_MIN_DEG, pitchMaxDeg: CAB_PITCH_MAX_DEG }
}

export function defaultPitchDegFor(view: WalkCameraView, chase: ChaseConfig): number {
  return view === 'CHASE' ? chase.defaultPitchDeg : CAB_DEFAULT_PITCH_DEG
}

/**
 * First-person eye in the BODY frame (origin at the collider centre, +Y up,
 * −Z forward): VEHICLE the driver's eye inside the cab box
 * (`truckLayout(preset).cabEye`), PERSON the configured eye height on the
 * body axis, DRONE the front of the body at its centre height.
 */
export function firstPersonEyeOffset(mode: WalkthroughNavigationMode, preset: VehiclePreset): Vec3 {
  if (mode === 'VEHICLE') return truckLayout(preset).cabEye
  const nav = navigationBody(mode, preset.id)
  if (mode === 'PERSON') return [0, nav.eyeHeightM - nav.bodyHeightM / 2, 0]
  return [0, 0, -nav.bodyRadiusM * 0.7]
}

/**
 * The body's LAMP point in the body frame — where the headlamp beam leaves
 * the body in EITHER view: the truck's headlights (the midpoint of the two
 * front lamps on the bumper), the miner's cap lamp (its eye), the drone's
 * front. Measured on the acceptance tour: a beam leaving the truck's EYE
 * (the cab seat) lit the own bumper from 0.9 m when the cab view looked
 * down, and the frame blew out to the lamp colour.
 */
export function lampOffset(mode: WalkthroughNavigationMode, preset: VehiclePreset): Vec3 {
  if (mode !== 'VEHICLE') return firstPersonEyeOffset(mode, preset)
  const lamps = truckLayout(preset).headlights
  const n = lamps.length
  return [
    lamps.reduce((s, p) => s + p[0], 0) / n,
    lamps.reduce((s, p) => s + p[1], 0) / n,
    lamps.reduce((s, p) => s + p[2], 0) / n,
  ]
}

/** Rotate a body-frame offset by the body yaw about +Y (yaw 0 → −Z). */
export function rotateOffsetByYaw(offset: Vec3, yaw: number): Vec3 {
  const c = Math.cos(yaw)
  const s = Math.sin(yaw)
  return [offset[0] * c + offset[2] * s, offset[1], -offset[0] * s + offset[2] * c]
}

/** CAB camera pose: the camera at the eye, looking along the view direction. */
export function cabPose(eye: Vec3, yaw: number, pitch: number): { position: Vec3; lookAt: Vec3 } {
  const d = viewDirection(yaw, pitch)
  return { position: eye, lookAt: [eye[0] + d[0], eye[1] + d[1], eye[2] + d[2]] }
}

export interface AvatarPresentation {
  /** the avatar group is rendered at all */
  visible: boolean
  /** translucent body + outlined planning edges (VEHICLE in either view) */
  ghost: boolean
  /** the truck's cab shell (box + glass) is drawn — never from inside */
  cabVisible: boolean
}

/** What the avatar shows per body and view. */
export function avatarPresentation(
  mode: WalkthroughNavigationMode,
  view: WalkCameraView,
): AvatarPresentation {
  if (view === 'CHASE') return { visible: true, ghost: mode === 'VEHICLE', cabVisible: true }
  if (mode === 'VEHICLE') return { visible: true, ghost: true, cabVisible: false }
  return { visible: false, ghost: false, cabVisible: false }
}
