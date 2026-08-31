import { useMemo } from 'react'
import { useFrame, useThree } from '@react-three/fiber'

/**
 * DEV-only walkthrough performance readout (hotfix §14): FPS, rendered
 * triangles and draw calls, written straight into a HUD DOM node at a
 * bounded ~2 Hz — never per React frame, never through Zustand, never
 * persisted, absent from production builds.
 */
export interface PerfSampler {
  sample: (deltaSeconds: number, triangles: number, calls: number) => string | null
}

export function createPerfSampler(intervalSeconds = 0.5): PerfSampler {
  let acc = 0
  let frames = 0
  return {
    sample(deltaSeconds, triangles, calls) {
      acc += deltaSeconds
      frames += 1
      if (acc + 1e-9 < intervalSeconds) return null
      const fps = frames / acc
      acc = 0
      frames = 0
      const tri = triangles >= 1000 ? `${(triangles / 1000).toFixed(0)}k` : String(triangles)
      return `FPS ${fps.toFixed(0)}\nTriangles ${tri}\nDraw calls ${calls}`
    },
  }
}

export function WalkthroughDiagnostics({
  targetRef,
}: {
  targetRef: { current: HTMLDivElement | null }
}) {
  const gl = useThree((s) => s.gl)
  const sampler = useMemo(() => createPerfSampler(0.5), [])
  useFrame((_, delta) => {
    if (!import.meta.env.DEV) return
    const line = sampler.sample(delta, gl.info.render.triangles, gl.info.render.calls)
    if (line !== null && targetRef.current) targetRef.current.textContent = line
  })
  return null
}
