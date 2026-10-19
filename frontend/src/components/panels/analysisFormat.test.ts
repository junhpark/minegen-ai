import { describe, expect, it } from 'vitest'
import { DAYS_PER_YEAR, days, duration, durationParts } from './analysisFormat'

describe('duration readout (PR-3 round 3 — years with the days beside them)', () => {
  it('reads a mine duration in Julian years and keeps the backend days in parentheses', () => {
    expect(DAYS_PER_YEAR).toBe(365.25)
    expect(duration(3254)).toBe('8.9 yr (3,254 d)')
    expect(duration(120)).toBe('0.3 yr (120 d)')
    expect(duration(365.25)).toBe('1 yr (365 d)')
    expect(duration(null)).toBe('—')
    expect(duration(undefined)).toBe('—')
  })

  it('splits the same readout for a KPI tile; a milestone keeps the day readout', () => {
    expect(durationParts(3254)).toEqual({ years: '8.9 yr', days: '3,254 d' })
    expect(durationParts(null)).toBeNull()
    expect(days(298.18)).toBe('298.2 d')
  })
})
