/**
 * Phase 20D.2 development runtime-geometry adapter (rule 187).
 *
 * Same architecture boundary as `tunnelRuntimeGeometry.ts`: the Phase 20D.1
 * `development_mesh.glb` is exposed by GLTFLoader as one Mesh child per
 * primitive in writer order, with primitive extras on `geometry.userData`.
 * The writer contract is batched PER KIND — one tube primitive
 * (`role = DEVELOPMENT`, `kind = LEVEL_ACCESS | DRIFT | CROSSCUT`, `ranges`
 * mapping contiguous index ranges back to development / piece ids with the
 * piece's progressive-reveal metadata) and, only where a CAP endpoint
 * exists, one cap primitive (`role = <KIND>_CAP`, same `kind`, no ranges).
 * The adapter reuses the source vertex buffer and index arrays EXACTLY (the
 * emitted triangles, typed junction apertures included) and never resweeps,
 * re-indexes by `ranges`, patches or approximates. The only permitted
 * transform is the canonical mine→Three rotation shared with the ramp
 * (`toThreePositions`). The validated `ranges` keep every piece's identity
 * on the runtime geometry (a future time-aware activation addresses pieces
 * by id and index range without a second GLB or a per-development mesh);
 * the STATIC_FINAL collider units stay kind-level.
 *
 * Malformed input is an explicit `DevelopmentGeometryError`; the caller
 * fails the static walkthrough closed and never guesses.
 */
import { Mesh, type Object3D } from 'three'
import { readRevealMeta, type RevealMeta } from '@/timeline/excavationReveal'
import { readTrianglePrimitive, toThreePositions, type ColliderUnit } from './tunnelRuntimeGeometry'

export class DevelopmentGeometryError extends Error {}

export const DEVELOPMENT_KINDS = ['LEVEL_ACCESS', 'DRIFT', 'CROSSCUT'] as const
export type DevelopmentKind = (typeof DEVELOPMENT_KINDS)[number]

/** One writer `ranges` entry of a batched tube primitive, validated. */
export interface DevelopmentPieceRange {
  developmentId: string
  pieceId: string
  levelId: string
  /** first index of the piece inside the primitive's index array */
  indexOffset: number
  /** index count of the piece (a multiple of 3) */
  indexCount: number
  /** the piece's own progressive-reveal metadata (shared reader, one authority) */
  meta: RevealMeta
}

export interface DevelopmentPrimitiveGeometry {
  kind: DevelopmentKind
  /** shared backend vertex buffer, mine coordinates, flat xyz */
  positions: Float32Array
  /** source triangle indices, reused exactly */
  indices: Uint32Array
}

export interface DevelopmentTubeGeometry extends DevelopmentPrimitiveGeometry {
  /** contiguous, non-overlapping, gap-free piece ranges covering the whole
   * index array, in buffer order (writer contract) */
  ranges: DevelopmentPieceRange[]
}

export interface DevelopmentRuntimeGeometry {
  /** tube primitives in writer order (one per kind actually emitted) */
  tubes: DevelopmentTubeGeometry[]
  /** cap primitives in writer order (only kinds with a CAP endpoint) */
  caps: DevelopmentPrimitiveGeometry[]
  /** total number of source primitives consumed */
  primitiveCount: number
}

function isKind(value: unknown): value is DevelopmentKind {
  return typeof value === 'string' && (DEVELOPMENT_KINDS as readonly string[]).includes(value)
}

function fail(message: string): never {
  throw new DevelopmentGeometryError(message)
}

/**
 * Validate the writer `ranges` extras of one DEVELOPMENT tube primitive
 * against its actual index count. Every entry must carry string ids, an
 * integer `indexOffset` / `indexCount` aligned to triangles and inside the
 * primitive, and reveal metadata the shared `readRevealMeta` accepts for
 * that count; the entries must be in buffer order, contiguous (no gap, no
 * overlap) and cover the primitive exactly; piece ids are unique. Nothing
 * is repaired: a malformed table fails the whole adapter.
 */
export function readDevelopmentRanges(
  extras: unknown,
  kind: DevelopmentKind,
  indexCount: number,
): DevelopmentPieceRange[] {
  const raw = (extras as { ranges?: unknown } | null)?.ranges
  if (!Array.isArray(raw)) fail(`development ${kind} tube lacks a ranges array`)
  if (raw.length === 0) fail(`development ${kind} tube has an empty ranges array`)
  const out: DevelopmentPieceRange[] = []
  const pieces = new Set<string>()
  let cursor = 0
  for (const entry of raw) {
    if (!entry || typeof entry !== 'object') fail(`development ${kind} range is not an object`)
    const o = entry as Record<string, unknown>
    const { developmentId, pieceId, levelId, indexOffset, indexCount: count } = o
    if (typeof developmentId !== 'string' || developmentId.length === 0) {
      fail(`development ${kind} range lacks a developmentId`)
    }
    if (typeof pieceId !== 'string' || pieceId.length === 0) {
      fail(`development ${kind} range ${developmentId} lacks a pieceId`)
    }
    if (typeof levelId !== 'string' || levelId.length === 0) {
      fail(`development ${kind} range ${pieceId} lacks a levelId`)
    }
    if (!Number.isInteger(indexOffset) || (indexOffset as number) < 0) {
      fail(`development ${kind} range ${pieceId} has an invalid indexOffset`)
    }
    if (!Number.isInteger(count) || (count as number) <= 0) {
      fail(`development ${kind} range ${pieceId} has an invalid indexCount`)
    }
    const offset = indexOffset as number
    const n = count as number
    if (offset % 3 !== 0 || n % 3 !== 0) {
      fail(`development ${kind} range ${pieceId} is not triangle-aligned`)
    }
    if (offset !== cursor) {
      fail(
        `development ${kind} range ${pieceId} starts at ${offset}, expected ${cursor} ` +
          '(ranges must be contiguous, in buffer order, without overlap or gap)',
      )
    }
    if (offset + n > indexCount) {
      fail(`development ${kind} range ${pieceId} exceeds the primitive index count`)
    }
    if (pieces.has(pieceId)) fail(`duplicate development ${kind} piece ${pieceId}`)
    pieces.add(pieceId)
    const meta = readRevealMeta(o, n)
    if (meta === null) fail(`development ${kind} range ${pieceId} has invalid reveal metadata`)
    out.push({ developmentId, pieceId, levelId, indexOffset: offset, indexCount: n, meta })
    cursor = offset + n
  }
  if (cursor !== indexCount) {
    fail(
      `development ${kind} ranges cover ${cursor} of ${indexCount} indices ` +
        '(the table must account for every emitted index)',
    )
  }
  return out
}

