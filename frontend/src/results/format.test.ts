import { describe, expect, it } from 'vitest'
import {
  COMPATIBILITY_LABEL,
  formatResultTime,
  fmtValue,
  resultTitle,
  STALE_TEXT,
  timeAxisLabel,
} from './format'
import { VENT_STALE, VENT_SUMMARY } from './results.fixture'

describe('result clock formatting', () => {
  it('reads MINE_DAY as "Mine day 123.4" and seconds as t = … s, static has no clock', () => {
    expect(formatResultTime('MINE_DAY', 123.44)).toBe('Mine day 123.4')
    expect(formatResultTime('ELAPSED_SECONDS', 123.6)).toBe('t = 124 s')
    expect(formatResultTime('STATIC', null)).toBe('static (no time axis)')
    expect(formatResultTime('STATIC', 5)).toBe('static (no time axis)')
    expect(timeAxisLabel('MINE_DAY')).toBe('Mine day')
  })

  it('carries the exact STALE wording', () => {
    expect(STALE_TEXT).toBe('STALE — this result was generated from an older mine snapshot')
    expect(COMPATIBILITY_LABEL.STALE).toBe('Stale')
  })

  it('titles a result by its run label, else by its source application', () => {
    expect(resultTitle(VENT_SUMMARY)).toBe('Base case')
    expect(resultTitle(VENT_STALE)).toBe('Ventsim result')
    expect(fmtValue(null)).toBe('—')
    expect(fmtValue(1234.5)).toBe('1235')
    expect(fmtValue(0.123456)).toBe('0.12')
  })
})
