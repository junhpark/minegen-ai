import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import {
  BallCollider,
  CapsuleCollider,
  CuboidCollider,
  RigidBody,
  useBeforePhysicsStep,
  useRapier,
  type RapierCollider,
  type RapierRigidBody,
} from '@react-three/rapier'
import { Group, Vector3 } from 'three'
import { DroneAvatar, PersonAvatar, TruckAvatar } from './avatars'
import { applyOrbit, resolveChase, type OrbitState, type Vec3 } from './chaseCamera'
import type { WalkthroughConfig } from './config'
import { desiredHorizontalVelocity, yawForForward, type KeyState } from './movement'
import {
  chaseFor,
  droneVelocity,
  locomotionFor,
  navigationBody,
  personSpeed,
  vehicleDriveVelocity,
  vehicleSignedSpeed,
  type WalkthroughNavigationMode,
} from './navigation'
import type { WalkthroughSpawn } from './spawn'
import type { WalkthroughTelemetry } from './telemetry'
import {
  integrateHeading,
  vehicleBoxHalfExtents,
  vehiclePreset,
  yawQuaternion,
  type VehiclePresetId,
} from './vehicle'

/** largest physics step the locomotion integrates (a stalled tab never
 * produces one giant translation through a wall) */
const MAX_STEP_S = 1 / 30
/** downward speed kept while grounded so the controller stays in contact */
const GROUND_STICK_MPS = 1.0
const TERMINAL_FALL_MPS = 30
/** a camera-line hit closer than this is the line's own starting surface */
const CAST_START_EPSILON_M = 0.05

/**
 * Third-person navigation body (hardening PR-4 W1b / W2; rules 101 / 107 /
 * 187 as amended). ONE kinematic-position RigidBody per mode / vehicle
 * preset drives a Rapier `KinematicCharacterController` against the exact
 * excavation trimeshes and the temporal barriers — collide-and-slide,
 * autostep and snap-to-ground sized by `navigation.ts::locomotionFor`
 * (gravity integrated here; the drone has none). No mode is noclip, nothing
 * is tuned per junction, and the controller never moves a fixed collider.
 *
 *   PERSON   camera-relative WASD; the miner turns to face the walk
 *   VEHICLE  A/D steer the truck heading (bicycle rule), W/S drive along it;
 *            the box collider is the preset's planning body
 *   DRONE    horizontal WASD along the camera yaw, Space / C vertical
 *
 * The camera is a chase camera orbiting the avatar's EYE point (IJKL orbit,
 * dt-scaled, pitch clamped) and is pulled in along the view line when an
 * authoritative collider stands between the eye and the desired position
 * (`world.castRay`, the avatar's own collider excluded). The eye point is
 * published through `eyeRef` for the interaction ray and the headlamp.
 * Remounted per mode / preset (key) at the deterministic spawn — the
 * documented safe switch behaviour (§29): no collider morphing inside
 * geometry, never a world-origin teleport.
 */
