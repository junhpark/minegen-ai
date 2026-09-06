import { useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { Object3D, PointLight, SpotLight, Vector3 } from 'three'
import type { WalkthroughConfig } from './config'

const FORWARD = new Vector3()

/**
 * Walkthrough lighting rig (hotfix §9–10): navigation visualization, not
 * illumination engineering. The browser test showed a single narrow
 * high-intensity spot producing a circular "tunnel vision" hotspot with
 * black periphery — replaced by (a) a broad camera-following point fill
 * so floor/walls/roof around the player stay readable in every direction,
 * plus (b) a WIDE, soft, moderate forward beam for depth cueing. No
 * shadows, no postprocessing.
 */
export function WalkthroughHeadlamp({ config }: { config: WalkthroughConfig }) {
  const fill = useRef<PointLight>(null)
  const beam = useRef<SpotLight>(null)
  const target = useMemo(() => new Object3D(), [])
  const camera = useThree((s) => s.camera)
  useFrame(() => {
    camera.getWorldDirection(FORWARD)
    if (fill.current) fill.current.position.copy(camera.position)
    if (beam.current) beam.current.position.copy(camera.position)
    target.position.copy(camera.position).addScaledVector(FORWARD, 12)
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
