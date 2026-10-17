import { PRODUCTION_UNIT_NOUN, productionKindOf, productionUnitCount } from '@/scene/production'
import type { Scenario } from '@/types/api'
import type { WorldScene } from '@/types/scene'
import { STAGE_IDS, type StageId } from '@/types/workflow'
import { PREREQUISITE } from './workflow'
import { tr } from '@/i18n/t'

/**
 * Hardening PR-3 — the mine development FLOW as a node graph (pure).
 *
 *   Scenario → Method → Access → Layout → Levels ─┬→ Excavation
 *                                                 ├→ Shafts
 *                                                 ├→ Network ─┬→ Capability
 *                                                 │           ├→ Communication
 *                                                 │           └→ Sensors → Analysis → Export
 *                                                 └→ Production → Schedule
 *
 * The nodes are the workflow STAGES and the edges are the workflow
 * PREREQUISITE chain the stepper already used to decide what is NEXT — a
 * PRESENTATION of the guided order (rule 191), never a dependency graph of
 * its own: what a reset deletes is still the backend's registry closure,
 * asked per stage (rule 219). Layout: a node's column is the length of its
 * prerequisite chain (longest path from the root), its row the barycentre
 * order inside the column (prerequisite row, then stage order) — a
 * deterministic function of the stage table, so the graph is tested as
 * data. Each node also carries one short metric line read from the scene
 * manifest (counts and names the backend reports — nothing computed here).
 */

export interface FlowNode {
  stage: StageId
  column: number
  row: number
}

export interface FlowEdge {
  from: StageId
  to: StageId
}

export interface FlowLayout {
  nodes: readonly FlowNode[]
  edges: readonly FlowEdge[]
  columns: number
  /** the tallest column (rows) */
  rows: number
  /** node count per column, for vertical centring */
  rowsInColumn: readonly number[]
}

export const FLOW_EDGES: readonly FlowEdge[] = STAGE_IDS.flatMap((stage) => {
  const from = PREREQUISITE[stage]
  return from === undefined ? [] : [{ from, to: stage }]
})

export function flowLayout(): FlowLayout {
  const column = {} as Record<StageId, number>
  // STAGE_IDS is topological for PREREQUISITE (a prerequisite is always an
  // earlier stage), so one pass yields the longest path from the root
  for (const stage of STAGE_IDS) {
    const pre = PREREQUISITE[stage]
    column[stage] = pre === undefined ? 0 : column[pre] + 1
  }
  const columns = Math.max(...STAGE_IDS.map((s) => column[s])) + 1
  const row = {} as Record<StageId, number>
  const rowsInColumn: number[] = []
  for (let c = 0; c < columns; c += 1) {
    const members = STAGE_IDS.filter((s) => column[s] === c)
    const key = (s: StageId): [number, number] => {
      const pre = PREREQUISITE[s]
      return [pre === undefined ? 0 : row[pre], STAGE_IDS.indexOf(s)]
    }
    members.sort((a, b) => {
      const [pa, ia] = key(a)
      const [pb, ib] = key(b)
      return pa - pb || ia - ib
    })
    members.forEach((s, i) => {
      row[s] = i
    })
    rowsInColumn.push(members.length)
  }
  return {
    nodes: STAGE_IDS.map((stage) => ({ stage, column: column[stage], row: row[stage] })),
    edges: FLOW_EDGES,
    columns,
    rows: Math.max(...rowsInColumn),
    rowsInColumn,
  }
}

export interface FlowMetricInput {
  scenario: Scenario | null
  scene: WorldScene | null
  /** the viewer-completed stages of the current scene revision */
  completed: ReadonlySet<StageId>
}

// the count templates are dictionary keys (`'{n} levels'` → `'레벨 {n}개'`)
const plural = (n: number, noun: string, many = `${noun}s`): string =>
  tr(`{n} ${n === 1 ? noun : many}`, { n })

