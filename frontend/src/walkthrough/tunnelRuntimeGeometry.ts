/**
 * Phase 13 tunnel runtime-geometry adapter (rule 100).
 *
 * PROVEN GLTFLoader representation of the Phase 06 GLB (inspected against a
 * writer-generated fixture): the single glTF mesh with N+2 primitives is
 * exposed as one Group (the "tunnel" node) whose children are separate
 * THREE.Mesh objects, ONE PER PRIMITIVE, in exact primitive order —
 * segment 0..N-1, PORTAL_CAP, TERMINAL_CAP. Primitive extras appear on
 * `mesh.geometry.userData` (NOT `mesh.userData`, which is empty). All
 * primitives share the same POSITION attribute; each carries its own index.
 *
 * The adapter therefore splits by geometry.userData role with the primitive
 * order preserved, reuses the shared vertex buffer and the source index
 * arrays EXACTLY, and never resamples, smooths or regenerates profile
 * topology. The only permitted transformation is the canonical mine→Three
 * rotation (identical to the visual −90° X group rotation).
 */
import { Mesh, type Object3D } from 'three'

export class TunnelGeometryError extends Error {}

export interface TunnelPrimitiveGeometry {
  /** shared backend vertex buffer, mine coordinates, flat xyz */
  positions: Float32Array
  /** source triangle indices, reused exactly */
  indices: Uint32Array
}

export interface TunnelSegmentGeometry extends TunnelPrimitiveGeometry {
  segmentId: string
}

export interface TunnelRuntimeGeometry {
  segments: TunnelSegmentGeometry[]
  portalCap: TunnelPrimitiveGeometry
  terminalCap: TunnelPrimitiveGeometry
  /** total number of source primitives consumed (segments + 2 caps) */
  primitiveCount: number
}

interface PrimitiveUserData {
  role?: unknown
  segmentId?: unknown
}

function primitiveOf(mesh: Mesh): TunnelPrimitiveGeometry {
  const geometry = mesh.geometry
  const position = geometry.getAttribute('position')
  const index = geometry.getIndex()
  if (!position || !index) throw new TunnelGeometryError('tunnel primitive lacks position/index')
  const positions = position.array
  const indices = index.array
  if (!(positions instanceof Float32Array)) {
    throw new TunnelGeometryError('tunnel positions are not a Float32Array')
  }
  if (!(indices instanceof Uint32Array) && !(indices instanceof Uint16Array)) {
    throw new TunnelGeometryError('tunnel indices are not an integer array')
  }
  if (positions.length % 3 !== 0 || indices.length % 3 !== 0) {
    throw new TunnelGeometryError('tunnel primitive arrays are not triangle-shaped')
  }
  const vertexCount = positions.length / 3
  for (let i = 0; i < indices.length; i++) {
    if (indices[i]! >= vertexCount) {
      throw new TunnelGeometryError('tunnel primitive index out of vertex range')
    }
  }
  return {
    positions,
    indices: indices instanceof Uint32Array ? indices : new Uint32Array(indices),
  }
}

/**
 * Split the loaded GLB scene into per-primitive runtime geometry. Throws
 * TunnelGeometryError when the authoritative writer contract is not met —
 * the caller treats that as "walkthrough unavailable", never guesses.
 */
export function extractTunnelRuntimeGeometry(root: Object3D): TunnelRuntimeGeometry {
  const meshes: Mesh[] = []
  root.traverse((o) => {
    if (o instanceof Mesh) meshes.push(o as Mesh)
  })
  if (meshes.length < 3) {
    throw new TunnelGeometryError(`expected >=3 tunnel primitives, found ${meshes.length}`)
  }
  const segments: TunnelSegmentGeometry[] = []
  let portalCap: TunnelPrimitiveGeometry | null = null
  let terminalCap: TunnelPrimitiveGeometry | null = null
  const seen = new Set<string>()
  for (const mesh of meshes) {
    const extras = mesh.geometry.userData as PrimitiveUserData
    const role = extras.role
    if (role === 'SEGMENT') {
      const segmentId = extras.segmentId
      if (typeof segmentId !== 'string' || segmentId.length === 0) {
        throw new TunnelGeometryError('tunnel segment primitive lacks a segmentId')
      }
      if (seen.has(segmentId)) {
        throw new TunnelGeometryError(`duplicate tunnel segmentId ${segmentId}`)
      }
      seen.add(segmentId)
      if (portalCap || terminalCap) {
        throw new TunnelGeometryError('tunnel segment primitive found after caps')
      }
      segments.push({ segmentId, ...primitiveOf(mesh) })
    } else if (role === 'PORTAL_CAP') {
      if (portalCap) throw new TunnelGeometryError('duplicate PORTAL_CAP primitive')
      portalCap = primitiveOf(mesh)
    } else if (role === 'TERMINAL_CAP') {
      if (terminalCap) throw new TunnelGeometryError('duplicate TERMINAL_CAP primitive')
      terminalCap = primitiveOf(mesh)
    } else {
      throw new TunnelGeometryError(`unknown tunnel primitive role ${String(role)}`)
    }
  }
  if (segments.length === 0) throw new TunnelGeometryError('tunnel GLB has no segment primitives')
  if (!portalCap) throw new TunnelGeometryError('tunnel GLB is missing PORTAL_CAP')
  if (!terminalCap) throw new TunnelGeometryError('tunnel GLB is missing TERMINAL_CAP')
  return { segments, portalCap, terminalCap, primitiveCount: meshes.length }
}

