/**
 * Phase 20B.2-F progressive excavation reveal (visualization only).
 *
 * 4D playback reveals the ACTUAL backend excavation meshes instead of only
 * growing centerlines: every SEGMENT primitive of the Phase 06 ramp GLB and
 * every piece range of the Phase 20B development GLB is emitted ring
 * interval by ring interval in chainage order, and the backend stamps each
 * SEGMENT primitive with ``indexStride`` (indices per ring interval),
 * ``ringIntervalCount`` and ``ringChainageFractions`` (0 → 1 per ring). A
 * DEVELOPING excavation is therefore rendered as the index PREFIX of its
 * last COMPLETED ring for the Phase 10 progress fraction — a shared-buffer
 * draw range / group, never regenerated geometry (rules 31, 86).
 *
 * Mapping is timeline-authoritative and fails CLOSED per development
 * (rule 117 analogue): a development whose geometryRef does not resolve to
 * exactly one mesh range keeps the existing centerline rendering.
 */
import { stateAt, developmentProgress, progressDirectionOf } from '@/timeline/evaluate'
import { rampOwningArtifact } from '@/walkthrough/temporalPlan'
import {
  rampSegmentId,
  type DevelopmentTimeline,
  type LevelAccessesPayload,
  type LevelsPayload,
  type SmoothedDeclinePayload,
  type TimelinePayload,
} from '@/types/scene'

export const LEVEL_ACCESSES_ARTIFACT = 'level_accesses.json'
export const LEVELS_ARTIFACT = 'levels.json'

/** SEGMENT primitive reveal metadata as stamped by the backend. */
export interface RevealMeta {
  indexStride: number
  ringIntervalCount: number
  ringChainageFractions: number[]
  /**
   * Phase 20D.1: exact index prefix sums per ring interval
   * (`ringIntervalCount + 1` entries, `[0, …, total]`). A typed junction
   * aperture omits quads from some intervals, so `m × indexStride` is no
   * longer the index count of the first `m` intervals; the backend stamps
   * the true offsets and the viewer cuts at them. Absent on pre-20D.1 GLBs,
   * whose intervals are uniform — the stride arithmetic stays exact there.
   */
  ringIntervalIndexOffsets?: number[]
}

/** Index count of the first `m` ring intervals (offset table or stride). */
export function intervalPrefixCount(meta: RevealMeta, m: number): number {
  const offsets = meta.ringIntervalIndexOffsets
  return offsets ? offsets[m]! : m * meta.indexStride
}

/** Read and validate the reveal metadata from a primitive's extras
 * (three.js GLTFLoader puts primitive extras on geometry.userData).
 * `indexCount`, when known (the primitive's index count or the batched
 * range's `indexCount`), must equal the total the table describes —
 * `offsets[count]` or `ringIntervalCount × indexStride` — otherwise the
 * metadata is rejected whole (fail closed, the edge keeps its centerline). */
