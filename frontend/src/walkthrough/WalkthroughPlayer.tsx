import { useEffect, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { CapsuleCollider, RigidBody, type RapierRigidBody } from '@react-three/rapier'
import { Euler } from 'three'
import { capsuleHalfHeight, eyeOffsetFromBodyCenter, type WalkthroughConfig } from './config'
import { desiredHorizontalVelocity, type KeyState } from './movement'
import type { WalkthroughSpawn } from './spawn'

const YAW_EULER = new Euler(0, 0, 0, 'YXZ')

/** Camera yaw under the pointer-lock YXZ convention (pure extraction). */
function cameraYaw(quaternion: { x: number; y: number; z: number; w: number }): number {
  YAW_EULER.setFromQuaternion(quaternion as never, 'YXZ')
  return YAW_EULER.y
}

/**
 * Upright collision-constrained player (rule 101): dynamic Rapier capsule,
 * rotations locked, CCD on, gravity on. WASD sets the desired HORIZONTAL
 * velocity from camera yaw only (pitch never flies); vertical velocity is
 * left to physics. With no input the horizontal velocity is zeroed every
 * frame, so the player stays practically stationary on the 12 % ramp.
 * Per-frame state lives in refs — no React/Zustand updates per frame.
 */
export function WalkthroughPlayer({
  config,
  spawn,
  keyState,
  lockedRef,
  resetSignal,
}: {
  config: WalkthroughConfig
  spawn: WalkthroughSpawn
  keyState: KeyState
  lockedRef: { current: boolean }
  resetSignal: { current: number }
}) {
  const body = useRef<RapierRigidBody>(null)
  const camera = useThree((s) => s.camera)
  const appliedReset = useRef(-1)

  // initial camera pose: spawn yaw, pitch 0 (rule 102)
  useEffect(() => {
    camera.rotation.order = 'YXZ'
    camera.rotation.set(0, spawn.yaw, 0)
  }, [camera, spawn])

  useFrame(() => {
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
      camera.rotation.order = 'YXZ'
      camera.rotation.set(0, spawn.yaw, 0)
    }
    // keyboard movement is inert whenever pointer lock is not active (§10)
    if (!lockedRef.current) keyState.clear()
    const [vx, vz] = desiredHorizontalVelocity(
      keyState.keys,
      cameraYaw(camera.quaternion),
      config.walkSpeedMps,
    )
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
