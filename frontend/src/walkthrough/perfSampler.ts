/**
 * Bounded DEV performance sampler (hotfix §14, split out per Phase 16 §54
 * so the component file exports only a component). ~2 Hz, epsilon-safe,
 * never per React frame, never through Zustand.
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
