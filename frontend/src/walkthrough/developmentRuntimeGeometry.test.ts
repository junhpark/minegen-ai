/**
 * Phase 20D.2 hard gate: the development GLB primitive mapping proof. The
 * fixture is written by the REAL Phase 20D.1 backend writer (batch_render +
 * write_glb): a straight LEVEL_ACCESS (OPEN/OPEN), DRIFT (CAP/CAP) and
 * CROSSCUT (OPEN/CAP) → 5 primitives in writer order, each tube carrying one
 * `ranges` entry with the piece's reveal metadata.
 */
import { readFileSync } from 'node:fs'
import { GLTFLoader, type GLTF } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { BufferAttribute, BufferGeometry, Group, Mesh, type Object3D } from 'three'
import { beforeAll, describe, expect, it } from 'vitest'
import {
  buildDevelopmentColliderUnits,
  DevelopmentGeometryError,
  developmentCapColliderId,
  developmentColliderId,
  extractDevelopmentRuntimeGeometry,
  readDevelopmentRanges,
} from './developmentRuntimeGeometry'
import { toThreePositions } from './tunnelRuntimeGeometry'

function loadFixture(): Promise<GLTF> {
  const buf = readFileSync(new URL('./__fixtures__/development_three_kinds.glb', import.meta.url))
  const array = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength)
  return new Promise((resolve, reject) => {
    new GLTFLoader().parse(array, '', resolve, reject)
  })
}

let gltf: GLTF
beforeAll(async () => {
  gltf = await loadFixture()
})

function meshesOf(root: Object3D): Mesh[] {
  const out: Mesh[] = []
  root.traverse((o) => {
    if (o instanceof Mesh) out.push(o as Mesh)
  })
  return out
}

describe('GLTFLoader representation of the Phase 20D.1 development GLB', () => {
  it('exposes one Mesh per primitive in writer order with role/kind extras on geometry.userData', () => {
    const meshes = meshesOf(gltf.scene)
    const extras = meshes.map((m) => m.geometry.userData as { role?: string; kind?: string })
    expect(extras.map((e) => [e.role, e.kind])).toEqual([
      ['DEVELOPMENT', 'LEVEL_ACCESS'],
      ['DEVELOPMENT', 'DRIFT'],
      ['DRIFT_CAP', 'DRIFT'],
      ['DEVELOPMENT', 'CROSSCUT'],
      ['CROSSCUT_CAP', 'CROSSCUT'],
    ])
    expect(meshes.every((m) => Object.keys(m.userData).length === 0)).toBe(true)
  })
})

