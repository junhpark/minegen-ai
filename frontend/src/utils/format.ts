/** Display helpers only. No engineering calculations here (CLAUDE.md rule 17). */

export function fmtMeters(v: number, digits = 1): string {
  return `${v.toFixed(digits)} m`
}

/** Total-station style coordinate readout: fixed width, one decimal. */
export function fmtCoord(v: number): string {
  const s = v.toFixed(1)
  return (v >= 0 ? '+' : '') + s
}

export function fmtPercent(fraction: number, digits = 1): string {
  return `${(fraction * 100).toFixed(digits)} %`
}
