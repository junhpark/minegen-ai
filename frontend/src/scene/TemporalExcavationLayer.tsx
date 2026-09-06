import { useGLTF } from '@react-three/drei'
import { useEffect, useMemo } from 'react'
import { BufferGeometry, Mesh, Object3D } from 'three'
import { API_BASE_URL } from '@/api/client'
import { useTimelineStore } from '@/stores/timelineStore'
import {
  coveredEdgeIds,
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
  /** Phase 06 ramp GLB, or null when the `tunnelMesh` toggle is off
   * (20B.3-1.2: ramp and development reveals are independent) */
  rampUrl: string | null
  /** Phase 20B development GLB, or null when `developmentMesh` is off */
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
  // hooks are unconditional: an absent side loads the other side's (cached)
  // GLB and is simply not prepared / rendered; the caller guarantees at
  // least one url (excavationMountPlan.mounted)
  const anyUrl = rampUrl ?? developmentUrl ?? ''
  const rampGltf = useGLTF(`${API_BASE_URL}${rampUrl ?? anyUrl}`)
  const devGltf = useGLTF(`${API_BASE_URL}${developmentUrl ?? anyUrl}`)

  const ramp = useMemo(() => (rampUrl ? prepareRamp(rampGltf.scene) : null), [rampGltf, rampUrl])
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

  // 20B.3-1.3: coverage is decided by VALID reveal metadata — a segment /
  // piece without it is hidden AND left to the centerline fallback
  const rampMeta = useMemo(
    () =>
      new Map(
        (ramp?.prims ?? [])
          .filter((p) => p.role === 'SEGMENT' && p.segmentId !== null)
          .map((p) => [p.segmentId as string, p.meta] as const),
      ),
    [ramp],
  )
  const pieceMeta = useMemo(
    () =>
      new Map((dev?.prims ?? []).flatMap((p) => p.ranges.map((r) => [r.pieceId, r.meta] as const))),
    [dev],
  )
  const covered = useMemo(
    () => coveredEdgeIds(plan.reveals, rampMeta, pieceMeta),
    [plan, rampMeta, pieceMeta],
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
    const rampPrims = ramp?.prims ?? []
    let allRampComplete = rampPrims.some((p) => p.role === 'SEGMENT')
    let anyRamp = false
    for (const p of rampPrims) {
      if (p.role !== 'SEGMENT') continue
      const progress = p.segmentId !== null ? (rampProgress.get(p.segmentId) ?? 0) : 0
      // 20B.3-1.3: without reveal metadata the segment is never shown (its
      // edge is not covered, the centerline fallback renders instead)
      const count =
        p.meta === null
          ? 0
          : progress >= 1
            ? p.indexCount
            : Math.min(p.indexCount, revealedIndexCount(p.meta, progress))
      p.mesh.visible = count > 0
      p.mesh.geometry.setDrawRange(0, count)
      anyRamp = anyRamp || count > 0
      allRampComplete = allRampComplete && count >= p.indexCount
    }
    for (const p of rampPrims) {
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
      {ramp ? <primitive object={ramp.root} /> : null}
      {dev ? <primitive object={dev.root} /> : null}
    </group>
  )
}
