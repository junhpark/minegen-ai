import { useGLTF } from '@react-three/drei'
import { useEffect, useMemo } from 'react'
import { BufferGeometry, Mesh, Object3D } from 'three'
import { API_BASE_URL } from '@/api/client'
import { useTimelineStore } from '@/stores/timelineStore'
import {
  planIndexGroups,
  readPieceRanges,
  readRevealMeta,
  revealedIndexCount,
  resolveExcavationReveal,
  type PieceRange,
  type RevealMeta,
} from '@/timeline/excavationReveal'
import type {
  LevelAccessesPayload,
  LevelsPayload,
  SmoothedDeclinePayload,
  TimelinePayload,
} from '@/types/scene'
import { applyRockTexture, CAP_MATERIAL, TUNNEL_MATERIAL } from '@/walkthrough/tunnelMaterials'
import { readTunnelPrimitiveMetadata } from '@/walkthrough/tunnelRuntimeGeometry'
import { useRockTexture } from '@/walkthrough/useRockTexture'

/**
 * Phase 20B.2-F: 4D progressive EXCAVATION reveal (visualization only).
 *
 * The SAME cached Phase 06 ramp GLB and Phase 20B development GLB are shown
 * in 4D; per Phase 10 state a segment / piece is hidden (NOT_BUILT), shown
 * complete (ACTIVE and later) or cut at its last COMPLETED ring for the
 * continuous DEVELOPING progress (rule 31). Cutting is a draw range on a
 * per-segment primitive (ramp) or draw GROUPS on the per-kind batched
 * primitive (developments) over geometry that shares the loaded vertex /
 * index buffers — nothing is regenerated per day or per frame and the
 * cached GLB scene is never mutated (a private BufferGeometry re-uses the
 * loaded attributes). Materials are the shared tunnel materials
 * (`applyRockTexture` single path). Fail-closed: a development whose
 * geometryRef does not resolve keeps the centerline rendering (the caller
 * passes those edge ids back to TimelineDevelopmentLayer).
 */

/** Private geometry sharing the loaded attributes / index (no copies). */
function sharedGeometry(src: BufferGeometry): BufferGeometry {
  const g = new BufferGeometry()
  for (const [name, attr] of Object.entries(src.attributes)) g.setAttribute(name, attr)
  if (src.index) g.setIndex(src.index)
  g.boundingSphere = src.boundingSphere
  g.boundingBox = src.boundingBox
  g.userData = src.userData
  return g
}

interface RampPrimitive {
  mesh: Mesh
  role: 'SEGMENT' | 'PORTAL_CAP' | 'TERMINAL_CAP'
  segmentId: string | null
  meta: RevealMeta | null
  indexCount: number
}

interface DevelopmentPrimitive {
  mesh: Mesh
  kind: string
  role: 'DEVELOPMENT' | 'CAP'
  ranges: PieceRange[]
}

function prepareRamp(scene: Object3D): { root: Object3D; prims: RampPrimitive[] } {
  const root = scene.clone(true)
  const prims: RampPrimitive[] = []
  root.traverse((o) => {
    if (!(o instanceof Mesh)) return
    const mesh = o as Mesh
    const { role, segmentId } = readTunnelPrimitiveMetadata(mesh)
    if (role === null) {
      mesh.visible = false
      return
    }
    const geometry = sharedGeometry(mesh.geometry)
    mesh.geometry = geometry
    mesh.material = role === 'SEGMENT' ? TUNNEL_MATERIAL : CAP_MATERIAL
    prims.push({
      mesh,
      role,
      segmentId,
      meta: role === 'SEGMENT' ? readRevealMeta(geometry.userData) : null,
      indexCount: geometry.index?.count ?? 0,
    })
  })
  return { root, prims }
}

function prepareDevelopment(scene: Object3D): { root: Object3D; prims: DevelopmentPrimitive[] } {
  const root = scene.clone(true)
  const prims: DevelopmentPrimitive[] = []
  root.traverse((o) => {
    if (!(o instanceof Mesh)) return
    const mesh = o as Mesh
    const extras = mesh.geometry.userData as { role?: unknown; kind?: unknown }
    const role = typeof extras.role === 'string' ? extras.role : null
    const kind = typeof extras.kind === 'string' ? extras.kind : null
    if (role === null || kind === null) {
      mesh.visible = false
      return
    }
    const geometry = sharedGeometry(mesh.geometry)
    mesh.geometry = geometry
    if (role === 'DEVELOPMENT') {
      // groups need an array material; the SHARED material object is reused
      mesh.material = [TUNNEL_MATERIAL]
      const ranges = readPieceRanges(geometry.userData, () => null).map((r) => ({
        ...r,
        meta: rangeMeta(geometry.userData, r.pieceId),
      }))
      prims.push({ mesh, kind, role: 'DEVELOPMENT', ranges })
    } else {
      mesh.material = CAP_MATERIAL
      prims.push({ mesh, kind, role: 'CAP', ranges: [] })
    }
  })
  return { root, prims }
}

