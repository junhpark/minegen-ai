/**
 * Level-aware minimap model (hardening PR-4 W3, Park: "미니맵은 반복되는
 * geometry에서 어색하다 — 레벨 구역에 들어오면 미니맵이 바뀌는 식으로").
 *
 * A spiral decline overlaps itself in plan, so one north-up map of the whole
 * ramp cannot say WHERE the avatar is. The map is therefore LEVEL-AWARE: the
 * avatar's RL picks the nearest required level inside half a level spacing
 * and the map shows THAT level's authoritative development — its drifts and
 * crosscuts (`levels.json`), its access branch (`level_accesses.json`), the
 * ramp samples inside the level's elevation band, and the level's nodes
 * (entry, turnout, stope accesses, shaft station from MineNetwork) — fitted
 * to the level's extent; between levels (or without levels) it shows the
 * ramp band around the avatar's RL. A LEVEL LADDER beside the map places the
 * RL among every level. In a TIMELINE_SNAPSHOT only the ACTIVE ramp prefix
 * and the ACTIVE development pieces are drawn (rule 114: the map never shows
 * what cannot be walked). Pure projection of backend-authored geometry — no
 * geometry is created, nothing is persisted (rule 99).
 */
import type { LevelAccessPayload, SmoothedDeclinePayload, WorldScene } from '@/types/scene'
import { rampSegmentId } from '@/types/scene'

export interface LevelRef {
  levelId: string
  elevation: number
}

/** Fallback half-band when a mine has fewer than two levels, m. */
export const DEFAULT_LEVEL_HALF_BAND_M = 12.5
/** The fitted map keeps at least this half-extent, m. */
export const MIN_MAP_HALF_EXTENT_M = 40
/** Padding around the fitted content as a fraction of the extent. */
export const MAP_PADDING_FRACTION = 0.1

type Scene = Pick<
  WorldScene,
  'levels' | 'levelAccesses' | 'network' | 'smoothedDecline' | 'layoutV2' | 'shafts'
>

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

/**
 * Every required level with its elevation, highest first — from the level
 * accesses (the selection's authority), else the layout catalogue's required
 * levels, else the Effective Ramp's level references / legacy segment ends.
 * Never invented: a mine without any of these has no levels.
 */
export function collectLevels(scene: Scene | null | undefined): LevelRef[] {
  const out = new Map<string, number>()
  const accesses = scene?.levelAccesses
  if (accesses && accesses.status === 'SUCCESS') {
    for (const a of accesses.accesses) if (finite(a.elevation)) out.set(a.levelId, a.elevation)
  }
  if (out.size === 0 && scene?.layoutV2) {
    for (const l of scene.layoutV2.requiredLevels ?? []) {
      if (finite(l.elevation)) out.set(l.levelId, l.elevation)
    }
  }
  const ramp = scene?.smoothedDecline
  if (out.size === 0 && ramp) {
    for (const r of ramp.rampLevelReferences ?? [])
      if (finite(r.elevation)) out.set(r.levelId, r.elevation)
    if (out.size === 0) {
      for (const seg of ramp.segments) {
        const pts = seg.effectiveCenterline?.points
        if (
          seg.levelId &&
          seg.terminalKind !== 'RAMP_END' &&
          Array.isArray(pts) &&
          pts.length >= 3
        ) {
          const z = pts[pts.length - 1]
          if (finite(z)) out.set(seg.levelId, z)
        }
      }
    }
  }
  return [...out.entries()]
    .map(([levelId, elevation]) => ({ levelId, elevation }))
    .sort((a, b) => b.elevation - a.elevation || a.levelId.localeCompare(b.levelId))
}

/** Half of the median spacing between consecutive levels (the level band). */
export function levelHalfBand(levels: readonly LevelRef[]): number {
  if (levels.length < 2) return DEFAULT_LEVEL_HALF_BAND_M
  const gaps = levels
    .slice(1)
    .map((l, i) => Math.abs(levels[i]!.elevation - l.elevation))
    .filter((g) => g > 0)
    .sort((a, b) => a - b)
  if (gaps.length === 0) return DEFAULT_LEVEL_HALF_BAND_M
  return gaps[Math.floor(gaps.length / 2)]! / 2
}

/** The level whose elevation is within `halfBand` of `rl` (nearest wins). */
export function pickLevel(
  rl: number,
  levels: readonly LevelRef[],
  halfBand: number,
): LevelRef | null {
  let best: LevelRef | null = null
  for (const l of levels) {
    const d = Math.abs(l.elevation - rl)
    if (d <= halfBand && (best === null || d < Math.abs(best.elevation - rl))) best = l
  }
  return best
}

