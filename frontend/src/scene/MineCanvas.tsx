import { Canvas } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import { useEffect, useState } from 'react'
import { MineScene } from './MineScene'
import { CoordinateReadout } from './CoordinateReadout'
import { mineToThree } from '@/geometry/coordinateTransform'
import { useScenarioStore } from '@/stores/scenarioStore'

/**
 * R3F canvas host. Camera positions are specified in mine coordinates and
 * converted once, here, at the rendering boundary.
 */
export function MineCanvas() {
  const scenario = useScenarioStore((s) => s.scenario)
  const scene = useScenarioStore((s) => s.scene)
  const baseZ = scenario?.terrain.baseElevation ?? 300
  const [target, setTarget] = useState<[number, number, number]>(mineToThree(0, 0, baseZ))

  // re-aim at the orebody when a world arrives
  useEffect(() => {
    if (scene) setTarget(mineToThree(...scene.orebody.center))
  }, [scene])

  return (
    <div className="relative h-full w-full bg-rock-950">
      <Canvas
        camera={{
          position: mineToThree(-900, -1100, baseZ + 700),
          fov: 45,
          near: 1,
          far: 20000,
        }}
        dpr={[1, 2]}
        gl={{ antialias: true }}
      >
        <color attach="background" args={['#0f1316']} />
        <MineScene />
        <OrbitControls
          makeDefault
          target={target}
          enableDamping
          dampingFactor={0.08}
          onChange={(e) => {
            const t = e?.target.target
            if (t) setTarget([t.x, t.y, t.z])
          }}
        />
      </Canvas>
      <CoordinateReadout threeTarget={target} />
    </div>
  )
}
