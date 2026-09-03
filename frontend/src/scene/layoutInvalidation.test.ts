/**
 * Phase 20A frontend mirrors of the Effective Ramp source resolution and
 * invalidation contract (rules 149–151). The backend deletes the files;
 * these helpers must keep the in-memory manifest consistent with it.
 */
import { describe, expect, it } from 'vitest'
import type {
  LayoutV2Catalogue,
  RampSourceSummary,
  SmoothedDeclinePayload,
  WorldScene,
} from '@/types/scene'
import {
  afterLayoutRegen,
  afterLayoutSelect,
  afterLegacySmoothRegen,
  afterLegacyUpstreamRegen,
  afterRampSourceChange,
} from './invalidation'

function ramp(id: string | null, source: 'LEGACY' | 'PARAMETRIC'): SmoothedDeclinePayload {
  return {
    status: 'SUCCESS',
    failureReason: null,
    candidateId: id,
    family: source === 'PARAMETRIC' ? 'SPIRAL' : null,
    sourceKind: source === 'PARAMETRIC' ? 'PARAMETRIC_V2' : 'LEGACY_SMOOTHED',
    owningArtifact: source === 'PARAMETRIC' ? 'layout_v2_selected.json' : 'decline_smoothed.json',
    layoutRevision: source === 'PARAMETRIC' ? 'rev1' : undefined,
    segments: [
      {
        levelId: 'L01',
        effectiveSource: source === 'PARAMETRIC' ? 'PARAMETRIC_V2' : 'SMOOTHED',
        effectiveCenterline: { points: [0, 0, 0, 1, 0, -0.1], pointCount: 2 },
      },
    ],
  } as unknown as SmoothedDeclinePayload
}

function rampSource(
  active: 'LEGACY' | 'LAYOUT_V2',
  over: Partial<RampSourceSummary> = {},
): RampSourceSummary {
  return {
    activeSource: active,
    owningArtifact: active === 'LEGACY' ? 'decline_smoothed.json' : 'layout_v2_selected.json',
    available: true,
    legacyAvailable: true,
    layoutV2Available: true,
    layoutV2Selected: true,
    sourceKind: active === 'LEGACY' ? 'LEGACY_SMOOTHED' : 'PARAMETRIC_V2',
    sourceRevision: 'r',
    candidateId: active === 'LEGACY' ? null : 'SPIRAL-n1-CW-e+0-g0.120',
    family: active === 'LEGACY' ? null : 'SPIRAL',
    status: 'SUCCESS',
    segmentCount: 1,
    ...over,
  }
}

const DOWNSTREAM = [
  'tunnelMesh',
  'levels',
  'network',
  'stopes',
  'timeline',
  'communication',
  'sensors',
] as const

function scene(active: 'LEGACY' | 'LAYOUT_V2'): WorldScene {
  const legacy = ramp(null, 'LEGACY')
  const selected = ramp('SPIRAL-n1-CW-e+0-g0.120', 'PARAMETRIC')
  return {
    scenarioId: 'S',
    accessTargets: { tag: 't' },
    decline: { tag: 'd' },
    legacySmoothedDecline: legacy,
    layoutV2: { winnerId: 'SPIRAL-n1-CW-e+0-g0.120', candidates: [] },
    layoutV2Selected: selected,
    levelAccesses: { status: 'SUCCESS', candidateId: 'SPIRAL-n1-CW-e+0-g0.120', accesses: [] },
    smoothedDecline: active === 'LEGACY' ? legacy : selected,
    rampSource: rampSource(active),
    tunnelMesh: { tag: 'm' },
    levels: { tag: 'l' },
    network: { tag: 'n' },
    stopes: { tag: 's' },
    timeline: { tag: 'tl' },
    communication: { tag: 'c' },
    sensors: { tag: 'se' },
  } as unknown as WorldScene
}

function expectDownstreamCleared(s: WorldScene) {
  for (const k of DOWNSTREAM) expect(s[k]).toBeNull()
}

function expectDownstreamKept(s: WorldScene, from: WorldScene) {
  for (const k of DOWNSTREAM) expect(s[k]).toBe(from[k])
}

