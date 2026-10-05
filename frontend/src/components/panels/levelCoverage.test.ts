import { describe, expect, it } from 'vitest'
import type { LayoutV2Catalogue, LevelsPayload } from '@/types/scene'
import {
  catalogueExcludedLines,
  catalogueLevelSummary,
  excludedLevelLine,
  isServiceable,
  levelCoverageLines,
  unservedIntervalLine,
} from './levelCoverage'

const LEVELS: LevelsPayload = {
  status: 'SUCCESS',
  failureReason: null,
  sourceRevision: 'r',
  developments: [],
  levels: [],
  metrics: null,
  excludedLevels: [
    {
      levelId: 'L01',
      index: 0,
      elevation: 105.54,
      reason: 'NO_FOOTWALL_CONTACT_AT_LEVEL',
      overshootM: 2.12064,
      minimumTopMiningMarginM: 11.8653,
    },
  ],
  unservedIntervals: [
    {
      upperLevelId: 'L01',
      lowerLevelId: 'L02',
      upperElevation: 105.54,
      lowerElevation: 80.54,
      reason: 'NO_FOOTWALL_CONTACT_AT_LEVEL',
    },
  ],
}

describe('level coverage (hardening H0 §3.1)', () => {
  it('echoes the backend exclusion with its overshoot and the dip-aware hint', () => {
    const [line] = levelCoverageLines(LEVELS)
    expect(line).toBe(
      'Top level L01 excluded — footwall contact above orebody top (2.12 m). Minimum topMiningMargin for L01: 11.87 m',
    )
    expect(levelCoverageLines(LEVELS)[1]).toBe(
      'No production interval L01–L02 (footwall contact above orebody top)',
    )
  })

  it('is empty for null, pre-hardening and fully developed payloads', () => {
    expect(levelCoverageLines(null)).toEqual([])
    // pre-hardening artifact: the two keys are absent
    const preHardening: LevelsPayload = {
      status: 'SUCCESS',
      failureReason: null,
      sourceRevision: 'r',
      developments: [],
      levels: [],
      metrics: null,
    }
    expect(levelCoverageLines(preHardening)).toEqual([])
    expect(levelCoverageLines({ ...LEVELS, excludedLevels: [], unservedIntervals: [] })).toEqual([])
  })

  it('omits the hint and the overshoot when the backend reports none', () => {
    expect(
      excludedLevelLine({
        levelId: 'L07',
        index: 6,
        elevation: -20,
        reason: 'NO_LEVEL_ENTRY',
        overshootM: null,
        minimumTopMiningMarginM: null,
      }),
    ).toBe('Level L07 excluded — no level entry from the active ramp.')
    expect(
      unservedIntervalLine({
        upperLevelId: 'L06',
        lowerLevelId: 'L07',
        upperElevation: 5,
        lowerElevation: -20,
        reason: 'NO_OREBODY_SECTION_AT_LEVEL',
      }),
    ).toBe('No production interval L06–L07 (no orebody section at this elevation)')
  })

  it('reads the catalogue count as given and lists the excluded levels', () => {
    const catalogue = {
      requiredLevels: [
        {
          levelId: 'L01',
          index: 0,
          elevation: 105.5,
          hasOrebodySection: true,
          serviceable: false,
          exclusionReason: 'NO_FOOTWALL_CONTACT_AT_LEVEL',
          overshootM: 2.1206,
          minimumTopMiningMarginM: 11.865,
        },
        {
          levelId: 'L02',
          index: 1,
          elevation: 80.5,
          hasOrebodySection: true,
          serviceable: true,
          exclusionReason: null,
          overshootM: null,
          minimumTopMiningMarginM: null,
        },
        // pre-hardening shape: serviceable ⇔ hasOrebodySection
        { levelId: 'L03', index: 2, elevation: 55.5, hasOrebodySection: false },
      ],
      serviceableLevelCount: 1,
    } as unknown as LayoutV2Catalogue
    expect(catalogueLevelSummary(catalogue)).toBe('1/3 levels serviceable')
    expect(catalogue.requiredLevels.map(isServiceable)).toEqual([false, true, false])
    expect(catalogueExcludedLines(catalogue)).toEqual([
      'L01 excluded — footwall contact above orebody top (2.12 m); minimum topMiningMargin 11.87 m',
      'L03 excluded — no orebody section at this elevation',
    ])
  })
})
