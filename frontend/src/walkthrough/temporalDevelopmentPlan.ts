/**
 * Temporal DEVELOPMENT traversal plan (hardening PR-4 W1a — the dark wall in
 * Park's Walk screenshot was the TIMELINE_SNAPSHOT aperture barrier that
 * closed every turnout because branch traversal was deferred, rule 187).
 *
 * The plan decides, for ONE captured snapshot day, which LEVEL_ACCESS /
 * DRIFT / CROSSCUT excavation pieces of the Phase 20B development GLB are
 * physically present — exactly the developments whose Phase 10 state is
 * ACTIVE (fully completed; rule 114's conservative volumetric contract,
 * never a DEVELOPING piece) — mapped through each development's
 * `geometryRef` to its OWNING artifact and the GLB `ranges` piece identity
 * (rule 173: LEVEL_ACCESS → `LEVEL_ACCESS:<levelId>`, DRIFT / CROSSCUT →
 * the levels.json development id). Where an ACTIVE excavation opens onto a
 * development that is NOT yet active, the opening is closed by an
 * ephemeral PLUG (rule 115 analogue, access-control geometry):
 *
 *   ACCESS_END      the access's OPEN end ring at the LEVEL_ENTRY when no
 *                   drift piece at the entry is active
 *   DRIFT_FACE      the shared ring plane between an active and an inactive
 *                   drift piece (also the entry plane when only one side of
 *                   the drift is active) — the unexcavated face
 *   CROSSCUT_MOUTH  the crosscut's aperture in the drift wall, flush with
 *                   the wall, when the drift is active and the crosscut is not
 *
 * The ramp → access turnout keeps the wall-line aperture barrier of
 * `apertureBarrier.ts` for a NOT-active access and opens for an ACTIVE one
 * (`openAccessLevelIds`). Topology comes from MineNetwork (node / edge ids,
 * endpoints, cross-sections); tangents from the owning centerlines. Every
 * inconsistency — an ACTIVE development without a GLB piece, an edge the
 * network lacks, a centerline end not welded to its node, an access active
 * before its ramp junction — fails CLOSED (rule 117): the temporal
 * walkthrough is unavailable rather than guessed. Pure and snapshot-stable.
 */
import { stateAt } from '@/timeline/evaluate'
import {
  rampSegmentId,
  type DevelopmentTimeline,
  type LevelAccessesPayload,
  type LevelsPayload,
  type NetworkEdge,
  type NetworkNode,
  type NetworkPayload,
  type SmoothedDeclinePayload,
  type TimelinePayload,
} from '@/types/scene'
import { LEVEL_ACCESSES_ARTIFACT, LEVELS_ARTIFACT } from '@/timeline/excavationReveal'
import { barrierPose, norm3, type Vec3 } from './barrierPose'
import type { DevelopmentKind } from './developmentRuntimeGeometry'

export const PLUG_HALF_DEPTH_M = 0.125
export const PLUG_MARGIN_M = 0.25
/** a centerline end must sit on its network node within this distance */
export const PLUG_WELD_TOLERANCE_M = 1e-3

export type TemporalPlugKind = 'ACCESS_END' | 'DRIFT_FACE' | 'CROSSCUT_MOUTH'

export interface TemporalPlug {
  colliderId: string
  kind: TemporalPlugKind
  /** the NOT-active development the plug closes (DRIFT_FACE / CROSSCUT_MOUTH)
   * or the active access whose end it closes (ACCESS_END) */
  edgeId: string
  nodeId: string
  positionThree: Vec3
  quaternion: [number, number, number, number]
  /** [width/2 + margin, height/2 + margin, half depth] */
  halfExtents: Vec3
  centerMine: Vec3
  forwardMine: Vec3
}

export interface TemporalDevelopmentPlan {
  /** NONE: no development is modelled (ramp-only temporal walk, the
   * pre-PR-4 contract); VALID: pieces + plugs resolved; INVALID: fail closed */
  status: 'NONE' | 'VALID' | 'INVALID'
  reason: string | null
  snapshotDay: number
  /** GLB piece ids whose development is ACTIVE at the day */
  activePieceIds: string[]
  /** kinds with at least one active piece (their batched cap primitive mounts) */
  activeKinds: DevelopmentKind[]
  /** levels whose LEVEL_ACCESS is ACTIVE: the ramp aperture stays open */
  openAccessLevelIds: string[]
  plugs: TemporalPlug[]
}

const DEVELOPMENT_EDGE_TYPES = new Set(['LEVEL_ACCESS', 'DRIFT', 'CROSSCUT'])