/**
 * Canonical mine→Three vertex transform: (x,y,z) → (x,z,−y). This is the
 * pure-rotation equivalent of the visual −90° X group rotation, so the
 * collision tunnel and the visual tunnel occupy the exact same space.
 */
export function toThreePositions(minePositions: Float32Array): Float32Array {
  const out = new Float32Array(minePositions.length)
  for (let i = 0; i < minePositions.length; i += 3) {
    out[i] = minePositions[i]!
    out[i + 1] = minePositions[i + 2]!
    out[i + 2] = -minePositions[i + 1]!
  }
  return out
}

export interface ColliderUnit {
  /** stable Phase 15-ready collider identity */
  id: string
  /** shared vertex buffer, Three coordinates */
  vertices: Float32Array
  indices: Uint32Array
  segmentId: string | null
}

export const PORTAL_CAP_COLLIDER_ID = 'WALK:COLLIDER:PORTAL_CAP'
export const TERMINAL_CAP_COLLIDER_ID = 'WALK:COLLIDER:TERMINAL_CAP'

export function segmentColliderId(segmentId: string): string {
  return `WALK:COLLIDER:SEGMENT:${segmentId}`
}

/**
 * Stable independently addressable collider units (rule 104): one fixed
 * trimesh per decline segment plus separately identifiable caps, all
 * sharing ONE transformed vertex buffer. Phase 15 can later activate or
 * deactivate an individual segment collider by ID without rebuilding the
 * physics world; Phase 13 keeps every unit active.
 */
export function buildColliderUnits(geometry: TunnelRuntimeGeometry): ColliderUnit[] {
  // primitives share one glTF POSITION accessor; transform each distinct
  // source buffer exactly once (reference-keyed, no per-unit duplication)
  const cache = new Map<Float32Array, Float32Array>()
  const three = (src: Float32Array): Float32Array => {
    let out = cache.get(src)
    if (!out) {
      out = toThreePositions(src)
      cache.set(src, out)
    }
    return out
  }
  const units: ColliderUnit[] = geometry.segments.map((s) => ({
    id: segmentColliderId(s.segmentId),
    vertices: three(s.positions),
    indices: s.indices,
    segmentId: s.segmentId,
  }))
  units.push({
    id: PORTAL_CAP_COLLIDER_ID,
    vertices: three(geometry.portalCap.positions),
    indices: geometry.portalCap.indices,
    segmentId: null,
  })
  units.push({
    id: TERMINAL_CAP_COLLIDER_ID,
    vertices: three(geometry.terminalCap.positions),
    indices: geometry.terminalCap.indices,
    segmentId: null,
  })
  const ids = units.map((u) => u.id)
  if (new Set(ids).size !== ids.length) {
    throw new TunnelGeometryError('collider unit ids are not unique')
  }
  return units
}

export interface TunnelPrimitiveMetadata {
  role: 'SEGMENT' | 'PORTAL_CAP' | 'TERMINAL_CAP' | null
  segmentId: string | null
}

/**
 * Shared reader for the PROVEN GLTFLoader representation: primitive extras
 * live on `mesh.geometry.userData`, never on `mesh.userData` (empirically
 * pinned in Phase 13). Used by BOTH the static TunnelMeshLayer and the
 * temporal walkthrough visual layer so the metadata contract cannot drift.
 */
export function readTunnelPrimitiveMetadata(mesh: {
  geometry: { userData: unknown }
}): TunnelPrimitiveMetadata {
  const extras = mesh.geometry.userData as { role?: unknown; segmentId?: unknown }
  const role = extras.role
  const segmentId = typeof extras.segmentId === 'string' ? extras.segmentId : null
  if (role === 'SEGMENT' || role === 'PORTAL_CAP' || role === 'TERMINAL_CAP') {
    return { role, segmentId }
  }
  return { role: null, segmentId }
}
