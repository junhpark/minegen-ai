/**
 * Display colormaps. Pure presentation: maps a normalized value to RGB.
 * No engineering thresholds live here (CLAUDE.md rule 17).
 */

export type RGB = [number, number, number]
type Stop = [number, RGB]

function ramp(stops: Stop[]): (t: number) => RGB {
  return (t: number) => {
    const x = Math.min(1, Math.max(0, Number.isFinite(t) ? t : 0))
    for (let i = 1; i < stops.length; i++) {
      const [t1, c1] = stops[i] as Stop
      if (x <= t1) {
        const [t0, c0] = stops[i - 1] as Stop
        const f = t1 === t0 ? 0 : (x - t0) / (t1 - t0)
        return [
          c0[0] + (c1[0] - c0[0]) * f,
          c0[1] + (c1[1] - c0[1]) * f,
          c0[2] + (c1[2] - c0[2]) * f,
        ]
      }
    }
    return (stops[stops.length - 1] as Stop)[1]
  }
}

/** poor → good rock: danger red → lamp amber → ore teal */
export const rockQualityRamp = ramp([
  [0, [0.85, 0.4, 0.35]],
  [0.5, [0.94, 0.72, 0.29]],
  [1, [0.31, 0.7, 0.65]],
])

/** low → high grade: rock slate → lamp amber → chalk white */
export const gradeRamp = ramp([
  [0, [0.17, 0.21, 0.24]],
  [0.55, [0.94, 0.72, 0.29]],
  [1, [0.95, 0.93, 0.88]],
])

/** 0 → 1 fault influence: transparent-ish slate → danger red */
export const faultInfluenceRamp = ramp([
  [0, [0.17, 0.21, 0.24]],
  [1, [0.85, 0.4, 0.35]],
])

/** elevation shading for terrain */
export const terrainRamp = ramp([
  [0, [0.2, 0.24, 0.27]],
  [1, [0.45, 0.48, 0.48]],
])

export const rampForField = (field: string): ((t: number) => RGB) => {
  switch (field) {
    case 'rockQuality':
      return rockQualityRamp
    case 'grade':
    case 'oreFraction':
      return gradeRamp
    case 'faultInfluence':
    case 'faultZone':
      return faultInfluenceRamp
    default:
      return gradeRamp
  }
}

export function normalize(v: number, min: number, max: number): number {
  return max > min ? (v - min) / (max - min) : 0
}
