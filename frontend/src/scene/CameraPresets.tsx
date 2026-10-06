import { useThree } from '@react-three/fiber'
import { useEffect, useRef } from 'react'
import { mineToThree } from '@/geometry/coordinateTransform'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useViewerStore } from '@/stores/viewerStore'

/**
 * Hardening H1 §4.2 — camera presets of the View panel, applied inside the
 * Canvas. Iso / Top aim at the orebody centre; Fit frames the world extent.
 * Positions are built in mine coordinates and converted once at this
 * rendering boundary. The OrbitControls target is handed back through
 * `onTarget` so the controller and the readout stay in sync.
 */
export function CameraPresets({
  onTarget,
}: {
  onTarget: (target: [number, number, number]) => void
}) {
  const camera = useThree((s) => s.camera)
  const preset = useViewerStore((s) => s.cameraPreset)
  const scenario = useScenarioStore((s) => s.scenario)
  const scene = useScenarioStore((s) => s.scene)
  const applied = useRef(0)
  useEffect(() => {
    if (preset.nonce === applied.current) return
    applied.current = preset.nonce
    const baseZ = scenario?.terrain.baseElevation ?? 300
    const centre: [number, number, number] = scene
      ? scene.orebody.center
      : [0, 0, baseZ - (scenario?.world.depth ?? 400) / 2]
    const sizeX = scene?.world.sizeX ?? scenario?.world.sizeX ?? 2000
    const sizeY = scene?.world.sizeY ?? scenario?.world.sizeY ?? 2000
    const extent = Math.max(sizeX, sizeY)
    let eye: [number, number, number]
    let target: [number, number, number] = centre
    switch (preset.kind) {
      case 'TOP':
        eye = [centre[0], centre[1] - 1, baseZ + extent * 0.9]
        break
      case 'FIT':
        target = [0, 0, baseZ - (scenario?.world.depth ?? 400) / 2]
        eye = [-extent * 0.9, -extent * 1.1, baseZ + extent * 0.7]
        break
      default:
        eye = [centre[0] - 900, centre[1] - 1100, baseZ + 700]
    }
    camera.position.set(...mineToThree(...eye))
    camera.lookAt(...mineToThree(...target))
    camera.updateProjectionMatrix()
    onTarget(mineToThree(...target))
  }, [preset, camera, scenario, scene, onTarget])
  return null
}
