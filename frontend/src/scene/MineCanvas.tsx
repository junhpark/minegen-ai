import { Canvas } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import { useCallback, useEffect, useState } from 'react'
import { MineScene } from './MineScene'
import { CoordinateReadout } from './CoordinateReadout'
import { mineToThree } from '@/geometry/coordinateTransform'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useViewerStore } from '@/stores/viewerStore'
import { walkthroughReadiness } from '@/walkthrough/readiness'
import { WALKTHROUGH_LOCK_SURFACE_ID } from '@/walkthrough/lockSurface'
import { WalkthroughHUD } from '@/walkthrough/WalkthroughHUD'
import { WalkthroughRuntime } from '@/walkthrough/WalkthroughRuntime'
import { API_BASE_URL } from '@/api/client'

/**
 * R3F canvas host. Camera positions are specified in mine coordinates and
 * converted once, here, at the rendering boundary.
 *
 * Camera-control ownership (§14): EXACTLY one controller is mounted —
 * OrbitControls in orbit camera mode, the walkthrough runtime in
 * walkthrough camera mode. They never coexist.
 */
export function MineCanvas() {
  const scenario = useScenarioStore((s) => s.scenario)
  const scene = useScenarioStore((s) => s.scene)
  const cameraMode = useViewerStore((s) => s.cameraMode)
  const mode = useViewerStore((s) => s.mode)
  const setMode = useViewerStore((s) => s.setMode)
  const baseZ = scenario?.terrain.baseElevation ?? 300
  const [target, setTarget] = useState<[number, number, number]>(mineToThree(0, 0, baseZ))
  const [locked, setLocked] = useState(false)

  // re-aim at the orebody when a world arrives
  useEffect(() => {
    if (scene) setTarget(mineToThree(...scene.orebody.center))
  }, [scene])

  // defensive gate (§13): if walkthrough prerequisites disappear while the
  // mode is active, release cleanly back to DESIGN/orbit — no crash
  const readiness = walkthroughReadiness(scene)
  useEffect(() => {
    if (mode === 'WALKTHROUGH' && readiness !== 'READY') {
      if (document.pointerLockElement) document.exitPointerLock()
      setMode('DESIGN')
    }
  }, [mode, readiness, setMode])
  useEffect(() => {
    if (cameraMode !== 'walkthrough') setLocked(false)
  }, [cameraMode])
  const leaveWalkthrough = useCallback(() => setMode('DESIGN'), [setMode])

  const walkable =
    cameraMode === 'walkthrough' &&
    readiness === 'READY' &&
    scene?.tunnelMesh?.meshUrl &&
    scene.smoothedDecline

  return (
    <div id={WALKTHROUGH_LOCK_SURFACE_ID} className="relative h-full w-full bg-rock-950">
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
        {walkable ? (
          <WalkthroughRuntime
            meshUrl={`${API_BASE_URL}${scene.tunnelMesh!.meshUrl}`}
            smoothed={scene.smoothedDecline!}
            onLockChange={setLocked}
            onGeometryError={leaveWalkthrough}
          />
        ) : cameraMode === 'orbit' ? (
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
        ) : null}
      </Canvas>
      {cameraMode === 'walkthrough' ? (
        <WalkthroughHUD locked={locked} />
      ) : (
        <CoordinateReadout threeTarget={target} />
      )}
    </div>
  )
}