function invalid(day: number, reason: string): TemporalDevelopmentPlan {
  return {
    status: 'INVALID',
    reason,
    snapshotDay: day,
    activePieceIds: [],
    activeKinds: [],
    openAccessLevelIds: [],
    plugs: [],
  }
}

interface Resolved {
  dev: DevelopmentTimeline
  edge: NetworkEdge
  pieceId: string
  kind: DevelopmentKind
  points: number[]
  active: boolean
}

/** Owning-centerline points + GLB piece id of one development (rule 173). */
function resolveDevelopment(
  dev: DevelopmentTimeline,
  levels: LevelsPayload | null | undefined,
  accesses: LevelAccessesPayload | null | undefined,
): { pieceId: string; kind: DevelopmentKind; points: number[] } | string {
  const ref = dev.geometryRef
  const i = ref.segmentIndex
  if (!Number.isInteger(i) || i < 0) return `${dev.edgeId}: segmentIndex ${i} is invalid`
  if (dev.edgeType === 'LEVEL_ACCESS') {
    if (ref.artifact !== LEVEL_ACCESSES_ARTIFACT) {
      return `${dev.edgeId}: LEVEL_ACCESS owned by ${ref.artifact}`
    }
    const a = accesses?.accesses[i]
    if (!a || a.status !== 'OK' || !a.levelId || !a.centerline) {
      return `${dev.edgeId}: level access ${i} is not an OK access with a centerline`
    }
    return {
      pieceId: `LEVEL_ACCESS:${a.levelId}`,
      kind: 'LEVEL_ACCESS',
      points: a.centerline.points,
    }
  }
  if (ref.artifact !== LEVELS_ARTIFACT)
    return `${dev.edgeId}: ${dev.edgeType} owned by ${ref.artifact}`
  const d = levels?.developments[i]
  if (!d || !d.id || d.kind !== dev.edgeType) {
    return `${dev.edgeId}: levels development ${i} is not a ${dev.edgeType}`
  }
  return { pieceId: d.id, kind: d.kind, points: d.centerline.points }
}

/** Unit tangent pointing INTO the polyline at the end welded to `node`. */
function tangentInto(points: readonly number[], node: Vec3): Vec3 | null {
  const n = points.length / 3
  if (n < 2 || points.length % 3 !== 0) return null
  const first: Vec3 = [points[0]!, points[1]!, points[2]!]
  const last: Vec3 = [points[(n - 1) * 3]!, points[(n - 1) * 3 + 1]!, points[(n - 1) * 3 + 2]!]
  const dist = (a: Vec3) => Math.hypot(a[0] - node[0], a[1] - node[1], a[2] - node[2])
  if (dist(first) <= PLUG_WELD_TOLERANCE_M) {
    return norm3([points[3]! - first[0], points[4]! - first[1], points[5]! - first[2]])
  }
  if (dist(last) <= PLUG_WELD_TOLERANCE_M) {
    const k = (n - 2) * 3
    return norm3([points[k]! - last[0], points[k + 1]! - last[1], points[k + 2]! - last[2]])
  }
  return null
}

function plugAt(
  kind: TemporalPlugKind,
  edge: NetworkEdge,
  node: NetworkNode,
  forward: Vec3,
  distanceM: number,
): TemporalPlug | null {
  const w = edge.crossSection.width
  const h = edge.crossSection.height
  if (!(w > 0) || !(h > 0)) return null
  const pose = barrierPose(
    [
      node.position[0] + forward[0] * distanceM,
      node.position[1] + forward[1] * distanceM,
      node.position[2] + forward[2] * distanceM,
    ],
    forward,
  )
  if (!pose) return null
  // lift the centre by half the height along the gravity-aligned up
  const center: Vec3 = [
    pose.centerMine[0] + pose.upMine[0] * (h / 2),
    pose.centerMine[1] + pose.upMine[1] * (h / 2),
    pose.centerMine[2] + pose.upMine[2] * (h / 2),
  ]
  const lifted = barrierPose(center, forward)
  if (!lifted) return null
  return {
    colliderId: `WALK:TEMPORAL:PLUG:${kind}:${edge.id}:${node.id}`,
    kind,
    edgeId: edge.id,
    nodeId: node.id,
    positionThree: lifted.positionThree,
    quaternion: lifted.quaternion,
    halfExtents: [w / 2 + PLUG_MARGIN_M, h / 2 + PLUG_MARGIN_M, PLUG_HALF_DEPTH_M],
    centerMine: lifted.centerMine,
    forwardMine: lifted.forwardMine,
  }
}