const failedOr = (a: { status: string } | null | undefined, text: () => string): string =>
  a == null ? '—' : a.status === 'SUCCESS' ? text() : tr('failed')

/** the one-line metric under a flow node: backend-reported names and counts */
export function flowMetric(stage: StageId, input: FlowMetricInput): string {
  const { scenario, scene } = input
  switch (stage) {
    case 'SCENARIO':
      return scenario ? `${scenario.name} · #${String(scenario.seed)}` : tr('no mine')
    case 'METHOD':
      return scene ? tr(scene.miningMethod.displayName) : '—'
    case 'ACCESS': {
      if (!scenario) return '—'
      const n = scenario.shafts?.specs.length ?? 0
      return n === 0 ? tr('Ramp only') : tr('Ramp + {shafts}', { shafts: plural(n, 'shaft') })
    }
    case 'LAYOUT': {
      if (!scene) return '—'
      if (scene.rampSource.available) {
        return scene.rampSource.activeSource === 'LAYOUT_V2'
          ? (scene.rampSource.candidateId ?? 'layout v2')
          : tr('legacy decline')
      }
      return scene.layoutV2
        ? tr('{feasible} / {total} feasible', {
            feasible: scene.layoutV2.feasibleCount,
            total: scene.layoutV2.candidateCount,
          })
        : '—'
    }
    case 'LEVELS':
      return failedOr(scene?.levels, () => plural(scene?.levels?.levels.length ?? 0, 'level'))
    case 'EXCAVATION': {
      const t = scene?.tunnelMesh ?? null
      const d = scene?.developmentMesh ?? null
      if (t?.status === 'FAILED' || d?.status === 'FAILED') return tr('failed')
      if (t && d) return tr('ramp + development')
      if (t) return tr('ramp tunnel')
      return '—'
    }
    case 'SHAFTS': {
      const declared = scenario?.shafts?.specs.length ?? 0
      if (!scene?.shafts) return scenario && declared === 0 ? tr('none declared') : '—'
      return failedOr(scene.shafts, () => {
        const n = scene.shafts?.metrics?.shaftCount ?? scene.shafts?.shafts.length ?? 0
        const mesh = scene.shaftMesh?.status === 'SUCCESS' ? ` ${tr('· mesh')}` : ''
        return `${plural(n, 'shaft')}${mesh}`
      })
    }
    case 'NETWORK':
      return failedOr(scene?.network, () =>
        plural(scene?.network?.metrics?.edgeCount ?? scene?.network?.edges.length ?? 0, 'edge'),
      )
    case 'CAPABILITY':
      return failedOr(scene?.capabilityGraph, () =>
        plural(scene?.capabilityGraph?.capabilities.length ?? 0, 'capability', 'capabilities'),
      )
    case 'PRODUCTION':
      return failedOr(scene?.stopes, () => {
        const payload = scene?.stopes
        if (!payload) return '—'
        const kind = productionKindOf(payload)
        // the unit noun of the kind is already plural ("stopes", "cuts", …)
        const noun = kind ? PRODUCTION_UNIT_NOUN[kind] : 'units'
        return tr('{n} {noun}', { n: productionUnitCount(payload), noun: tr(noun) })
      })
    case 'SCHEDULE':
      return failedOr(scene?.timeline, () =>
        tr('ends day {day}', { day: Math.round(scene?.timeline?.endDay ?? 0) }),
      )
    case 'COMMUNICATION':
      return failedOr(scene?.communication, () =>
        plural(scene?.communication?.selectedAssets.length ?? 0, 'router'),
      )
    case 'SENSORS':
      return failedOr(scene?.sensors, () =>
        plural(scene?.sensors?.selectedSensors.length ?? 0, 'sensor'),
      )
    case 'ANALYSIS':
      return input.completed.has(stage) ? tr('shown') : '—'
    case 'EXPORT':
      return input.completed.has(stage) ? tr('downloaded') : '—'
  }
}
