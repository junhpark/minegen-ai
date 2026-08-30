/**
 * Walkthrough interactable-asset resolver (rules 106/103).
 *
 * Phase 14 interactables are ONLY backend-authored MESH_ROUTER and
 * GAS_SENSOR selected assets, resolved through their authoritative
 * candidate → MineNetwork references. The walkthrough is decline-only, so
 * eligibility is topological, never Euclidean proximity:
 *   EDGE candidate  → owning edge type must be RAMP
 *   NODE candidate  → node must be incident to at least one RAMP edge
 * Assets in DRIFT/CROSSCUT-only domains are excluded (no fake access).
 *
 * Malformed references are skipped with a recorded issue (never a crash);
 * duplicate asset ids are deterministically rejected (first occurrence
 * wins, later duplicates recorded). Missing/failed payloads yield an empty
 * list so the walkthrough itself keeps working.
 */
import { mineToThree } from '@/geometry/coordinateTransform'
import type { WorldScene } from '@/types/scene'

export type InteractableKind = 'MESH_ROUTER' | 'GAS_SENSOR'
export type InteractableSource = 'COMMUNICATION' | 'SENSOR'

export interface WalkthroughInteractableAsset {
  id: string
  kind: InteractableKind
  source: InteractableSource
  candidateId: string
  positionMine: [number, number, number]
  positionThree: [number, number, number]
}

export interface WalkthroughAssetResolution {
  assets: WalkthroughInteractableAsset[]
  issues: string[]
}

interface CandidateRef {
  locationKind: 'NODE' | 'EDGE'
  nodeId: string | null
  edgeId: string | null
}

export function resolveWalkthroughAssets(
  scene: WorldScene | null | undefined,
): WalkthroughAssetResolution {
  const assets: WalkthroughInteractableAsset[] = []
  const issues: string[] = []
  const network = scene?.network
  if (!scene || !network || network.status !== 'SUCCESS') return { assets, issues }

  const edgeType = new Map<string, string>()
  for (const e of network.edges) edgeType.set(e.id, e.type)
  const rampNodes = new Set<string>()
  for (const e of network.edges) {
    if (e.type === 'RAMP') {
      rampNodes.add(e.fromNode)
      rampNodes.add(e.toNode)
    }
  }

  const eligible = (candidate: CandidateRef | undefined, assetId: string): boolean => {
    if (!candidate) {
      issues.push(`${assetId}: candidate reference not found`)
      return false
    }
    if (candidate.locationKind === 'EDGE') {
      if (!candidate.edgeId || !edgeType.has(candidate.edgeId)) {
        issues.push(`${assetId}: owning edge not found`)
        return false
      }
      return edgeType.get(candidate.edgeId) === 'RAMP'
    }
    if (!candidate.nodeId) {
      issues.push(`${assetId}: node candidate lacks nodeId`)
      return false
    }
    return rampNodes.has(candidate.nodeId)
  }

  const seen = new Set<string>()
  const push = (
    id: string,
    kind: InteractableKind,
    source: InteractableSource,
    candidateId: string,
    position: [number, number, number],
    candidate: CandidateRef | undefined,
  ) => {
    if (seen.has(id)) {
      issues.push(`duplicate asset id ${id} rejected`)
      return
    }
    if (!eligible(candidate, id)) return
    seen.add(id)
    assets.push({
      id,
      kind,
      source,
      candidateId,
      positionMine: position,
      positionThree: mineToThree(...position),
    })
  }

  const communication = scene.communication
  if (communication?.status === 'SUCCESS') {
    const candById = new Map(communication.candidates.map((c) => [c.id, c]))
    for (const a of communication.selectedAssets) {
      if (a.assetType !== 'MESH_ROUTER') continue
      push(
        a.id,
        'MESH_ROUTER',
        'COMMUNICATION',
        a.candidateId,
        a.position,
        candById.get(a.candidateId),
      )
    }
  }
  const sensors = scene.sensors
  if (sensors?.status === 'SUCCESS') {
    const candById = new Map(sensors.candidates.map((c) => [c.id, c]))
    for (const s of sensors.selectedSensors) {
      if (s.assetType !== 'GAS_SENSOR') continue
      push(s.id, 'GAS_SENSOR', 'SENSOR', s.candidateId, s.position, candById.get(s.candidateId))
    }
  }
  return { assets, issues }
}