export type MapLineKind = 'RAMP' | 'ACCESS' | 'DRIFT' | 'CROSSCUT'
export type MapMarkerKind = 'PORTAL' | 'TURNOUT' | 'ENTRY' | 'STOPE_ACCESS' | 'SHAFT_STATION'

export interface MapPolyline {
  id: string
  kind: MapLineKind
  /** mine-space XY pairs, metres */
  xy: number[]
}

export interface MapMarker {
  id: string
  kind: MapMarkerKind
  xy: [number, number]
}

export interface MapBounds {
  minX: number
  minY: number
  maxX: number
  maxY: number
}

export interface LevelMapModel {
  /** the level shown, or null for the ramp band between / without levels */
  level: LevelRef | null
  polylines: MapPolyline[]
  markers: MapMarker[]
  /** fitted content bounds (geometry only — the avatar never moves the map) */
  bounds: MapBounds
}

export interface LevelMapInput {
  scene: Scene | null | undefined
  level: LevelRef | null
  /** avatar RL, m (the ramp band centre when no level is shown) */
  rl: number
  halfBand: number
  /** TIMELINE_SNAPSHOT: the ACTIVE ramp prefix; null = every segment */
  activeRampSegmentIds: readonly string[] | null
  /** TIMELINE_SNAPSHOT: the ACTIVE development piece ids; null = every piece */
  activePieceIds: ReadonlySet<string> | null
}

function extend(b: MapBounds | null, x: number, y: number): MapBounds {
  if (!b) return { minX: x, minY: y, maxX: x, maxY: y }
  return {
    minX: Math.min(b.minX, x),
    minY: Math.min(b.minY, y),
    maxX: Math.max(b.maxX, x),
    maxY: Math.max(b.maxY, y),
  }
}

/** Ramp samples inside the elevation band, split into runs where they leave it. */
function rampBand(
  ramp: SmoothedDeclinePayload | null | undefined,
  zLo: number,
  zHi: number,
  active: ReadonlySet<string> | null,
): MapPolyline[] {
  const out: MapPolyline[] = []
  if (!ramp) return out
  let run: number[] = []
  let runIndex = 0
  const flush = () => {
    if (run.length >= 4) out.push({ id: `RAMP:${runIndex++}`, kind: 'RAMP', xy: run })
    run = []
  }
  for (const seg of ramp.segments) {
    if (active !== null && !active.has(rampSegmentId(seg))) break // ACTIVE prefix only
    const pts = seg.effectiveCenterline?.points
    if (!Array.isArray(pts)) continue
    for (let i = 0; i + 2 < pts.length; i += 3) {
      const z = pts[i + 2]!
      if (z >= zLo && z <= zHi) {
        const n = run.length
        // segments share their boundary point: never draw a zero-length chord
        if (n >= 2 && run[n - 2] === pts[i] && run[n - 1] === pts[i + 1]) continue
        run.push(pts[i]!, pts[i + 1]!)
      } else flush()
    }
  }
  flush()
  return out
}

function accessLine(a: LevelAccessPayload): MapPolyline | null {
  const pts = a.centerline?.points
  if (!Array.isArray(pts) || pts.length < 6) return null
  const xy: number[] = []
  for (let i = 0; i + 2 < pts.length; i += 3) xy.push(pts[i]!, pts[i + 1]!)
  return { id: `ACCESS:${a.levelId}`, kind: 'ACCESS', xy }
}

