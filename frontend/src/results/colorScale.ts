/**
 * Phase 23C — metric colour mapping for the overlays. A sequential ramp over
 * the DISPLAY range (auto = the frame's min / max, or the user's manual
 * range); values outside the range clamp to the ends; a MISSING value is
 * never coloured as zero — it keeps the neutral tone.
 */

export const NEUTRAL_COLOR = '#5a6470'

/** viridis-like stops (t = 0 … 1) */
const STOPS: [number, [number, number, number]][] = [
  [0.0, [0.267, 0.005, 0.329]],
  [0.25, [0.229, 0.322, 0.545]],
  [0.5, [0.127, 0.567, 0.551]],
  [0.75, [0.369, 0.789, 0.383]],
  [1.0, [0.993, 0.906, 0.144]],
]

export interface DisplayRange {
  min: number
  max: number
}

/** The range colours are mapped over: the manual range when set, else the
 * frame extent; a degenerate extent widens symmetrically so one value is
 * still colourable. */
export function displayRange(
  frameMin: number | null,
  frameMax: number | null,
  manual: DisplayRange | null,
): DisplayRange | null {
  if (manual && Number.isFinite(manual.min) && Number.isFinite(manual.max)) {
    return manual.min <= manual.max ? manual : { min: manual.max, max: manual.min }
  }
  if (frameMin === null || frameMax === null) return null
  if (frameMin === frameMax) {
    const pad = Math.abs(frameMin) > 0 ? Math.abs(frameMin) * 0.05 : 0.5
    return { min: frameMin - pad, max: frameMax + pad }
  }
  return { min: frameMin, max: frameMax }
}

export function rampRgb(t: number): [number, number, number] {
  const x = Math.min(1, Math.max(0, t))
  for (let i = 1; i < STOPS.length; i++) {
    const [t1, c1] = STOPS[i] as [number, [number, number, number]]
    if (x <= t1) {
      const [t0, c0] = STOPS[i - 1] as [number, [number, number, number]]
      const u = t1 === t0 ? 0 : (x - t0) / (t1 - t0)
      return [c0[0] + u * (c1[0] - c0[0]), c0[1] + u * (c1[1] - c0[1]), c0[2] + u * (c1[2] - c0[2])]
    }
  }
  const last = STOPS[STOPS.length - 1] as [number, [number, number, number]]
  return last[1]
}

export function valueRgb(value: number, range: DisplayRange): [number, number, number] {
  const span = range.max - range.min
  return rampRgb(span <= 0 ? 0.5 : (value - range.min) / span)
}

export function rgbToHex(rgb: [number, number, number]): string {
  const c = (v: number) =>
    Math.round(Math.min(1, Math.max(0, v)) * 255)
      .toString(16)
      .padStart(2, '0')
  return `#${c(rgb[0])}${c(rgb[1])}${c(rgb[2])}`
}

/** Legend ticks (min … max), five evenly spaced values. */
export function legendTicks(range: DisplayRange, count = 5): number[] {
  const out: number[] = []
  for (let i = 0; i < count; i++) {
    out.push(range.min + ((range.max - range.min) * i) / (count - 1))
  }
  return out
}
