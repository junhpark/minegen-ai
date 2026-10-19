import { useGLTF } from '@react-three/drei'
import { useEffect, useMemo } from 'react'
import { BufferGeometry, Mesh, Object3D } from 'three'
import type {
  LevelAccessesPayload,
  LevelsPayload,
  NetworkPayload,
  SmoothedDeclinePayload,
  TimelinePayload,
} from '@/types/scene'
import {
  developmentPieceIdentities,
  extractDevelopmentRuntimeGeometry,
} from './developmentRuntimeGeometry'
import { resolveTemporalDevelopmentPlan } from './temporalDevelopmentPlan'
import { applyRockTexture, CAP_MATERIAL, TUNNEL_MATERIAL } from './tunnelMaterials'
import { useRockTexture } from './useRockTexture'

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

/**
 * Temporal development visual for the TIMELINE_SNAPSHOT walkthrough (PR-4
 * W1a, rule 187 "visual = collidable"): the SAME cached development GLB the
 * static layer renders, cloned once, showing exactly the pieces the
 * temporal development plan marks ACTIVE as draw groups over the shared
 * buffers (`ranges` windows — never regenerated geometry) and the batched
 * cap primitive of every active kind. The plan is the same pure function
 * the runtime mounts its colliders from, over the same artifacts, so what
 * is shown is what collides; an INVALID plan shows nothing (the runtime
 * exits the session). Not-yet-active developments never appear.
 */
export function TemporalDevelopmentLayer({
  url,
  timeline,
  levels,
  levelAccesses,
  network,
  smoothed,
  snapshotDay,
  activeRampSegmentIds,
}: {
  url: string
  timeline: TimelinePayload | null
  levels: LevelsPayload | null
  levelAccesses: LevelAccessesPayload | null
  network: NetworkPayload | null
  smoothed: SmoothedDeclinePayload | null
  snapshotDay: number
  activeRampSegmentIds: readonly string[]
}) {
  const gltf = useGLTF(url)
  const rock = useRockTexture()
  useMemo(() => applyRockTexture(rock), [rock])
  const runtime = useMemo(() => {
    try {
      return extractDevelopmentRuntimeGeometry(gltf.scene)
    } catch {
      return null
    }
  }, [gltf])
  const plan = useMemo(
    () =>
      runtime
        ? resolveTemporalDevelopmentPlan(
            timeline,
            levels,
            levelAccesses,
            network,
            smoothed,
            developmentPieceIdentities(runtime),
            snapshotDay,
            activeRampSegmentIds,
          )
        : null,
    [
      runtime,
      timeline,
      levels,
      levelAccesses,
      network,
      smoothed,
      snapshotDay,
      activeRampSegmentIds,
    ],
  )
  const prepared = useMemo(() => {
    const root: Object3D = gltf.scene.clone(true)
    const tubes: {
      mesh: Mesh
      kind: string
      ranges: { pieceId: string; indexOffset: number; indexCount: number }[]
    }[] = []
    const caps: { mesh: Mesh; kind: string }[] = []
    root.traverse((o) => {
      if (!(o instanceof Mesh)) return
      const mesh = o as Mesh
      const extras = mesh.geometry.userData as { role?: unknown; kind?: unknown; ranges?: unknown }
      const role = typeof extras.role === 'string' ? extras.role : null
      const kind = typeof extras.kind === 'string' ? extras.kind : null
      if (role === null || kind === null) {
        mesh.visible = false
        return
      }
      mesh.geometry = sharedGeometry(mesh.geometry)
      if (role === 'DEVELOPMENT') {
        mesh.material = [TUNNEL_MATERIAL]
        const raw = Array.isArray(extras.ranges) ? (extras.ranges as Record<string, unknown>[]) : []
        tubes.push({
          mesh,
          kind,
          ranges: raw
            .filter(
              (r) =>
                typeof r.pieceId === 'string' &&
                Number.isInteger(r.indexOffset) &&
                Number.isInteger(r.indexCount),
            )
            .map((r) => ({
              pieceId: r.pieceId as string,
              indexOffset: r.indexOffset as number,
              indexCount: r.indexCount as number,
            })),
        })
      } else {
        mesh.material = CAP_MATERIAL
        caps.push({ mesh, kind })
      }
    })
    return { root, tubes, caps }
  }, [gltf])
  useEffect(() => {
    const active = new Set(plan?.status === 'VALID' ? plan.activePieceIds : [])
    const kinds = new Set(plan?.status === 'VALID' ? plan.activeKinds : [])
    for (const t of prepared.tubes) {
      const g = t.mesh.geometry
      g.clearGroups()
      let shown = 0
      for (const r of [...t.ranges].sort((a, b) => a.indexOffset - b.indexOffset)) {
        if (!active.has(r.pieceId)) continue
        g.addGroup(r.indexOffset, r.indexCount, 0)
        shown += r.indexCount
      }
      t.mesh.visible = shown > 0
    }
    for (const c of prepared.caps) c.mesh.visible = kinds.has(c.kind as never)
  }, [plan, prepared])
  if (!plan || plan.status !== 'VALID') return null
  return (
    <group rotation={[-Math.PI / 2, 0, 0]}>
      <primitive object={prepared.root} />
    </group>
  )
}
