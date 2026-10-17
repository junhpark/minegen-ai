import { describe, expect, it } from 'vitest'
import type { LayoutCandidateSummary, LayoutV2Catalogue, RampSourceSummary } from '@/types/scene'
import {
  currentDesignLabel,
  optionBriefRows,
  optionLabel,
  optionSummaryLine,
  optionValue,
} from './candidateSummary'

const feasible = {
  candidateId: 'SPIRAL-n1-CW-e+0-g0.120',
  family: 'SPIRAL',
  parameters: {},
  status: 'FEASIBLE',
  stageReached: 'RANKED',
  failureReasons: [],
  failureDetail: null,
  shortlisted: true,
  rank: 1,
  screenedLevels: 13,
  accessibleLevels: 13,
  requiredLevels: 13,
  rampLevelReferences: [],
  access: {
    accessibleLevelCount: 13,
    levelCount: 13,
    totalAccessLength: 495.4,
    worstAccessLength: 60.2,
    maxAccessGradient: 0.118,
    minAccessPlanRadius: 18.0,
  },
  levelAccesses: null,
  diagnostics: {
    length3d: 3954.3,
    maxAbsGradient: 0.12,
    minPlanRadius: 18.8,
    cumulativeHeadingChangeDeg: 2520,
    headingReversalCount: 0,
  },
  scores: { development: 1.58, geology: 0.0, geometry: 3.62, total: 5.201 },
  clearance: {
    clearanceBasis: 'EXACT',
    conservativeMinimumClearance: 47.0,
    requiredClearance: 10.6,
    clearanceErrorBound: null,
  },
  cheapProxy: 4.9,
} as unknown as LayoutCandidateSummary

const infeasible = {
  ...feasible,
  candidateId: 'SWITCHBACK-k2-p+20-CW-g0.120',
  family: 'SWITCHBACK',
  status: 'INFEASIBLE',
  rank: null,
  accessibleLevels: null,
  screenedLevels: 9,
  failureReasons: ['LEVEL_ACCESS_INFEASIBLE'],
  failureDetail: 'L04: GRADE_LIMIT',
  scores: null,
  access: null,
} as unknown as LayoutCandidateSummary

describe('option rows (hardening PR-3 round 2)', () => {
  it('reads "Option n" for a ranked candidate and the id tail for an unranked one', () => {
    expect(optionLabel(feasible)).toBe('Option 1')
    expect(optionLabel(infeasible)).toBe('k2-p+20-CW-g0.120')
  })

  it('shows the total score, or the typed status when infeasible', () => {
    expect(optionValue(feasible)).toEqual({ text: '5.201', feasible: true })
    expect(optionValue(infeasible)).toEqual({ text: 'INFEASIBLE', feasible: false })
  })

  it('keeps ONE summary line: levels, ramp length, access length', () => {
    expect(optionSummaryLine(feasible)).toBe('13/13 accessible · ramp 3,954 m · access 495 m')
    expect(optionSummaryLine(infeasible)).toBe('9/13 screened · ramp 3,954 m')
  })

  it('moves the group scores, geometry, access, clearance and failure reasons into the detail', () => {
    const rows = optionBriefRows(feasible)
    expect(rows.map((r) => r.label)).toEqual([
      'Score',
      'By group',
      'Levels',
      'Ramp',
      'Geometry',
      'Access',
      'Clearance',
    ])
    expect(rows[0]?.value).toBe('5.201')
    expect(rows[1]?.value).toBe('D 1.58 · G 0.00 · M 3.62')
    expect(rows[2]?.value).toBe('13 of 13 accessible')
    expect(rows[3]?.value).toBe('3,954 m · 0 hairpins')
    expect(rows[4]?.value).toBe('grade ≤ 0.120 · R ≥ 18.8 m')
    expect(rows[5]?.value).toBe('495 m · worst 60 m · g ≤ 0.118')
    expect(rows[6]?.value).toBe('47.0 m ≥ 10.6 m (EXACT)')
    const bad = optionBriefRows(infeasible)
    expect(bad.map((r) => r.label)).toEqual([
      'Levels',
      'Ramp',
      'Geometry',
      'Clearance',
      'Why not',
      'Detail',
    ])
    expect(bad.find((r) => r.label === 'Why not')).toEqual({
      label: 'Why not',
      value: 'LEVEL_ACCESS_INFEASIBLE',
      tone: 'danger',
    })
  })

  it('names the current design as its option, never as a bare id when the catalogue knows it', () => {
    const catalogue = { candidates: [feasible, infeasible] } as unknown as LayoutV2Catalogue
    const src = (over: Partial<RampSourceSummary>): RampSourceSummary =>
      ({
        activeSource: 'LAYOUT_V2',
        available: true,
        candidateId: null,
        ...over,
      }) as RampSourceSummary
    expect(currentDesignLabel(catalogue, src({ candidateId: feasible.candidateId }))).toBe(
      'Option 1 · SPIRAL (active)',
    )
    expect(currentDesignLabel(null, src({ candidateId: feasible.candidateId }))).toBe(
      'Layout v2 · SPIRAL-n1-CW-e+0-g0.120 (active)',
    )
    expect(currentDesignLabel(catalogue, src({ activeSource: 'LEGACY' }))).toBe(
      'Legacy decline (Hybrid-A*) — advanced',
    )
    expect(currentDesignLabel(catalogue, src({ available: false }))).toBe('none yet')
    expect(currentDesignLabel(catalogue, null)).toBe('none yet')
  })
})
