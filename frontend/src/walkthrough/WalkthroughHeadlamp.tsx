import { useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { Object3D, SpotLight, Vector3 } from 'three'
import type { WalkthroughConfig } from './config'

const FORWARD = new Vector3()

/**
 * Camera-following headlamp: a plain runtime spot light so the walker can
 * perceive floor, walls, roof and curvature. No shadows, no lighting
 * simulation, mode-scoped only.
 */
export function WalkthroughHeadlamp({ config }: { config: WalkthroughConfig }) {
  const light = useRef<SpotLight>(null)
  const target = useMemo(() => new Object3D(), [])
  const camera = useThree((s) => s.camera)
  useFrame(() => {
    const l = light.current
    if (!l) return
    l.position.copy(camera.position)
    camera.getWorldDirection(FORWARD)
    target.position.copy(camera.position).addScaledVector(FORWARD, 10)
  })
  return (
    <>
      <primitive object={target} />
      <spotLight
        ref={light}
        target={target}
        intensity={260}
        distance={config.headlampRangeM}
        angle={0.55}
        penumbra={0.45}
        decay={1.4}
        color="#f4ead2"
      />
    </>
  )
}