describe('development runtime-geometry adapter (rule 187)', () => {
  it('maps tubes and only the emitted caps, drops nothing and doubles nothing', () => {
    const g = extractDevelopmentRuntimeGeometry(gltf.scene)
    expect(g.tubes.map((t) => t.kind)).toEqual(['LEVEL_ACCESS', 'DRIFT', 'CROSSCUT'])
    // LEVEL_ACCESS is OPEN/OPEN: no cap primitive exists and none is invented
    expect(g.caps.map((c) => c.kind)).toEqual(['DRIFT', 'CROSSCUT'])
    expect(g.primitiveCount).toBe(5)
    const total = [...g.tubes, ...g.caps].reduce((n, p) => n + p.indices.length, 0)
    const sourceTotal = meshesOf(gltf.scene).reduce(
      (n, m) => n + m.geometry.getIndex()!.array.length,
      0,
    )
    expect(total).toBe(sourceTotal)
    expect(total % 3).toBe(0)
  })

  it('reuses the source index values exactly (no re-indexing by ranges, no new topology)', () => {
    const g = extractDevelopmentRuntimeGeometry(gltf.scene)
    const meshes = meshesOf(gltf.scene)
    const source = [meshes[0], meshes[1], meshes[3], meshes[2], meshes[4]].map(
      (m) => m!.geometry.getIndex()!.array,
    )
    const extracted = [...g.tubes, ...g.caps].map((p) => p.indices)
    extracted.forEach((idx, i) => {
      expect(Array.from(idx)).toEqual(Array.from(source[i]!))
      if (source[i] instanceof Uint32Array) expect(idx).toBe(source[i])
    })
    // every primitive shares the writer's single vertex buffer
    const buffers = new Set([...g.tubes, ...g.caps].map((p) => p.positions))
    expect(buffers.size).toBe(1)
  })

  it('validates the writer ranges: one piece per tube covering the whole index array, with reveal metadata', () => {
    const g = extractDevelopmentRuntimeGeometry(gltf.scene)
    for (const tube of g.tubes) {
      expect(tube.ranges).toHaveLength(1)
      const r = tube.ranges[0]!
      expect(r.indexOffset).toBe(0)
      expect(r.indexCount).toBe(tube.indices.length)
      expect(r.levelId).toBe('L01')
      expect(r.developmentId).toBe(r.pieceId)
      expect(r.meta.ringIntervalCount).toBeGreaterThan(0)
      expect(r.meta.ringIntervalIndexOffsets?.at(-1)).toBe(tube.indices.length)
    }
    expect(g.tubes.map((t) => t.ranges[0]!.developmentId)).toEqual([
      'LEVEL_ACCESS:L01',
      'DRIFT:L01',
      'CROSSCUT:L01:S+00',
    ])
  })

  it('canonical transform is exactly (x, y, z) → (x, z, −y)', () => {
    const three = toThreePositions(new Float32Array([1, 2, 3, -4, 5, -6]))
    expect(Array.from(three)).toEqual([1, 3, -2, -4, -6, -5])
    // mutations that must not survive
    expect(Array.from(three.slice(0, 3))).not.toEqual([1, 3, 2])
    expect(Array.from(three.slice(0, 3))).not.toEqual([1, -3, 2])
    expect(Array.from(three.slice(0, 3))).not.toEqual([1, 2, 3])
    const g = extractDevelopmentRuntimeGeometry(gltf.scene)
    const units = buildDevelopmentColliderUnits(g)
    const mine = g.tubes[0]!.positions
    const v = units[0]!.vertices
    for (let i = 0; i < 9; i += 3) {
      expect(v[i]).toBe(mine[i])
      expect(v[i + 1]).toBe(mine[i + 2])
      expect(v[i + 2]).toBe(-mine[i + 1]!)
    }
  })

  it('collider units: one per emitted primitive, unique ids, source indices as-is, one shared buffer', () => {
    const g = extractDevelopmentRuntimeGeometry(gltf.scene)
    const units = buildDevelopmentColliderUnits(g)
    expect(units.map((u) => u.id)).toEqual([
      developmentColliderId('LEVEL_ACCESS'),
      developmentColliderId('DRIFT'),
      developmentColliderId('CROSSCUT'),
      developmentCapColliderId('DRIFT'),
      developmentCapColliderId('CROSSCUT'),
    ])
    expect(units.map((u) => u.id)).not.toContain(developmentCapColliderId('LEVEL_ACCESS'))
    expect(new Set(units.map((u) => u.id)).size).toBe(units.length)
    units.forEach((u, i) => expect(u.indices).toBe([...g.tubes, ...g.caps][i]!.indices))
    expect(new Set(units.map((u) => u.vertices)).size).toBe(1)
    expect(units.every((u) => u.segmentId === null)).toBe(true)
  })

  it('T3: the collision input is the source triangles under the transform only — same count, same indices', () => {
    const g = extractDevelopmentRuntimeGeometry(gltf.scene)
    const units = buildDevelopmentColliderUnits(g)
    const meshes = meshesOf(gltf.scene)
    const sourceTriangles = meshes.reduce((n, m) => n + m.geometry.getIndex()!.count / 3, 0)
    const colliderTriangles = units.reduce((n, u) => n + u.indices.length / 3, 0)
    expect(colliderTriangles).toBe(sourceTriangles)
    const position = meshes[0]!.geometry.getAttribute('position').array as Float32Array
    expect(units[0]!.vertices.length).toBe(position.length)
    // every collider vertex is the transform of the SAME source vertex, no
    // vertex is added, moved, welded or dropped
    for (let i = 0; i < position.length; i += 3) {
      expect(units[0]!.vertices[i]).toBe(position[i])
      expect(units[0]!.vertices[i + 1]).toBe(position[i + 2])
      expect(units[0]!.vertices[i + 2]).toBe(-position[i + 1]!)
    }
  })
})

/** one-piece ranges table for a synthetic tube of `indexCount` indices */
function rangesFor(indexCount: number, pieceId = 'DRIFT:L01'): Record<string, unknown>[] {
  return [
    {
      developmentId: pieceId,
      pieceId,
      levelId: 'L01',
      indexOffset: 0,
      indexCount,
      indexStride: indexCount,
      ringIntervalCount: 1,
      ringChainageFractions: [0, 1],
      ringIntervalIndexOffsets: [0, indexCount],
    },
  ]
}