describe('ramp source switch (rule 150/151)', () => {
  it('switching LEGACY → LAYOUT_V2 makes the selection the effective ramp and clears the chain', () => {
    const before = scene('LEGACY')
    const after = afterRampSourceChange(before, rampSource('LAYOUT_V2'))
    expect(after.rampSource.activeSource).toBe('LAYOUT_V2')
    expect(after.smoothedDecline?.candidateId).toBe('SPIRAL-n1-CW-e+0-g0.120')
    expect(after.smoothedDecline?.activeSource).toBe('LAYOUT_V2')
    expectDownstreamCleared(after)
    // geology / legacy artifacts untouched
    expect(after.legacySmoothedDecline).toBe(before.legacySmoothedDecline)
    expect(after.decline).toBe(before.decline)
    expect(after.accessTargets).toBe(before.accessTargets)
    expect(after.layoutV2).toBe(before.layoutV2)
  })

  it('switching back exposes the legacy artifact again', () => {
    const after = afterRampSourceChange(scene('LAYOUT_V2'), rampSource('LEGACY'))
    expect(after.smoothedDecline).toBe(after.legacySmoothedDecline)
    expect(after.smoothedDecline?.sourceKind).toBe('LEGACY_SMOOTHED')
    expectDownstreamCleared(after)
  })

  it('a same-source response is not an identity change', () => {
    const before = scene('LAYOUT_V2')
    const after = afterRampSourceChange(before, rampSource('LAYOUT_V2'))
    expectDownstreamKept(after, before)
  })

  it('LAYOUT_V2 without a selection has no effective ramp', () => {
    const before = { ...scene('LEGACY'), layoutV2Selected: null }
    const after = afterRampSourceChange(before, rampSource('LAYOUT_V2', { available: false }))
    expect(after.smoothedDecline).toBeNull()
  })
})

describe('layout catalogue regeneration', () => {
  const catalogue = { winnerId: 'X', candidates: [] } as unknown as LayoutV2Catalogue

  it('drops the stale selection; with LEGACY active the chain survives', () => {
    const before = scene('LEGACY')
    const after = afterLayoutRegen(before, catalogue)
    expect(after.layoutV2).toBe(catalogue)
    expect(after.layoutV2Selected).toBeNull()
    expect(after.levelAccesses).toBeNull()
    expect(after.rampSource.layoutV2Selected).toBe(false)
    expect(after.smoothedDecline).toBe(before.legacySmoothedDecline)
    expectDownstreamKept(after, before)
  })

  it('with LAYOUT_V2 active the effective ramp and its chain are gone', () => {
    const after = afterLayoutRegen(scene('LAYOUT_V2'), catalogue)
    expect(after.smoothedDecline).toBeNull()
    expect(after.rampSource.available).toBe(false)
    expectDownstreamCleared(after)
  })
})

describe('candidate selection', () => {
  const other = ramp('SWITCHBACK-k2-p+0-CW-g0.120', 'PARAMETRIC')

  it('is inert while LEGACY is active', () => {
    const before = scene('LEGACY')
    const after = afterLayoutSelect(before, other)
    expect(after.layoutV2Selected).toBe(other)
    expect(after.smoothedDecline).toBe(before.smoothedDecline)
    expectDownstreamKept(after, before)
  })

  it('replaces the active layout-v2 ramp and clears the chain', () => {
    const after = afterLayoutSelect(scene('LAYOUT_V2'), other)
    expect(after.smoothedDecline?.candidateId).toBe('SWITCHBACK-k2-p+0-CW-g0.120')
    expect(after.rampSource.candidateId).toBe('SWITCHBACK-k2-p+0-CW-g0.120')
    expect(after.rampSource.sourceKind).toBe('PARAMETRIC_V2')
    expectDownstreamCleared(after)
  })

  it('re-selecting the active candidate at the same revision is a no-op', () => {
    const before = scene('LAYOUT_V2')
    const after = afterLayoutSelect(before, ramp('SPIRAL-n1-CW-e+0-g0.120', 'PARAMETRIC'))
    expectDownstreamKept(after, before)
  })
})

describe('legacy pipeline while LAYOUT_V2 is active', () => {
  it('re-smoothing updates the legacy artifact only', () => {
    const before = scene('LAYOUT_V2')
    const fresh = ramp(null, 'LEGACY')
    const after = afterLegacySmoothRegen(before, fresh)
    expect(after.legacySmoothedDecline?.sourceKind).toBe('LEGACY_SMOOTHED')
    expect(after.smoothedDecline).toBe(before.smoothedDecline)
    expectDownstreamKept(after, before)
  })

  it('re-smoothing with LEGACY active replaces the effective ramp and clears the chain', () => {
    const before = scene('LEGACY')
    const fresh = {
      ...ramp(null, 'LEGACY'),
      segments: [{ ...ramp(null, 'LEGACY').segments[0]!, effectiveSource: 'RAW_FALLBACK' }],
    } as SmoothedDeclinePayload
    const after = afterLegacySmoothRegen(before, fresh)
    expect(after.smoothedDecline?.sourceKind).toBe('LEGACY_RAW_FALLBACK')
    expect(after.smoothedDecline).toBe(after.legacySmoothedDecline)
    expect(after.rampSource.sourceKind).toBe('LEGACY_RAW_FALLBACK')
    expectDownstreamCleared(after)
  })

  it('legacy upstream regeneration never touches a LAYOUT_V2 chain', () => {
    const before = scene('LAYOUT_V2')
    const after = afterLegacyUpstreamRegen(before)
    expect(after.legacySmoothedDecline).toBeNull()
    expect(after.smoothedDecline).toBe(before.smoothedDecline)
    expectDownstreamKept(after, before)
    const legacyAfter = afterLegacyUpstreamRegen(scene('LEGACY'))
    expect(legacyAfter.smoothedDecline).toBeNull()
    expectDownstreamCleared(legacyAfter)
  })
})
