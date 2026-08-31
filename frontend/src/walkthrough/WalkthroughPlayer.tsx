import { useEffect, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { CapsuleCollider, RigidBody, type RapierRigidBody } from '@react-three/rapier'
import { capsuleHalfHeight, eyeOffsetFromBodyCenter, type WalkthroughConfig } from './config'
import { applyLook, desiredHorizontalVelocity, type KeyState, type LookState } from './movement'
import type { WalkthroughSpawn } from './spawn'

/**
 * Upright collision-constrained player (rule 101): dynamic Rapier capsule,
 * rotations locked, CCD on, gravity on. Camera orientation is owned by a
 * keyboard look state (J/L yaw, I/K pitch — frame-rate independent, pitch
 * clamped, no roll); WASD sets the desired HORIZONTAL velocity from that
 * yaw ONLY, so pitching up/down never flies or digs. Vertical velocity is
 * left to physics; with no input the horizontal velocity is zeroed every
 * frame, so the player stays practically stationary on the 12 % ramp.
 * Per-frame state lives in refs — no React/Zustand updates per frame.
 */
export function WalkthroughPlayer({
  config,
  spawn,
  keyState,
  resetSignal,
}: {
  config: WalkthroughConfig
  spawn: WalkthroughSpawn
  keyState: KeyState
  resetSignal: { current: number }
}) {
  const body = useRef<RapierRigidBody>(null)
  const camera = useThree((s) => s.camera)
  const appliedReset = useRef(-1)
  const look = useRef<LookState>({ yaw: spawn.yaw, pitch: 0 })

  // initial camera pose: spawn yaw, pitch 0 (rule 102)
  useEffect(() => {
    look.current = { yaw: spawn.yaw, pitch: 0 }
    camera.rotation.order = 'YXZ'
    camera.rotation.set(0, spawn.yaw, 0)
  }, [camera, spawn])

  useFrame((_, delta) => {
    const rb = body.current
    if (!rb) return
    // R reset: the only deliberate teleport (rule 101/§19)
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
    }
    // keyboard look: dt-scaled yaw/pitch, no roll (§3)
    look.current = applyLook(look.current, keyState.look, delta, config)
    camera.rotation.order = 'YXZ'
    camera.rotation.set(look.current.pitch, look.current.yaw, 0)
    // walking from yaw ONLY — pitch never contributes to translation (§4)
    const [vx, vz] = desiredHorizontalVelocity(keyState.keys, look.current.yaw, config.walkSpeedMps)
    const lv = rb.linvel()
    rb.setLinvel({ x: vx, y: lv.y, z: vz }, true)
    const t = rb.translation()
    camera.position.set(t.x, t.y + eyeOffsetFromBodyCenter(config), t.z)
  })

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
    >
      <CapsuleCollider args={[capsuleHalfHeight(config), config.bodyRadiusM]} />
    </RigidBody>
  )
}