function mesh(
  role: unknown,
  kind: unknown,
  opts: {
    positions?: Float32Array | Float64Array
    indices?: Uint32Array | Uint16Array
    ranges?: unknown
  } = {},
  omit: { position?: boolean; index?: boolean; ranges?: boolean } = {},
): Mesh {
  const geometry = new BufferGeometry()
  const positions = opts.positions ?? new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 1, 0])
  const indices = opts.indices ?? new Uint16Array([0, 1, 2, 1, 3, 2])
  if (!omit.position) geometry.setAttribute('position', new BufferAttribute(positions, 3))
  if (!omit.index) geometry.setIndex(new BufferAttribute(indices, 1))
  const extras: Record<string, unknown> = {}
  if (role !== undefined) extras.role = role
  if (kind !== undefined) extras.kind = kind
  if (opts.ranges !== undefined) extras.ranges = opts.ranges
  else if (role === 'DEVELOPMENT' && !omit.ranges) extras.ranges = rangesFor(indices.length)
  geometry.userData = extras
  return new Mesh(geometry)
}

function scene(...meshes: Mesh[]): Group {
  const g = new Group()
  for (const m of meshes) g.add(m)
  return g
}

describe('development runtime-geometry adapter fails closed on malformed input', () => {
  const tube = (kind: string) => mesh('DEVELOPMENT', kind)
  const cases: [string, () => Group][] = [
    ['empty scene', () => scene()],
    ['missing position', () => scene(mesh('DEVELOPMENT', 'DRIFT', {}, { position: true }))],
    ['missing index', () => scene(mesh('DEVELOPMENT', 'DRIFT', {}, { index: true }))],
    [
      'non-triangle index count',
      () => scene(mesh('DEVELOPMENT', 'DRIFT', { indices: new Uint16Array([0, 1, 2, 1]) })),
    ],
    [
      'out-of-range index',
      () => scene(mesh('DEVELOPMENT', 'DRIFT', { indices: new Uint16Array([0, 1, 9]) })),
    ],
    [
      'non-Float32 positions',
      () => scene(mesh('DEVELOPMENT', 'DRIFT', { positions: new Float64Array(12) })),
    ],
    [
      'non-finite positions (NaN)',
      () =>
        scene(
          mesh('DEVELOPMENT', 'DRIFT', {
            positions: new Float32Array([0, 0, 0, 1, 0, 0, 0, NaN, 0, 1, 1, 0]),
          }),
        ),
    ],
    [
      'non-finite positions (Infinity)',
      () =>
        scene(
          mesh('DEVELOPMENT', 'DRIFT', {
            positions: new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0, Infinity, 1, 0]),
          }),
        ),
    ],
    ['unknown role', () => scene(mesh('SEGMENT', 'DRIFT'))],
    ['missing role', () => scene(mesh(undefined, 'DRIFT'))],
    ['unknown kind', () => scene(mesh('DEVELOPMENT', 'RAISE'))],
    ['missing kind', () => scene(mesh('DEVELOPMENT', undefined))],
    ['role/kind mismatch', () => scene(tube('CROSSCUT'), mesh('DRIFT_CAP', 'CROSSCUT'))],
    ['duplicate tube', () => scene(tube('DRIFT'), tube('DRIFT'))],
    [
      'duplicate cap',
      () => scene(tube('DRIFT'), mesh('DRIFT_CAP', 'DRIFT'), mesh('DRIFT_CAP', 'DRIFT')),
    ],
    ['cap without its tube', () => scene(tube('DRIFT'), mesh('CROSSCUT_CAP', 'CROSSCUT'))],
    ['caps only, no tube', () => scene(mesh('DRIFT_CAP', 'DRIFT'))],
    // ranges (§4): the writer table is validated, never repaired
    ['tube without ranges', () => scene(mesh('DEVELOPMENT', 'DRIFT', {}, { ranges: true }))],
    ['ranges not an array', () => scene(mesh('DEVELOPMENT', 'DRIFT', { ranges: { a: 1 } }))],
    ['empty ranges', () => scene(mesh('DEVELOPMENT', 'DRIFT', { ranges: [] }))],
    [
      'range exceeds the primitive',
      () => scene(mesh('DEVELOPMENT', 'DRIFT', { ranges: rangesFor(9) })),
    ],
    [
      'ranges do not cover the primitive',
      () => scene(mesh('DEVELOPMENT', 'DRIFT', { ranges: rangesFor(3) })),
    ],
    [
      'overlapping ranges',
      () =>
        scene(
          mesh('DEVELOPMENT', 'DRIFT', {
            ranges: [{ ...rangesFor(6)[0] }, { ...rangesFor(3, 'DRIFT:L02')[0], indexOffset: 3 }],
          }),
        ),
    ],
    [
      'gap between ranges',
      () =>
        scene(
          mesh('DEVELOPMENT', 'DRIFT', {
            indices: new Uint16Array([0, 1, 2, 1, 3, 2, 0, 1, 3]),
            ranges: [{ ...rangesFor(3)[0] }, { ...rangesFor(3, 'DRIFT:L02')[0], indexOffset: 6 }],
          }),
        ),
    ],
    [
      'duplicate piece id',
      () =>
        scene(
          mesh('DEVELOPMENT', 'DRIFT', {
            ranges: [{ ...rangesFor(3)[0] }, { ...rangesFor(3)[0], indexOffset: 3 }],
          }),
        ),
    ],
    [
      'non-integer indexOffset',
      () =>
        scene(mesh('DEVELOPMENT', 'DRIFT', { ranges: [{ ...rangesFor(6)[0], indexOffset: 0.5 }] })),
    ],
    [
      'non-triangle-aligned indexCount',
      () =>
        scene(
          mesh('DEVELOPMENT', 'DRIFT', {
            ranges: [{ ...rangesFor(4)[0] }, { ...rangesFor(2, 'DRIFT:L02')[0], indexOffset: 4 }],
          }),
        ),
    ],
    [
      'missing pieceId',
      () => scene(mesh('DEVELOPMENT', 'DRIFT', { ranges: [{ ...rangesFor(6)[0], pieceId: '' }] })),
    ],
    [
      'missing levelId',
      () =>
        scene(
          mesh('DEVELOPMENT', 'DRIFT', { ranges: [{ ...rangesFor(6)[0], levelId: undefined }] }),
        ),
    ],
    [
      'invalid reveal metadata (fractions)',
      () =>
        scene(
          mesh('DEVELOPMENT', 'DRIFT', {
            ranges: [{ ...rangesFor(6)[0], ringChainageFractions: [0, 0.5] }],
          }),
        ),
    ],
    [
      'invalid reveal metadata (offset table)',
      () =>
        scene(
          mesh('DEVELOPMENT', 'DRIFT', {
            ranges: [{ ...rangesFor(6)[0], ringIntervalIndexOffsets: [0, 3] }],
          }),
        ),
    ],
    [
      'cap carrying ranges',
      () => scene(tube('DRIFT'), mesh('DRIFT_CAP', 'DRIFT', { ranges: rangesFor(6) })),
    ],
  ]
  it.each(cases)('%s → DevelopmentGeometryError', (_name, build) => {
    expect(() => extractDevelopmentRuntimeGeometry(build())).toThrow(DevelopmentGeometryError)
  })

  it('accepts the minimal valid synthetic contract (tube + matching cap)', () => {
    const g = extractDevelopmentRuntimeGeometry(scene(tube('DRIFT'), mesh('DRIFT_CAP', 'DRIFT')))
    expect(g.tubes.map((t) => t.kind)).toEqual(['DRIFT'])
    expect(g.caps.map((c) => c.kind)).toEqual(['DRIFT'])
    expect(buildDevelopmentColliderUnits(g).map((u) => u.id)).toEqual([
      developmentColliderId('DRIFT'),
      developmentCapColliderId('DRIFT'),
    ])
  })

  it('accepts a multi-piece table that is contiguous and gap-free, in buffer order', () => {
    const ranges = readDevelopmentRanges(
      {
        ranges: [{ ...rangesFor(3)[0] }, { ...rangesFor(3, 'DRIFT:L01:B')[0], indexOffset: 3 }],
      },
      'DRIFT',
      6,
    )
    expect(ranges.map((r) => [r.pieceId, r.indexOffset, r.indexCount])).toEqual([
      ['DRIFT:L01', 0, 3],
      ['DRIFT:L01:B', 3, 3],
    ])
  })

  it('Uint16 indices are widened to Uint32 with identical values', () => {
    const g = extractDevelopmentRuntimeGeometry(
      scene(mesh('DEVELOPMENT', 'DRIFT', { indices: new Uint16Array([0, 1, 2, 1, 3, 2]) })),
    )
    expect(g.tubes[0]!.indices).toBeInstanceOf(Uint32Array)
    expect(Array.from(g.tubes[0]!.indices)).toEqual([0, 1, 2, 1, 3, 2])
  })
})
