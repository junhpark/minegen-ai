import { useEffect, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { CapsuleCollider, RigidBody, type RapierRigidBody } from '@react-three/rapier'
import type { WalkthroughConfig } from './config'
import { applyLook, desiredHorizontalVelocity, type KeyState, type LookState } from './movement'
import {
  droneVelocity,
  navigationBody,
  personSpeed,
  vehicleStep,
  VEHICLE_CONFIG,
  type WalkthroughNavigationMode,
} from './navigation'
import type { WalkthroughSpawn } from './spawn'
import type { WalkthroughTelemetry } from './telemetry'

/**
 * Mode-aware navigation body (Phase 16 §5–9, rule 101 preserved in
 * substance): one upright collision-constrained Rapier capsule per
 * navigation mode against the exact tunnel trimesh + temporal frontier —
 * no mode is noclip. Camera orientation is keyboard LookState (IJKL,
 * dt-scaled, pitch clamped, no roll) in every mode; pitch NEVER reaches
 * translation.
 *   PERSON  gravity ON, yaw-only walk, Shift run
 *   VEHICLE gravity ON, heading steered by A/D at a bounded rate, W/S
 *           drive, Shift boost, elevated inspection eye
 *   DRONE   gravityScale 0, yaw-based XYZ velocity, Space/C vertical,
 *           Shift boost
 * The component is remounted per mode (key), which IS the documented safe
 * mode-switch behaviour (§29 accepted baseline): switching always resets
 * to the deterministic mode-specific spawn — no collider morphing inside
 * geometry, no catapult physics, never a world-origin teleport.
 */
export function WalkthroughPlayer({
  mode,
  config,
  spawn,
  keyState,
  resetSignal,
  telemetry,
}: {
  mode: WalkthroughNavigationMode
  config: WalkthroughConfig
  spawn: WalkthroughSpawn
  keyState: KeyState
  resetSignal: { current: number }
  telemetry: WalkthroughTelemetry
}) {
  const body = useRef<RapierRigidBody>(null)
  const camera = useThree((s) => s.camera)
  const appliedReset = useRef(-1)
  const look = useRef<LookState>({ yaw: spawn.yaw, pitch: 0 })
  const heading = useRef(spawn.yaw)
  const nav = navigationBody(mode)
  const eyeOffset = nav.eyeHeightM - nav.bodyHeightM / 2

  useEffect(() => {
    look.current = { yaw: spawn.yaw, pitch: 0 }
    heading.current = spawn.yaw
    camera.rotation.order = 'YXZ'
    camera.rotation.set(0, spawn.yaw, 0)
  }, [camera, spawn])

  useFrame((_, delta) => {
    const rb = body.current
    if (!rb) return
    if (resetSignal.current !== appliedReset.current) {
      appliedReset.current = resetSignal.current
      rb.setTranslation(
        {
          x: spawn.bodyPositionThree[0],
          y: spawn.bodyPositionThree[1],
          z: spawn.bodyPositionThree[2],
        },
        true,
      )
      rb.setLinvel({ x: 0, y: 0, z: 0 }, true)
      rb.setAngvel({ x: 0, y: 0, z: 0 }, true)
      keyState.clear()
      look.current = { yaw: spawn.yaw, pitch: 0 }
      heading.current = spawn.yaw
    }
    look.current = applyLook(look.current, keyState.look, delta, config)
    camera.rotation.order = 'YXZ'
    camera.rotation.set(look.current.pitch, look.current.yaw, 0)

    const lv = rb.linvel()
    let headingForMap = look.current.yaw
    if (mode === 'PERSON') {
      const [vx, vz] = desiredHorizontalVelocity(
        keyState.keys,
        look.current.yaw,
        personSpeed(keyState.actions.boost),
      )
      rb.setLinvel({ x: vx, y: lv.y, z: vz }, true)
    } else if (mode === 'VEHICLE') {
      const step = vehicleStep(
        { headingYaw: heading.current },
        { ...keyState.keys, boost: keyState.actions.boost },
        delta,
        VEHICLE_CONFIG,
      )
      heading.current = step.headingYaw
      headingForMap = step.headingYaw
      rb.setLinvel({ x: step.vx, y: lv.y, z: step.vz }, true)
    } else {
      const [vx, vy, vz] = droneVelocity(
        { ...keyState.keys, boost: keyState.actions.boost },
        { up: keyState.actions.up, down: keyState.actions.down },
        look.current.yaw,
      )
      rb.setLinvel({ x: vx, y: vy, z: vz }, true)
    }
    const t = rb.translation()
    camera.position.set(t.x, t.y + eyeOffset, t.z)
    // cheap per-frame telemetry ref write; consumers sample at ~8 Hz (§15)
    const v = rb.linvel()
    telemetry.write(t.x, t.y, t.z, headingForMap, Math.hypot(v.x, v.y, v.z), mode)
  })

  const halfHeight = Math.max(nav.bodyHeightM / 2 - nav.bodyRadiusM, 0.01)
  return (
    <RigidBody
      ref={body}
      position={spawn.bodyPositionThree}
      colliders={false}
      enabledRotations={[false, false, false]}
      lockRotations
      ccd
      canSleep={false}
      friction={0}
      gravityScale={nav.gravityScale}
    >
      <CapsuleCollider args={[halfHeight, nav.bodyRadiusM]} />
    </RigidBody>
  )
}
