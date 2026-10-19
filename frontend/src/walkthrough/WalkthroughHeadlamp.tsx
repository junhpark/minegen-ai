import { useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { Object3D, PointLight, SpotLight, Vector3 } from 'three'
import type { WalkthroughConfig } from './config'

const FORWARD = new Vector3()

/**
 * Walkthrough lighting rig (hotfix §9–10, PR-4 third person): navigation
 * visualization, not illumination engineering. (a) A broad camera-following
 * point fill keeps floor / walls / roof around the camera readable in every
 * direction; (b) a WIDE, soft, moderate beam leaves the AVATAR's eye point
 * (the cap lamp / truck lights) along the camera forward so depth reads
 * ahead of the avatar. No shadows, no postprocessing.
 */
export function WalkthroughHeadlamp({
  config,
  eyeRef,
}: {
  config: WalkthroughConfig
  /** avatar eye point (Three coordinates); the camera when absent */
  eyeRef?: { current: Vector3 }
}) {
  const fill = useRef<PointLight>(null)
  const beam = useRef<SpotLight>(null)
  const target = useMemo(() => new Object3D(), [])
  const camera = useThree((s) => s.camera)
  useFrame(() => {
    camera.getWorldDirection(FORWARD)
    const eye = eyeRef?.current ?? camera.position
    if (fill.current) fill.current.position.copy(camera.position)
    if (beam.current) beam.current.position.copy(eye)
    target.position.copy(eye).addScaledVector(FORWARD, 12)
  })
  return (
    <>
      <primitive object={target} />
      {/* 20B.3: the shared tunnel material / rock texture were lightened for
          ORBIT readability; the walkthrough rig comes down by the same
          factor (fill 30 → 22, beam 70 → 52) so the Phase 15 "no
          overexposed beige" balance is preserved */}
      <pointLight ref={fill} intensity={22} distance={45} decay={1.15} color="#efe6d4" />
      <spotLight
        ref={beam}
        target={target}
        intensity={52}
        distance={config.headlampRangeM}
        angle={0.95}
        penumbra={0.9}
        decay={1.2}
        color="#f2e9d8"
      />
    </>
  )
}
