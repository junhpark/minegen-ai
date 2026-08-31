/**
 * Deterministic procedural rock/joint surface (§20–24): VISUAL ONLY — not
 * mapped discontinuities, not DFN, not RMR joint condition, not geological
 * structure. The Phase 06 GLB owns stable UVs (u = perimeter fraction with
 * the FLOOR spanning u ∈ [0.72, 1.0]; v = 3D chainage in metres), so one
 * small seamless canvas texture is generated frontend-side from
 * scenario.seed and shared by every tunnel primitive: same scenario, same
 * appearance; zero image assets; one texture, no extra draw calls.
 */

/** deterministic 32-bit PRNG (mulberry32) */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export interface JointFamilySpec {
  /** apparent trace orientation on the unwrapped surface, deg */
  angleDeg: number
  /** mean spacing between traces, px on the 512 canvas */
  spacingPx: number
  /** per-trace jitter fraction of spacing */
  jitter: number
  /** darkening strength 0..1 */
  strength: number
}

export interface RockTextureSpec {
  seed: number
  sizePx: number
  /** dark grey-brown base, css color */
  baseColor: string
  /** low-frequency mottle blob count + amplitude */
  mottleBlobs: number
  mottleStrength: number
  /** 2–3 apparent joint orientations with irregular spacing (§21) */
  jointFamilies: JointFamilySpec[]
  /** floor darkening band in u-space (perimeter fraction) */
  floorBandU: [number, number]
  floorDarken: number
}

export function rockTextureSpec(seed: number): RockTextureSpec {
  const rng = mulberry32(Math.floor(seed) || 1)
  const familyCount = 2 + (rng() < 0.55 ? 1 : 0)
  const jointFamilies: JointFamilySpec[] = []
  let angle = rng() * 60 - 70 // first family steep-ish
  for (let i = 0; i < familyCount; i++) {
    jointFamilies.push({
      angleDeg: angle,
      spacingPx: 46 + rng() * 60,
      jitter: 0.35 + rng() * 0.3,
      strength: 0.16 + rng() * 0.12,
    })
    angle += 45 + rng() * 55 // clearly distinct orientations
  }
  return {
    seed: Math.floor(seed) || 1,
    sizePx: 512,
    baseColor: '#6d6459',
    mottleBlobs: 130,
    mottleStrength: 0.16,
    jointFamilies,
    floorBandU: [0.72, 1.0],
    floorDarken: 0.12,
  }
}

/**
 * Paint the spec onto a canvas. Deterministic for a given spec (all
 * randomness flows through the seeded PRNG). Not pixel-unit-tested; the
 * spec generator above is the tested contract (§40).
 */
export function paintRockTexture(
  ctx: {
    fillStyle: string | CanvasGradient | CanvasPattern
    strokeStyle: string | CanvasGradient | CanvasPattern
    lineWidth: number
    globalAlpha: number
    fillRect: (x: number, y: number, w: number, h: number) => void
    beginPath: () => void
    arc: (x: number, y: number, r: number, a0: number, a1: number) => void
    fill: () => void
    moveTo: (x: number, y: number) => void
    lineTo: (x: number, y: number) => void
    stroke: () => void
  },
  spec: RockTextureSpec,
): void {
  const S = spec.sizePx
  const rng = mulberry32(spec.seed * 2654435761)
  ctx.globalAlpha = 1
  ctx.fillStyle = spec.baseColor
  ctx.fillRect(0, 0, S, S)
  // low-frequency mottling: large soft blobs, drawn wrapped for seamlessness
  for (let i = 0; i < spec.mottleBlobs; i++) {
    const x = rng() * S
    const y = rng() * S
    const r = S * (0.06 + rng() * 0.16)
    const dark = rng() < 0.5
    ctx.globalAlpha = spec.mottleStrength * (0.35 + rng() * 0.65)
    ctx.fillStyle = dark ? '#4c453d' : '#7d7466'
    for (const ox of [-S, 0, S]) {
      for (const oy of [-S, 0, S]) {
        ctx.beginPath()
        ctx.arc(x + ox, y + oy, r, 0, Math.PI * 2)
        ctx.fill()
      }
    }
  }
  // joint/fracture traces: dark thin lines per family, irregular spacing,
  // drawn across the tile with wrap copies (never bright, never brick-like)
  for (const fam of spec.jointFamilies) {
    const rad = (fam.angleDeg * Math.PI) / 180
    const dx = Math.cos(rad)
    const dy = Math.sin(rad)
    const nx = -dy
    const ny = dx
    let offset = -S
    while (offset < S * 2) {
      offset += fam.spacingPx * (1 - fam.jitter + rng() * fam.jitter * 2)
      const cx = S / 2 + nx * (offset - S / 2)
      const cy = S / 2 + ny * (offset - S / 2)
      ctx.globalAlpha = fam.strength * (0.6 + rng() * 0.4)
      ctx.strokeStyle = '#3a342d'
      ctx.lineWidth = 0.8 + rng() * 1.2
      for (const ox of [-S, 0, S]) {
        for (const oy of [-S, 0, S]) {
          ctx.beginPath()
          ctx.moveTo(cx - dx * S * 1.6 + ox, cy - dy * S * 1.6 + oy)
          // slight per-trace waviness via one midpoint kink
          ctx.lineTo(cx + (rng() - 0.5) * 14 + ox, cy + (rng() - 0.5) * 14 + oy)
          ctx.lineTo(cx + dx * S * 1.6 + ox, cy + dy * S * 1.6 + oy)
          ctx.stroke()
        }
      }
    }
  }
  // floor readability (§24): subtle darker response across the floor
  // u-band; u maps to the texture x axis
  ctx.globalAlpha = spec.floorDarken
  ctx.fillStyle = '#2f2a24'
  const x0 = spec.floorBandU[0] * S
  ctx.fillRect(x0, 0, (spec.floorBandU[1] - spec.floorBandU[0]) * S, S)
  ctx.globalAlpha = 1
}
