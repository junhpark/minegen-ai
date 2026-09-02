import { useMemo } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { createPerfSampler } from './perfSampler'

/**
 * DEV-only walkthrough performance readout (hotfix §14): FPS, rendered
 * triangles and draw calls, written straight into a HUD DOM node at a
 * bounded ~2 Hz — never per React frame, never through Zustand, never
 * persisted, absent from production builds.
 */

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