function rangeMeta(extras: unknown, pieceId: string): RevealMeta | null {
  const raw: unknown = (extras as { ranges?: unknown }).ranges
  if (!Array.isArray(raw)) return null
  const list: unknown[] = raw
  const r = list.find(
    (x) => x !== null && typeof x === 'object' && (x as { pieceId?: unknown }).pieceId === pieceId,
  )
  return r === undefined ? null : readRevealMeta(r)
}

export function TemporalExcavationLayer({
  rampUrl,
  developmentUrl,
  timeline,
  smoothed,
  levels,
  levelAccesses,
  onCoverage,
}: {
  rampUrl: string
  developmentUrl: string | null
  timeline: TimelinePayload
  smoothed: SmoothedDeclinePayload
  levels: LevelsPayload | null
  levelAccesses: LevelAccessesPayload | null
  /** edge ids rendered as excavation meshes (the caller skips their lines) */
  onCoverage?: (edgeIds: string[]) => void
}) {
  const currentDay = useTimelineStore((s) => s.currentDay)
  const rock = useRockTexture()
  useMemo(() => applyRockTexture(rock), [rock])
  const rampGltf = useGLTF(`${API_BASE_URL}${rampUrl}`)
  const devGltf = useGLTF(
    developmentUrl ? `${API_BASE_URL}${developmentUrl}` : `${API_BASE_URL}${rampUrl}`,
  )

  const ramp = useMemo(() => prepareRamp(rampGltf.scene), [rampGltf])
  const dev = useMemo(
    () => (developmentUrl ? prepareDevelopment(devGltf.scene) : null),
    [devGltf, developmentUrl],
  )

  // identity resolution is day-dependent only through progress; the mapping
  // itself (which mesh a development is) is fixed by the artifacts
  const plan = useMemo(
    () => resolveExcavationReveal(timeline, smoothed, levels, levelAccesses, currentDay),
    [timeline, smoothed, levels, levelAccesses, currentDay],
  )

  const rampIds = useMemo(
    () => new Set(ramp.prims.filter((p) => p.segmentId).map((p) => p.segmentId)),
    [ramp],
  )
  const pieceIds = useMemo(
    () => new Set((dev?.prims ?? []).flatMap((p) => p.ranges.map((r) => r.pieceId))),
    [dev],
  )
  const covered = useMemo(
    () =>
      plan.reveals
        .filter((r) =>
          r.target.kind === 'RAMP'
            ? rampIds.has(r.target.segmentId)
            : pieceIds.has(r.target.pieceId),
        )
        .map((r) => r.edgeId),
    [plan, rampIds, pieceIds],
  )
  useEffect(() => {
    onCoverage?.(covered)
  }, [covered, onCoverage])

  // apply the day's reveal: draw ranges / groups only — no geometry work
  useEffect(() => {
    const rampProgress = new Map<string, number>()
    const pieceProgress = new Map<string, number>()
    for (const r of plan.reveals) {
      if (r.target.kind === 'RAMP') rampProgress.set(r.target.segmentId, r.progress)
      else pieceProgress.set(r.target.pieceId, r.progress)
    }
    let allRampComplete = ramp.prims.some((p) => p.role === 'SEGMENT')
    let anyRamp = false
    for (const p of ramp.prims) {
      if (p.role !== 'SEGMENT') continue
      const progress = p.segmentId !== null ? (rampProgress.get(p.segmentId) ?? 0) : 0
      const count =
        progress >= 1
          ? p.indexCount
          : p.meta
            ? Math.min(p.indexCount, revealedIndexCount(p.meta, progress))
            : 0
      p.mesh.visible = count > 0
      p.mesh.geometry.setDrawRange(0, count)
      anyRamp = anyRamp || count > 0
      allRampComplete = allRampComplete && count >= p.indexCount
    }
    for (const p of ramp.prims) {
      if (p.role === 'PORTAL_CAP') p.mesh.visible = anyRamp
      else if (p.role === 'TERMINAL_CAP') p.mesh.visible = allRampComplete
    }
    if (dev) {
      const completeByKind = new Map<string, boolean>()
      for (const p of dev.prims) {
        if (p.role !== 'DEVELOPMENT') continue
        const groups = planIndexGroups(p.ranges, pieceProgress)
        const g = p.mesh.geometry
        g.clearGroups()
        for (const grp of groups) g.addGroup(grp.start, grp.count, 0)
        p.mesh.visible = groups.length > 0
        const total = p.ranges.reduce((s, r) => s + r.indexCount, 0)
        const shown = groups.reduce((s, grp) => s + grp.count, 0)
        completeByKind.set(p.kind, total > 0 && shown >= total)
      }
      // batched caps carry no per-piece ranges: shown only once every piece
      // of that kind is complete (an open ring end reads as the working face)
      for (const p of dev.prims) {
        if (p.role === 'CAP') p.mesh.visible = completeByKind.get(p.kind) === true
      }
    }
  }, [plan, ramp, dev])

  return (
    <group rotation={[-Math.PI / 2, 0, 0]}>
      <primitive object={ramp.root} />
      {dev ? <primitive object={dev.root} /> : null}
    </group>
  )
}