export function buildLevelMapModel(input: LevelMapInput): LevelMapModel {
  const { scene, level, rl, halfBand } = input
  const active = input.activeRampSegmentIds === null ? null : new Set(input.activeRampSegmentIds)
  const pieces = input.activePieceIds
  const polylines: MapPolyline[] = []
  const markers: MapMarker[] = []
  const centre = level ? level.elevation : rl
  polylines.push(...rampBand(scene?.smoothedDecline, centre - halfBand, centre + halfBand, active))
  if (level) {
    const levels = scene?.levels
    if (levels && levels.status === 'SUCCESS') {
      for (const d of levels.developments) {
        if (d.levelId !== level.levelId) continue
        if (pieces !== null && !pieces.has(d.id)) continue
        const pts = d.centerline.points
        const xy: number[] = []
        for (let i = 0; i + 2 < pts.length; i += 3) xy.push(pts[i]!, pts[i + 1]!)
        if (xy.length >= 4) polylines.push({ id: d.id, kind: d.kind, xy })
      }
    }
    const accesses = scene?.levelAccesses
    if (accesses && accesses.status === 'SUCCESS') {
      for (const a of accesses.accesses) {
        if (a.levelId !== level.levelId || a.status !== 'OK') continue
        if (pieces !== null && !pieces.has(`LEVEL_ACCESS:${a.levelId}`)) continue
        const line = accessLine(a)
        if (line) polylines.push(line)
      }
    }
    const network = scene?.network
    if (network && network.status === 'SUCCESS') {
      const present = new Set(polylines.map((p) => p.id))
      for (const n of network.nodes) {
        if (n.levelId !== level.levelId) continue
        const xy: [number, number] = [n.position[0], n.position[1]]
        if (n.type === 'RAMP_JUNCTION') markers.push({ id: n.id, kind: 'TURNOUT', xy })
        else if (
          n.type === 'LEVEL_ENTRY' &&
          (pieces === null || present.has(`ACCESS:${level.levelId}`))
        )
          markers.push({ id: n.id, kind: 'ENTRY', xy })
        else if (n.type === 'STOPE_ACCESS' && (pieces === null || presentCrosscut(present, n.id)))
          markers.push({ id: n.id, kind: 'STOPE_ACCESS', xy })
        else if (n.type === 'SHAFT_STATION') markers.push({ id: n.id, kind: 'SHAFT_STATION', xy })
      }
    }
  } else {
    const ramp = scene?.smoothedDecline
    const first = ramp?.segments[0]?.effectiveCenterline?.points
    if (
      Array.isArray(first) &&
      first.length >= 3 &&
      first[2]! >= centre - halfBand &&
      first[2]! <= centre + halfBand
    ) {
      markers.push({ id: 'PORTAL', kind: 'PORTAL', xy: [first[0]!, first[1]!] })
    }
  }
  let b: MapBounds | null = null
  for (const p of polylines)
    for (let i = 0; i + 1 < p.xy.length; i += 2) b = extend(b, p.xy[i]!, p.xy[i + 1]!)
  for (const m of markers) b = extend(b, m.xy[0], m.xy[1])
  if (!b)
    b = {
      minX: -MIN_MAP_HALF_EXTENT_M,
      minY: -MIN_MAP_HALF_EXTENT_M,
      maxX: MIN_MAP_HALF_EXTENT_M,
      maxY: MIN_MAP_HALF_EXTENT_M,
    }
  const cx = (b.minX + b.maxX) / 2
  const cy = (b.minY + b.maxY) / 2
  const half = Math.max(
    ((b.maxX - b.minX) / 2) * (1 + 2 * MAP_PADDING_FRACTION),
    ((b.maxY - b.minY) / 2) * (1 + 2 * MAP_PADDING_FRACTION),
    MIN_MAP_HALF_EXTENT_M,
  )
  return {
    level,
    polylines,
    markers,
    bounds: { minX: cx - half, minY: cy - half, maxX: cx + half, maxY: cy + half },
  }
}

/** a STOPE_ACCESS node `STOPE_ACCESS:<level>:S<k>` belongs to the crosscut
 * `CROSSCUT:<level>:S<k>` (the backend id grammar) */
function presentCrosscut(present: ReadonlySet<string>, nodeId: string): boolean {
  return present.has(nodeId.replace(/^STOPE_ACCESS:/, 'CROSSCUT:'))
}

/** Square map projection: mine XY → [0, 1]² with north UP (v grows downward). */
export function projectToMap(bounds: MapBounds, x: number, y: number): [number, number] {
  const w = bounds.maxX - bounds.minX
  const h = bounds.maxY - bounds.minY
  return [(x - bounds.minX) / w, (bounds.maxY - y) / h]
}

export interface LadderTick {
  levelId: string
  elevation: number
  /** 0 at the top (highest elevation shown), 1 at the bottom */
  t: number
}

export interface LadderModel {
  ticks: LadderTick[]
  zTop: number
  zBottom: number
  /** avatar position on the ladder, clamped to [0, 1] */
  avatarT: number
}

/** The level ladder: every level between the surface (the portal RL, when
 * known) and the deepest level, with the avatar's RL placed among them. */
export function buildLadderModel(
  levels: readonly LevelRef[],
  rl: number,
  surfaceRl: number | null,
): LadderModel | null {
  if (levels.length === 0) return null
  const zs = levels.map((l) => l.elevation)
  const zTop = surfaceRl !== null ? Math.max(surfaceRl, ...zs) : Math.max(...zs)
  const zBottom = Math.min(...zs)
  const span = Math.max(zTop - zBottom, 1e-6)
  const t = (z: number) => Math.min(1, Math.max(0, (zTop - z) / span))
  return {
    ticks: levels.map((l) => ({ levelId: l.levelId, elevation: l.elevation, t: t(l.elevation) })),
    zTop,
    zBottom,
    avatarT: t(rl),
  }
}

/** Portal RL of the Effective Ramp (its first centerline point), or null. */
export function portalRl(ramp: SmoothedDeclinePayload | null | undefined): number | null {
  const pts = ramp?.segments[0]?.effectiveCenterline?.points
  return Array.isArray(pts) && pts.length >= 3 && finite(pts[2]) ? pts[2] : null
}