export function readRevealMeta(extras: unknown, indexCount?: number): RevealMeta | null {
  if (!extras || typeof extras !== 'object') return null
  const e = extras as Record<string, unknown>
  const stride = e.indexStride
  const count = e.ringIntervalCount
  const fr = e.ringChainageFractions
  if (!Number.isInteger(stride) || (stride as number) <= 0) return null
  if (!Number.isInteger(count) || (count as number) <= 0) return null
  if (!Array.isArray(fr) || fr.length !== (count as number) + 1) return null
  let prev = -1
  for (const v of fr) {
    if (typeof v !== 'number' || !Number.isFinite(v) || v <= prev) return null
    prev = v
  }
  if (fr[0] !== 0 || fr[fr.length - 1] !== 1) return null
  const offsets = e.ringIntervalIndexOffsets
  if (offsets === undefined) {
    if (indexCount !== undefined && (count as number) * (stride as number) !== indexCount) {
      return null
    }
    return {
      indexStride: stride as number,
      ringIntervalCount: count as number,
      ringChainageFractions: fr as number[],
    }
  }
  // 20D.1 offsets, when present, must be a consistent prefix-sum table:
  // integers, starting at 0, non-decreasing, never more than one stride per
  // interval — anything else is rejected whole (fail closed, 20B.3-1.3)
  if (!Array.isArray(offsets) || offsets.length !== (count as number) + 1) return null
  const table: unknown[] = offsets
  let last = 0
  for (let i = 0; i < table.length; i += 1) {
    const v: unknown = table[i]
    if (!Number.isInteger(v) || (v as number) < 0) return null
    if (i === 0 && v !== 0) return null
    if (i > 0 && ((v as number) < last || (v as number) - last > (stride as number))) return null
    last = v as number
  }
  // the table must account for every emitted index (20D.1 review)
  if (indexCount !== undefined && last !== indexCount) return null
  return {
    indexStride: stride as number,
    ringIntervalCount: count as number,
    ringChainageFractions: fr as number[],
    ringIntervalIndexOffsets: offsets as number[],
  }
}

/** Index count revealed at chainage `progress`: the whole prefix of ring
 * intervals whose END ring lies at or before the progress fraction
 * (conservative — never a vertex beyond the excavated chainage). */
export function revealedIndexCount(meta: RevealMeta, progress: number): number {
  if (!(progress > 0)) return 0
  if (progress >= 1) return intervalPrefixCount(meta, meta.ringIntervalCount)
  let m = 0
  const fr = meta.ringChainageFractions
  while (m < meta.ringIntervalCount && fr[m + 1]! <= progress) m += 1
  return intervalPrefixCount(meta, m)
}

export type RevealTarget =
  { kind: 'RAMP'; segmentId: string } | { kind: 'DEVELOPMENT'; pieceId: string }

export interface DevelopmentReveal {
  edgeId: string
  edgeType: string
  target: RevealTarget
  /** chainage fraction to reveal: 0 NOT_BUILT, (0,1) DEVELOPING, 1 built */
  progress: number
  /** Phase 20C.1-V (rule 174): +1 reveals the index PREFIX (excavation starts
   * at the first point), −1 the index SUFFIX (starts at the last point) */
  direction: 1 | -1
}

/** Revealed index window of one segment / piece for a progress fraction and
 * direction: +1 → the first `m` complete intervals ([0, m·stride]); −1 → the
 * last `m` complete intervals counted from the END ring. Conservative in
 * both directions (only COMPLETED rings). */
export function revealedIndexRange(
  meta: RevealMeta,
  progress: number,
  direction: 1 | -1,
): { start: number; count: number } {
  const n = meta.ringIntervalCount
  const total = intervalPrefixCount(meta, n)
  if (!(progress > 0)) return { start: 0, count: 0 }
  if (progress >= 1) return { start: 0, count: total }
  const fr = meta.ringChainageFractions
  if (direction === 1) {
    let m = 0
    while (m < n && fr[m + 1]! <= progress) m += 1
    return { start: 0, count: intervalPrefixCount(meta, m) }
  }
  // interval i spans [fr[i], fr[i+1]]; from the end, interval i is complete
  // once fr[i] >= 1 − progress; the suffix starts at the prefix sum of the
  // first n − m intervals (exact under a 20D.1 offset table)
  let m = 0
  while (m < n && fr[n - 1 - m]! >= 1 - progress) m += 1
  const start = intervalPrefixCount(meta, n - m)
  return { start, count: total - start }
}

export interface ExcavationRevealPlan {
  reveals: DevelopmentReveal[]
  /** edgeIds whose geometryRef did not resolve to a mesh identity — they keep
   * the centerline rendering (fail closed, never guessed) */
  unmappedEdgeIds: string[]
}