export function WalkthroughPlayer({
  mode,
  vehiclePresetId,
  config,
  spawn,
  keyState,
  resetSignal,
  teleportRef,
  telemetry,
  eyeRef,
}: {
  mode: WalkthroughNavigationMode
  vehiclePresetId: VehiclePresetId
  config: WalkthroughConfig
  spawn: WalkthroughSpawn
  keyState: KeyState
  resetSignal: { current: number }
  /** when set, the next reset lands at this pose instead of the entry
   * spawn (teleport); consumed once */
  teleportRef: { current: WalkthroughSpawn | null }
  telemetry: WalkthroughTelemetry
  /** the avatar's eye point in Three coordinates, updated every frame */
  eyeRef: { current: Vector3 }
}) {
  const body = useRef<RapierRigidBody>(null)
  const colliderRef = useRef<RapierCollider>(null)
  const avatar = useRef<Group>(null)
  const camera = useThree((s) => s.camera)
  const { world, rapier } = useRapier()
  const nav = navigationBody(mode, vehiclePresetId)
  const locomotion = locomotionFor(mode)
  const chase = chaseFor(mode, vehiclePresetId)
  const preset = vehiclePreset(vehiclePresetId)
  const eyeOffset = nav.eyeHeightM - nav.bodyHeightM / 2

  const controller = useMemo(() => {
    const c = world.createCharacterController(0.05)
    c.setUp({ x: 0, y: 1, z: 0 })
    c.setSlideEnabled(true)
    c.setMaxSlopeClimbAngle((locomotion.maxSlopeClimbDeg * Math.PI) / 180)
    c.setMinSlopeSlideAngle((locomotion.minSlopeSlideDeg * Math.PI) / 180)
    c.setApplyImpulsesToDynamicBodies(false)
    if (locomotion.autostepMaxHeightM > 0) {
      c.enableAutostep(locomotion.autostepMaxHeightM, locomotion.autostepMinWidthM, false)
    }
    if (locomotion.snapToGroundM > 0) c.enableSnapToGround(locomotion.snapToGroundM)
    return c
  }, [world, locomotion])
  useEffect(() => () => world.removeCharacterController(controller), [world, controller])

  const appliedReset = useRef(-1)
  const heading = useRef(spawn.yaw)
  const orbit = useRef<OrbitState>({
    yaw: spawn.yaw,
    pitch: (chase.defaultPitchDeg * Math.PI) / 180,
  })
  const verticalSpeed = useRef(0)
  const speed = useRef(0)

  useEffect(() => {
    heading.current = spawn.yaw
    orbit.current = { yaw: spawn.yaw, pitch: (chase.defaultPitchDeg * Math.PI) / 180 }
  }, [spawn, chase.defaultPitchDeg])

  // the vehicle body at its current translation with a candidate heading,
  // tested against every other non-sensor collider (walls, caps, barriers)
  const rotatedBodyIntersects = (
    rb: RapierRigidBody,
    own: RapierCollider,
    yaw: number,
  ): boolean => {
    const [qx, qy, qz, qw] = yawQuaternion(yaw)
    let blocked = false
    world.intersectionsWithShape(
      rb.translation(),
      { x: qx, y: qy, z: qz, w: qw },
      own.shape,
      () => {
        blocked = true
        return false
      },
      rapier.QueryFilterFlags.EXCLUDE_SENSORS,
      undefined,
      own,
      rb,
      (c) => c !== own,
    )
    return blocked
  }

  // locomotion runs once per physics step with the fixed step length
  useBeforePhysicsStep((physics) => {
    const rb = body.current
    const collider = colliderRef.current
    if (!rb || !collider) return
    const dt = Math.min(physics.timestep, MAX_STEP_S)
    if (resetSignal.current !== appliedReset.current) {
      appliedReset.current = resetSignal.current
      // R -> entry spawn; teleport -> the requested station pose
      const target = teleportRef.current ?? spawn
      teleportRef.current = null
      const p = target.bodyPositionThree
      rb.setTranslation({ x: p[0], y: p[1], z: p[2] }, true)
      rb.setNextKinematicTranslation({ x: p[0], y: p[1], z: p[2] })
      heading.current = target.yaw
      orbit.current = { yaw: target.yaw, pitch: (chase.defaultPitchDeg * Math.PI) / 180 }
      verticalSpeed.current = 0
      keyState.clear()
      if (mode === 'VEHICLE') {
        const [qx, qy, qz, qw] = yawQuaternion(target.yaw)
        rb.setRotation({ x: qx, y: qy, z: qz, w: qw }, true)
        rb.setNextKinematicRotation({ x: qx, y: qy, z: qz, w: qw })
      }
    }
    const prevYaw = orbit.current.yaw
    orbit.current = applyOrbit(orbit.current, keyState.look, dt, config, chase)
    let vx = 0
    let vy = 0
    let vz = 0
    if (mode === 'PERSON') {
      ;[vx, vz] = desiredHorizontalVelocity(
        keyState.keys,
        orbit.current.yaw,
        personSpeed(keyState.actions.boost),
      )
      if (Math.hypot(vx, vz) > 1e-6) heading.current = yawForForward(vx, vz)
    } else if (mode === 'VEHICLE') {
      const drive = {
        forward: keyState.keys.forward,
        backward: keyState.keys.backward,
        boost: keyState.actions.boost,
      }
      const signed = vehicleSignedSpeed(drive)
      const before = heading.current
      const next = integrateHeading(heading.current, keyState.keys, signed, dt, preset)
      // a kinematic rotation is not collision-checked by the character
      // controller: the turned body is tested against the tunnel first and
      // the heading change is refused for this step when it would intersect
      if (next !== before && !rotatedBodyIntersects(rb, collider, next)) heading.current = next
      // the chase camera turns with the truck; IJKL add an orbit offset on top
      orbit.current = {
        yaw: orbit.current.yaw + (heading.current - before),
        pitch: orbit.current.pitch,
      }
      ;[vx, vz] = vehicleDriveVelocity(drive, heading.current)
    } else {
      heading.current = orbit.current.yaw
      ;[vx, vy, vz] = droneVelocity(
        { ...keyState.keys, boost: keyState.actions.boost },
        { up: keyState.actions.up, down: keyState.actions.down },
        orbit.current.yaw,
        0,
      )
    }
    if (locomotion.gravity) {
      const g = config.gravityMps2
      verticalSpeed.current = Math.max(verticalSpeed.current - g * dt, -TERMINAL_FALL_MPS)
      vy = verticalSpeed.current
    }
    controller.computeColliderMovement(
      collider,
      { x: vx * dt, y: vy * dt, z: vz * dt },
      rapier.QueryFilterFlags.EXCLUDE_SENSORS,
      undefined,
      (c) => c !== collider,
    )
    const mv = controller.computedMovement()
    if (locomotion.gravity) {
      verticalSpeed.current = controller.computedGrounded() ? -GROUND_STICK_MPS : mv.y / dt
    }
    const t = rb.translation()
    rb.setNextKinematicTranslation({ x: t.x + mv.x, y: t.y + mv.y, z: t.z + mv.z })
    if (mode === 'VEHICLE') {
      const [qx, qy, qz, qw] = yawQuaternion(heading.current)
      rb.setNextKinematicRotation({ x: qx, y: qy, z: qz, w: qw })
    }
    speed.current = Math.hypot(mv.x, mv.y, mv.z) / dt
    void prevYaw
  })

  // camera, avatar facing, eye point and telemetry follow the body each frame
  const anchor = useMemo(() => new Vector3(), [])
  const lookTarget = useMemo(() => new Vector3(), [])
  useFrame(() => {
    const rb = body.current
    if (!rb) return
    const t = rb.translation()
    anchor.set(t.x, t.y + eyeOffset, t.z)
    eyeRef.current.copy(anchor)
    if (avatar.current && mode !== 'VEHICLE') avatar.current.rotation.y = heading.current
    const { yaw, pitch } = orbit.current
    // occlusion: cast from the (shifted) eye toward each candidate camera
    // position; the avatar's own collider is excluded
    // the line starts ON the avatar's own collider (eye / roof point), so the
    // avatar is excluded three ways (collider, body, predicate) and a
    // zero-travel hit — a coplanar start on a surface — is never a blocker
    const own = colliderRef.current
    const ownBody = rb
    const cast = (origin: Vec3, dir: Vec3, maxDistance: number): number | null => {
      const ray = new rapier.Ray(
        { x: origin[0], y: origin[1], z: origin[2] },
        { x: dir[0], y: dir[1], z: dir[2] },
      )
      const hit = world.castRay(
        ray,
        maxDistance,
        true,
        rapier.QueryFilterFlags.EXCLUDE_SENSORS,
        undefined,
        own ?? undefined,
        ownBody,
        (c) => c !== own,
      )
      if (!hit || hit.timeOfImpact < CAST_START_EPSILON_M) return null
      return hit.timeOfImpact
    }
    const pose = resolveChase([anchor.x, anchor.y, anchor.z], yaw, pitch, chase, cast)
    camera.position.set(pose.position[0], pose.position[1], pose.position[2])
    lookTarget.set(pose.lookAt[0], pose.lookAt[1], pose.lookAt[2])
    camera.lookAt(lookTarget)
    telemetry.write(t.x, t.y, t.z, heading.current, speed.current, mode)
  })

  const halfHeight = Math.max(nav.bodyHeightM / 2 - nav.bodyRadiusM, 0.01)
  const box = vehicleBoxHalfExtents(preset)
  return (
    <RigidBody
      ref={body}
      type="kinematicPosition"
      position={spawn.bodyPositionThree}
      rotation={mode === 'VEHICLE' ? [0, spawn.yaw, 0] : undefined}
      colliders={false}
      canSleep={false}
    >
      {mode === 'PERSON' ? (
        <CapsuleCollider ref={colliderRef} args={[halfHeight, nav.bodyRadiusM]} />
      ) : mode === 'VEHICLE' ? (
        <CuboidCollider ref={colliderRef} args={box} />
      ) : (
        <BallCollider ref={colliderRef} args={[nav.bodyRadiusM]} />
      )}
      <group ref={avatar}>
        {mode === 'PERSON' ? (
          <PersonAvatar bodyHeightM={nav.bodyHeightM} />
        ) : mode === 'VEHICLE' ? (
          <TruckAvatar preset={preset} />
        ) : (
          <DroneAvatar />
        )}
      </group>
    </RigidBody>
  )
}