/**
 * Split the loaded development GLB scene into per-primitive runtime
 * geometry. Throws DevelopmentGeometryError when the writer contract is not
 * met (missing/invalid arrays, unknown role or kind, role/kind mismatch, a
 * duplicated semantic primitive, a cap whose tube is absent or that carries
 * ranges, no tube, a non-finite vertex, an invalid ranges table).
 */
export function extractDevelopmentRuntimeGeometry(root: Object3D): DevelopmentRuntimeGeometry {
  const meshes: Mesh[] = []
  root.traverse((o) => {
    if (o instanceof Mesh) meshes.push(o as Mesh)
  })
  if (meshes.length === 0) fail('development GLB has no primitives')
  const tubes: DevelopmentTubeGeometry[] = []
  const caps: DevelopmentPrimitiveGeometry[] = []
  const seen = new Set<string>()
  const finiteBuffers = new Set<Float32Array>()
  for (const mesh of meshes) {
    const extras = mesh.geometry.userData as { role?: unknown; kind?: unknown; ranges?: unknown }
    const role: unknown = extras.role
    const kind: unknown = extras.kind
    if (typeof role !== 'string') fail(`development primitive lacks a role (${String(role)})`)
    if (!isKind(kind)) fail(`development primitive has an unknown kind ${String(kind)}`)
    let semantic: 'DEVELOPMENT' | 'CAP'
    if (role === 'DEVELOPMENT') {
      semantic = 'DEVELOPMENT'
    } else if (role.endsWith('_CAP')) {
      if (role !== `${kind}_CAP`) fail(`development cap role ${role} does not match kind ${kind}`)
      semantic = 'CAP'
    } else {
      fail(`unknown development primitive role ${role}`)
    }
    const key = `${semantic}:${kind}`
    if (seen.has(key)) fail(`duplicate development primitive ${key}`)
    seen.add(key)
    const geometry = readTrianglePrimitive(mesh, (message) => fail(`development ${message}`))
    // finite positions (rule 34 on the consuming side): a NaN / ±inf vertex
    // would be a silent hole in the collision trimesh; each distinct shared
    // buffer is scanned once
    if (!finiteBuffers.has(geometry.positions)) {
      for (let i = 0; i < geometry.positions.length; i++) {
        if (!Number.isFinite(geometry.positions[i]!)) {
          fail('development positions are not all finite')
        }
      }
      finiteBuffers.add(geometry.positions)
    }
    if (semantic === 'DEVELOPMENT') {
      const ranges = readDevelopmentRanges(extras, kind, geometry.indices.length)
      tubes.push({ kind, ...geometry, ranges })
    } else {
      if (extras.ranges !== undefined) fail(`development cap ${role} carries ranges`)
      caps.push({ kind, ...geometry })
    }
  }
  if (tubes.length === 0) fail('development GLB has no tube primitives')
  for (const cap of caps) {
    if (!tubes.some((t) => t.kind === cap.kind)) {
      fail(`development cap ${cap.kind}_CAP has no ${cap.kind} tube`)
    }
  }
  return { tubes, caps, primitiveCount: meshes.length }
}

export function developmentColliderId(kind: DevelopmentKind): string {
  return `WALK:COLLIDER:DEVELOPMENT:${kind}`
}

export function developmentCapColliderId(kind: DevelopmentKind): string {
  return `WALK:COLLIDER:DEVELOPMENT_CAP:${kind}`
}

/**
 * Fixed collider units for the STATIC_FINAL walkthrough: one trimesh per
 * emitted batched tube primitive and one per emitted cap primitive — the
 * source index arrays as-is, the shared vertex buffer transformed exactly
 * once. No piece-level split (the validated `ranges` keep piece identity
 * for a later time-aware activation), no fake cap for an OPEN endpoint, no
 * collision-only geometry.
 */
export function buildDevelopmentColliderUnits(
  geometry: DevelopmentRuntimeGeometry,
): ColliderUnit[] {
  const cache = new Map<Float32Array, Float32Array>()
  const three = (src: Float32Array): Float32Array => {
    let out = cache.get(src)
    if (!out) {
      out = toThreePositions(src)
      cache.set(src, out)
    }
    return out
  }
  const units: ColliderUnit[] = [
    ...geometry.tubes.map((t) => ({
      id: developmentColliderId(t.kind),
      vertices: three(t.positions),
      indices: t.indices,
      segmentId: null,
    })),
    ...geometry.caps.map((c) => ({
      id: developmentCapColliderId(c.kind),
      vertices: three(c.positions),
      indices: c.indices,
      segmentId: null,
    })),
  ]
  const ids = units.map((u) => u.id)
  if (new Set(ids).size !== ids.length) fail('development collider unit ids are not unique')
  return units
}