export function resolveTemporalDevelopmentPlan(
  timeline: TimelinePayload | null | undefined,
  levels: LevelsPayload | null | undefined,
  levelAccesses: LevelAccessesPayload | null | undefined,
  network: NetworkPayload | null | undefined,
  smoothed: SmoothedDeclinePayload | null | undefined,
  /** GLB piece identities (the validated `ranges` of every tube) */
  pieces: readonly { pieceId: string; kind: DevelopmentKind }[],
  snapshotDay: number,
  activeRampSegmentIds: readonly string[],
): TemporalDevelopmentPlan {
  const none: TemporalDevelopmentPlan = {
    status: 'NONE',
    reason: null,
    snapshotDay,
    activePieceIds: [],
    activeKinds: [],
    openAccessLevelIds: [],
    plugs: [],
  }
  if (!Number.isFinite(snapshotDay)) return invalid(snapshotDay, 'snapshot day is not finite')
  if (!timeline || timeline.status !== 'SUCCESS')
    return invalid(snapshotDay, 'timeline is not available')
  const devs = timeline.developments.filter((d) => DEVELOPMENT_EDGE_TYPES.has(d.edgeType))
  if (devs.length === 0) return none
  // the legacy chain develops levels without accesses and without junction
  // apertures (rule 154): its developments are never walkable in time
  if (!levelAccesses || levelAccesses.status !== 'SUCCESS') return none
  if (!network || network.status !== 'SUCCESS') {
    return invalid(snapshotDay, 'developments are scheduled but the network is unavailable')
  }
  const edgeById = new Map(network.edges.map((e) => [e.id, e]))
  const nodeById = new Map(network.nodes.map((n) => [n.id, n]))
  const pieceKind = new Map(pieces.map((p) => [p.pieceId, p.kind]))
  const resolved: Resolved[] = []
  const seenPieces = new Set<string>()
  for (const dev of devs) {
    const edge = edgeById.get(dev.edgeId)
    if (!edge) return invalid(snapshotDay, `${dev.edgeId}: network edge not found`)
    if (edge.type !== dev.edgeType) {
      return invalid(snapshotDay, `${dev.edgeId}: timeline ${dev.edgeType} vs network ${edge.type}`)
    }
    const r = resolveDevelopment(dev, levels, levelAccesses)
    if (typeof r === 'string') return invalid(snapshotDay, r)
    if (seenPieces.has(r.pieceId)) return invalid(snapshotDay, `${r.pieceId}: mapped twice`)
    seenPieces.add(r.pieceId)
    const active = stateAt(dev.initialState, dev.transitions, snapshotDay) === 'ACTIVE'
    if (active && pieceKind.get(r.pieceId) !== r.kind) {
      return invalid(snapshotDay, `${r.pieceId}: ACTIVE development has no ${r.kind} GLB piece`)
    }
    resolved.push({ dev, edge, pieceId: r.pieceId, kind: r.kind, points: r.points, active })
  }
  // precedence sanity (rule 160): an ACTIVE access needs its ramp junction
  // reached — the ramp segment ending at the junction node is ACTIVE
  const activeRamp = new Set(activeRampSegmentIds)
  const rampEndNode = new Map<string, string>() // junction node id → ramp segment id
  if (smoothed) {
    for (const seg of smoothed.segments) {
      const id = rampSegmentId(seg)
      if (seg.rampJunction?.levelId)
        rampEndNode.set(`RAMP_JUNCTION:${seg.rampJunction.levelId}`, id)
      else if (seg.segmentId) rampEndNode.set(seg.segmentId, id)
    }
  }
  const openAccessLevelIds: string[] = []
  for (const r of resolved) {
    if (r.kind !== 'LEVEL_ACCESS' || !r.active) continue
    const junctionNode = r.edge.fromNode
    const seg = rampEndNode.get(junctionNode)
    if (seg !== undefined && !activeRamp.has(seg)) {
      return invalid(snapshotDay, `${r.edge.id}: access ACTIVE before its ramp segment ${seg}`)
    }
    const levelId = r.pieceId.slice('LEVEL_ACCESS:'.length)
    openAccessLevelIds.push(levelId)
  }
  // plugs at every node where ACTIVE and NOT-active developments meet
  const incident = new Map<string, Resolved[]>()
  for (const r of resolved) {
    for (const nodeId of [r.edge.fromNode, r.edge.toNode]) {
      const list = incident.get(nodeId) ?? []
      list.push(r)
      incident.set(nodeId, list)
    }
  }
  const plugs: TemporalPlug[] = []
  const nodeIds = [...incident.keys()].sort()
  for (const nodeId of nodeIds) {
    const list = incident.get(nodeId)!
    const active = list.filter((r) => r.active)
    const inactive = list.filter((r) => !r.active)
    if (active.length === 0 || inactive.length === 0) continue
    const node = nodeById.get(nodeId)
    if (!node) return invalid(snapshotDay, `${nodeId}: network node not found`)
    const pos = node.position
    const accessOnly = active.every((r) => r.kind === 'LEVEL_ACCESS')
    if (accessOnly) {
      // the entry: close the access's own open end ring
      for (const a of active) {
        const tIn = tangentInto(a.points, pos)
        if (!tIn)
          return invalid(snapshotDay, `${a.edge.id}: centerline end not welded to ${nodeId}`)
        const outward: Vec3 = [-tIn[0], -tIn[1], -tIn[2]]
        const plug = plugAt('ACCESS_END', a.edge, node, outward, PLUG_HALF_DEPTH_M)
        if (!plug) return invalid(snapshotDay, `${a.edge.id}: degenerate access end at ${nodeId}`)
        plugs.push(plug)
      }
      continue
    }
    const hostDrift = active.find((r) => r.kind === 'DRIFT')
    for (const e of inactive) {
      if (e.kind === 'LEVEL_ACCESS') {
        if (e.edge.toNode === nodeId) {
          return invalid(snapshotDay, `${e.edge.id}: drift active before its access at ${nodeId}`)
        }
        continue // ramp junction: the wall-line aperture barrier closes it
      }
      const tIn = tangentInto(e.points, pos)
      if (!tIn) return invalid(snapshotDay, `${e.edge.id}: centerline end not welded to ${nodeId}`)
      if (e.kind === 'CROSSCUT') {
        const hostWidth = hostDrift?.edge.crossSection.width ?? e.edge.crossSection.width
        const plug = plugAt('CROSSCUT_MOUTH', e.edge, node, tIn, hostWidth / 2)
        if (!plug)
          return invalid(snapshotDay, `${e.edge.id}: degenerate crosscut mouth at ${nodeId}`)
        plugs.push(plug)
      } else {
        const plug = plugAt('DRIFT_FACE', e.edge, node, tIn, PLUG_HALF_DEPTH_M)
        if (!plug) return invalid(snapshotDay, `${e.edge.id}: degenerate drift face at ${nodeId}`)
        plugs.push(plug)
      }
    }
  }
  const ids = plugs.map((p) => p.colliderId)
  if (new Set(ids).size !== ids.length) return invalid(snapshotDay, 'plug ids collide')
  const activePieceIds = resolved.filter((r) => r.active).map((r) => r.pieceId)
  const activeKinds = [...new Set(resolved.filter((r) => r.active).map((r) => r.kind))]
  return {
    status: 'VALID',
    reason: null,
    snapshotDay,
    activePieceIds,
    activeKinds,
    openAccessLevelIds,
    plugs,
  }
}

