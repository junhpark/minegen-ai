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
}

/** Read and validate the reveal metadata from a primitive's extras
 * (three.js GLTFLoader puts primitive extras on geometry.userData). */
export function readRevealMeta(extras: unknown): RevealMeta | null {
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
  return {
    indexStride: stride as number,
    ringIntervalCount: count as number,
    ringChainageFractions: fr as number[],
  }
}

/** Index count revealed at chainage `progress`: the whole prefix of ring
 * intervals whose END ring lies at or before the progress fraction
 * (conservative — never a vertex beyond the excavated chainage). */
export function revealedIndexCount(meta: RevealMeta, progress: number): number {
  if (!(progress > 0)) return 0
  if (progress >= 1) return meta.ringIntervalCount * meta.indexStride
  let m = 0
  const fr = meta.ringChainageFractions
  while (m < meta.ringIntervalCount && fr[m + 1]! <= progress) m += 1
  return m * meta.indexStride
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
  const total = meta.ringIntervalCount * meta.indexStride
  if (!(progress > 0)) return { start: 0, count: 0 }
  if (progress >= 1) return { start: 0, count: total }
  const fr = meta.ringChainageFractions
  if (direction === 1) {
    let m = 0
    while (m < meta.ringIntervalCount && fr[m + 1]! <= progress) m += 1
    return { start: 0, count: m * meta.indexStride }
  }
  // interval i spans [fr[i], fr[i+1]]; from the end, interval i is complete
  // once fr[i] >= 1 − progress
  let m = 0
  while (m < meta.ringIntervalCount && fr[meta.ringIntervalCount - 1 - m]! >= 1 - progress) m += 1
  return { start: total - m * meta.indexStride, count: m * meta.indexStride }
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
  meta: (pieceId: string) => RevealMeta | null,
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
      meta: meta(o.pieceId),
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
