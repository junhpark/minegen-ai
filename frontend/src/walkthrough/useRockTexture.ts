import { useMemo } from 'react'
import { CanvasTexture, RepeatWrapping, SRGBColorSpace } from 'three'
import { useScenarioStore } from '@/stores/scenarioStore'
import { paintRockTexture, rockTextureSpec } from './rockTexture'

/** metres of tunnel chainage per texture tile along v */
export const ROCK_TILE_METERS = 8

/**
 * One shared deterministic rock CanvasTexture per scenario seed (§22–23):
 * u repeats once around the perimeter, v repeats every ROCK_TILE_METERS of
 * chainage (backend UV: u = perimeter fraction, v = chainage metres).
 * Returns null outside the DOM (tests) so callers can fall back cleanly.
 */
export function useRockTexture(): CanvasTexture | null {
  const seed = useScenarioStore((s) => s.scenario?.seed ?? 1)
  return useMemo(() => {
    if (typeof document === 'undefined') return null
    const spec = rockTextureSpec(seed)
    const canvas = document.createElement('canvas')
    canvas.width = spec.sizePx
    canvas.height = spec.sizePx
    const ctx = canvas.getContext('2d')
    if (!ctx) return null
    paintRockTexture(ctx, spec)
    const tex = new CanvasTexture(canvas)
    tex.wrapS = RepeatWrapping
    tex.wrapT = RepeatWrapping
    tex.repeat.set(1, 1 / ROCK_TILE_METERS)
    tex.colorSpace = SRGBColorSpace
    tex.anisotropy = 4
    return tex
  }, [seed])
}