/**
 * GLB-free projection of the plan for consumers that have no runtime
 * geometry (the minimap, the teleport list): the ACTIVE development piece
 * ids and the levels whose access is ACTIVE at `snapshotDay`, by the same
 * rule-173 mapping; null when the timeline / accesses are unusable or a
 * development does not resolve (the runtime then fails the session closed).
 */
export function temporalActiveDevelopment(
  timeline: TimelinePayload | null | undefined,
  levels: LevelsPayload | null | undefined,
  levelAccesses: LevelAccessesPayload | null | undefined,
  snapshotDay: number,
): { activePieceIds: string[]; openAccessLevelIds: string[] } | null {
  if (!Number.isFinite(snapshotDay) || !timeline || timeline.status !== 'SUCCESS') return null
  if (!levelAccesses || levelAccesses.status !== 'SUCCESS') {
    return { activePieceIds: [], openAccessLevelIds: [] }
  }
  const activePieceIds: string[] = []
  const openAccessLevelIds: string[] = []
  for (const dev of timeline.developments) {
    if (!DEVELOPMENT_EDGE_TYPES.has(dev.edgeType)) continue
    const r = resolveDevelopment(dev, levels, levelAccesses)
    if (typeof r === 'string') return null
    if (stateAt(dev.initialState, dev.transitions, snapshotDay) !== 'ACTIVE') continue
    activePieceIds.push(r.pieceId)
    if (r.kind === 'LEVEL_ACCESS') openAccessLevelIds.push(r.pieceId.slice('LEVEL_ACCESS:'.length))
  }
  return { activePieceIds, openAccessLevelIds }
}
