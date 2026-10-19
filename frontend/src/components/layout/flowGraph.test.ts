import { describe, expect, it } from 'vitest'
import type { Scenario } from '@/types/api'
import type { WorldScene } from '@/types/scene'
import { STAGE_IDS, type StageId } from '@/types/workflow'
import { FLOW_EDGES, flowLayout, flowMetric } from './flowGraph'
import { PREREQUISITE } from './workflow'

describe('flow layout (hardening PR-3 — the development flow as a node graph)', () => {
  const layout = flowLayout()
  const column = Object.fromEntries(layout.nodes.map((n) => [n.stage, n.column])) as Record<
    StageId,
    number
  >
  const row = Object.fromEntries(layout.nodes.map((n) => [n.stage, n.row])) as Record<
    StageId,
    number
  >

  it('has every stage exactly once and the prerequisite chain as its edges', () => {
    expect(layout.nodes.map((n) => n.stage)).toEqual([...STAGE_IDS])
    expect(layout.edges).toEqual(FLOW_EDGES)
    expect(FLOW_EDGES).toEqual(
      STAGE_IDS.filter((s) => PREREQUISITE[s] !== undefined).map((s) => ({
        from: PREREQUISITE[s],
        to: s,
      })),
    )
    expect(FLOW_EDGES).toHaveLength(14)
  })

  it('places every stage one column after its prerequisite (longest path from the root)', () => {
    for (const e of FLOW_EDGES) expect(column[e.to]).toBe(column[e.from] + 1)
    expect(column.SCENARIO).toBe(0)
    expect(column.LEVELS).toBe(4)
    expect(column.EXPORT).toBe(8)
    expect(layout.columns).toBe(9)
  })

  it('orders a column by the prerequisite row, then by stage order — deterministic, no shared cell', () => {
    expect(STAGE_IDS.filter((s) => column[s] === 5).map((s) => [s, row[s]] as const)).toEqual([
      ['EXCAVATION', 0],
      ['SHAFTS', 1],
      ['NETWORK', 2],
      ['PRODUCTION', 3],
    ])
    // the three Network children sit together (row 2 parents), the Schedule
    // under its Production parent (row 3)
    expect(
      STAGE_IDS.filter((s) => column[s] === 6)
        .sort((a, b) => row[a] - row[b])
        .map((s) => s),
    ).toEqual(['CAPABILITY', 'COMMUNICATION', 'SENSORS', 'SCHEDULE'])
    const cells = layout.nodes.map((n) => `${String(n.column)}:${String(n.row)}`)
    expect(new Set(cells).size).toBe(cells.length)
    expect(layout.rows).toBe(4)
    expect(layout.rowsInColumn.reduce((a, b) => a + b, 0)).toBe(STAGE_IDS.length)
    expect(flowLayout()).toEqual(layout)
  })
})

describe('flow node metrics (backend-reported names and counts only)', () => {
  const none = { scenario: null, scene: null, completed: new Set<StageId>() }

  it('reads "no mine" / "—" without a scenario or a world', () => {
    expect(flowMetric('SCENARIO', none)).toBe('no mine')
    expect(flowMetric('METHOD', none)).toBe('—')
    expect(flowMetric('ACCESS', none)).toBe('—')
    expect(flowMetric('LAYOUT', none)).toBe('—')
    expect(flowMetric('LEVELS', none)).toBe('—')
    expect(flowMetric('SHAFTS', none)).toBe('—')
    expect(flowMetric('ANALYSIS', none)).toBe('—')
    expect(flowMetric('EXPORT', none)).toBe('—')
  })

  const scenario = {
    name: 'Alpha',
    seed: 42,
    shafts: { specs: [{ shaftId: 'S1' }, { shaftId: 'S2' }] },
  } as unknown as Scenario
  const scene = {
    miningMethod: { displayName: 'Longhole Open Stoping' },
    rampSource: { available: true, activeSource: 'LAYOUT_V2', candidateId: 'SPIRAL-cw-g12' },
    layoutV2: { feasibleCount: 3, candidateCount: 12 },
    levels: { status: 'SUCCESS', levels: [{}, {}, {}] },
    tunnelMesh: { status: 'SUCCESS' },
    developmentMesh: { status: 'SUCCESS' },
    shafts: { status: 'SUCCESS', shafts: [{}], metrics: { shaftCount: 1 } },
    shaftMesh: { status: 'SUCCESS' },
    network: { status: 'SUCCESS', edges: [], metrics: { edgeCount: 37 } },
    capabilityGraph: { status: 'SUCCESS', capabilities: ['PERSONNEL', 'HAULAGE'] },
    stopes: { status: 'SUCCESS', method: 'LONGHOLE_OPEN_STOPING', stopes: [], metrics: null },
    timeline: { status: 'SUCCESS', endDay: 1094.6 },
    communication: { status: 'SUCCESS', selectedAssets: [{}, {}, {}] },
    sensors: { status: 'FAILED', selectedSensors: [] },
  } as unknown as WorldScene
  const input = { scenario, scene, completed: new Set<StageId>(['ANALYSIS']) }

  it('echoes the scene manifest per stage', () => {
    expect(flowMetric('SCENARIO', input)).toBe('Alpha · #42')
    expect(flowMetric('METHOD', input)).toBe('Longhole Open Stoping')
    expect(flowMetric('ACCESS', input)).toBe('Ramp + 2 shafts')
    expect(flowMetric('LAYOUT', input)).toBe('SPIRAL-cw-g12')
    expect(flowMetric('LEVELS', input)).toBe('3 levels')
    expect(flowMetric('EXCAVATION', input)).toBe('ramp + development')
    expect(flowMetric('SHAFTS', input)).toBe('1 shaft · mesh')
    expect(flowMetric('NETWORK', input)).toBe('37 edges')
    expect(flowMetric('CAPABILITY', input)).toBe('2 capabilities')
    expect(flowMetric('PRODUCTION', input)).toBe('0 stopes')
    expect(flowMetric('SCHEDULE', input)).toBe('ends day 1095')
    expect(flowMetric('COMMUNICATION', input)).toBe('3 routers')
    expect(flowMetric('SENSORS', input)).toBe('failed')
    expect(flowMetric('ANALYSIS', input)).toBe('shown')
    expect(flowMetric('EXPORT', input)).toBe('—')
  })

  it('reads the catalogue while no ramp is active, and "Ramp only" without shafts', () => {
    const noRamp = {
      ...input,
      scenario: { name: 'Beta', seed: 1, shafts: { specs: [] } } as unknown as Scenario,
      scene: {
        ...scene,
        rampSource: { available: false, activeSource: 'LAYOUT_V2', candidateId: null },
        shafts: null,
      } as unknown as WorldScene,
    }
    expect(flowMetric('LAYOUT', noRamp)).toBe('3 / 12 feasible')
    expect(flowMetric('ACCESS', noRamp)).toBe('Ramp only')
    expect(flowMetric('SHAFTS', noRamp)).toBe('none declared')
  })

  it('a FAILED artifact reads "failed", a legacy ramp reads "legacy decline"', () => {
    const failed = {
      ...input,
      scene: {
        ...scene,
        rampSource: { available: true, activeSource: 'LEGACY', candidateId: null },
        levels: { status: 'FAILED', levels: [] },
        developmentMesh: { status: 'FAILED' },
      } as unknown as WorldScene,
    }
    expect(flowMetric('LAYOUT', failed)).toBe('legacy decline')
    expect(flowMetric('LEVELS', failed)).toBe('failed')
    expect(flowMetric('EXCAVATION', failed)).toBe('failed')
  })
})