function revealProgress(dev: DevelopmentTimeline, day: number): number {
  const state = stateAt(dev.initialState, dev.transitions, day)
  if (state === 'NOT_BUILT') return 0
  if (state === 'DEVELOPING') return developmentProgress(dev, day)
  return 1
}

/**
 * Resolve every timeline development to its mesh identity for `day`:
 * RAMP → the Phase 06 SEGMENT primitive `segmentId` (rule 113 mapping),
 * LEVEL_ACCESS → development-mesh piece `LEVEL_ACCESS:<levelId>`,
 * DRIFT / CROSSCUT → the levels.json development id (the development-mesh
 * `pieceId`). Each geometryRef is checked against its OWNING artifact.
 */
export function resolveExcavationReveal(
  timeline: TimelinePayload,
  smoothed: SmoothedDeclinePayload | null | undefined,
  levels: LevelsPayload | null | undefined,
  levelAccesses: LevelAccessesPayload | null | undefined,
  day: number,
): ExcavationRevealPlan {
  const reveals: DevelopmentReveal[] = []
  const unmapped: string[] = []
  const owner = smoothed ? rampOwningArtifact(smoothed) : null
  const seen = new Set<string>()
  for (const dev of timeline.developments) {
    const ref = dev.geometryRef
    const i = ref.segmentIndex
    let target: RevealTarget | null = null
    if (Number.isInteger(i) && i >= 0) {
      if (ref.artifact === owner && smoothed) {
        const seg = smoothed.segments[i]
        if (seg) {
          const id = rampSegmentId(seg)
          if (id) target = { kind: 'RAMP', segmentId: id }
        }
      } else if (ref.artifact === LEVEL_ACCESSES_ARTIFACT) {
        const a = levelAccesses?.accesses[i]
        if (a && a.status === 'OK' && a.levelId) {
          target = { kind: 'DEVELOPMENT', pieceId: `LEVEL_ACCESS:${a.levelId}` }
        }
      } else if (ref.artifact === LEVELS_ARTIFACT) {
        const d = levels?.developments[i]
        if (d && d.id) target = { kind: 'DEVELOPMENT', pieceId: d.id }
      }
    }
    const key = target
      ? `${target.kind}:${'segmentId' in target ? target.segmentId : target.pieceId}`
      : null
    if (!target || !key || seen.has(key)) {
      unmapped.push(dev.edgeId)
      continue
    }
    seen.add(key)
    reveals.push({
      edgeId: dev.edgeId,
      edgeType: dev.edgeType,
      target,
      progress: revealProgress(dev, day),
      direction: progressDirectionOf(dev),
    })
  }
  return { reveals, unmappedEdgeIds: unmapped }
}

/** One batched development-mesh piece range (GLB primitive `ranges` extras). */
export interface PieceRange {
  pieceId: string
  developmentId: string
  indexOffset: number
  indexCount: number
  meta: RevealMeta | null
}

export interface IndexGroup {
  start: number
  count: number
}

/**
 * Draw groups for a batched primitive: each piece contributes the revealed
 * PREFIX of its own index range; consecutive fully-revealed ranges coalesce
 * into one group so draw calls stay near the number of active headings, not
 * the number of pieces. Ranges are visited in buffer order. A range without
 * reveal metadata is skipped entirely (20B.3-1.3 fail-closed).
 */
export interface PieceProgress {
  progress: number
  /** rule 174 progress direction along the piece's ring order */
  direction: 1 | -1
}

export function planIndexGroups(
  ranges: readonly PieceRange[],
  progressByPiece: ReadonlyMap<string, number | PieceProgress>,
): IndexGroup[] {
  const sorted = [...ranges].sort((a, b) => a.indexOffset - b.indexOffset)
  const groups: IndexGroup[] = []
  for (const r of sorted) {
    const raw = progressByPiece.get(r.pieceId)
    const p = typeof raw === 'number' ? raw : raw?.progress
    const direction: 1 | -1 = typeof raw === 'object' && raw !== null ? raw.direction : 1
    if (p === undefined || !(p > 0)) continue
    // 20B.3-1.3: no metadata → never revealed (the edge is not covered, so
    // its centerline fallback keeps rendering instead)
    if (r.meta === null) continue
    const win =
      p >= 1 ? { start: 0, count: r.indexCount } : revealedIndexRange(r.meta, p, direction)
    const count = Math.min(r.indexCount - win.start, win.count)
    if (count <= 0) continue
    const start = r.indexOffset + win.start
    const last = groups[groups.length - 1]
    if (last && last.start + last.count === start) last.count += count
    else groups.push({ start, count })
  }
  return groups
}

/** Read the batched primitive `ranges` extras (development mesh GLB). */
export function readPieceRanges(
  extras: unknown,
  meta: (pieceId: string, indexCount: number) => RevealMeta | null,
): PieceRange[] {
  if (!extras || typeof extras !== 'object') return []
  const raw = (extras as { ranges?: unknown }).ranges
  if (!Array.isArray(raw)) return []
  const out: PieceRange[] = []
  for (const r of raw) {
    if (!r || typeof r !== 'object') return []
    const o = r as Record<string, unknown>
    if (
      typeof o.pieceId !== 'string' ||
      typeof o.developmentId !== 'string' ||
      !Number.isInteger(o.indexOffset) ||
      !Number.isInteger(o.indexCount) ||
      (o.indexOffset as number) < 0 ||
      (o.indexCount as number) <= 0
    ) {
      return []
    }
    out.push({
      pieceId: o.pieceId,
      developmentId: o.developmentId,
      indexOffset: o.indexOffset as number,
      indexCount: o.indexCount as number,
      meta: meta(o.pieceId, o.indexCount as number),
    })
  }
  return out
}

/**
 * Phase 20B.3-1.2: which 4D excavation layers mount for a layer-toggle
 * state. The ramp reveal is bound to the `tunnelMesh` toggle and the
 * development reveal to the `developmentMesh` toggle INDEPENDENTLY — turning
 * one off never disables the other's progressive reveal. Pure; the scene
 * evaluates it and mounts accordingly.
 */
export interface ExcavationMountPlan {
  /** the Phase 06 ramp GLB is shown progressively */
  ramp: boolean
  /** the Phase 20B development GLB is shown progressively */
  development: boolean
  /** the temporal excavation layer mounts at all */
  mounted: boolean
}

export function excavationMountPlan(input: {
  timelineActive: boolean
  hasSmoothed: boolean
  rampMeshAvailable: boolean
  developmentMeshAvailable: boolean
  tunnelMeshVisible: boolean
  developmentMeshVisible: boolean
}): ExcavationMountPlan {
  const base = input.timelineActive && input.hasSmoothed
  const ramp = base && input.rampMeshAvailable && input.tunnelMeshVisible
  const development = base && input.developmentMeshAvailable && input.developmentMeshVisible
  return { ramp, development, mounted: ramp || development }
}

/**
 * Phase 20B.3-1.3: the edge ids a reveal plan actually COVERS with a mesh.
 * Covered means the development resolved to a mesh identity that carries
 * VALID reveal metadata; a segment / piece without metadata (an older GLB,
 * malformed extras) is never covered — its mesh stays hidden and the
 * centerline fallback keeps rendering, so nothing silently disappears.
 */
export function coveredEdgeIds(
  reveals: readonly DevelopmentReveal[],
  rampMetaBySegment: ReadonlyMap<string, RevealMeta | null>,
  pieceMetaByPiece: ReadonlyMap<string, RevealMeta | null>,
): string[] {
  const out: string[] = []
  for (const r of reveals) {
    const meta =
      r.target.kind === 'RAMP'
        ? rampMetaBySegment.get(r.target.segmentId)
        : pieceMetaByPiece.get(r.target.pieceId)
    if (meta) out.push(r.edgeId)
  }
  return out
}
