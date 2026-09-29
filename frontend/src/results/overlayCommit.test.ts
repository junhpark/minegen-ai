import { describe, expect, it } from 'vitest'
import { VENT_FRAME, VENT_PRESSURE_ONLY, VENT_SUMMARY } from './results.fixture'
import {
  availableOperationsMetrics,
  availableVentilationMetrics,
  selectMetric,
  ventilationFrameMatches,
  ventilationPlaceholder,
} from './overlayCommit'

describe('metric authority helpers (B2)', () => {
  it('available metrics follow the backend manifest in the canonical order', () => {
    expect(availableVentilationMetrics(VENT_SUMMARY)).toEqual(['airflowM3s'])
    expect(availableVentilationMetrics(VENT_PRESSURE_ONLY)).toEqual(['pressurePa'])
    expect(availableOperationsMetrics(VENT_SUMMARY)).toEqual([])
    expect(
      availableVentilationMetrics({
        ...VENT_SUMMARY,
        metrics: [
          { name: 'pressurePa', unit: 'Pa', available: true, sampleCount: 1, min: 0, max: 1 },
          { name: 'airflowM3s', unit: 'm3/s', available: true, sampleCount: 1, min: 0, max: 1 },
          { name: 'bogus', unit: '?', available: true, sampleCount: 1, min: 0, max: 1 },
        ],
      }),
    ).toEqual(['airflowM3s', 'pressurePa'])
  })

  it('selectMetric keeps an available current metric, else the first available', () => {
    expect(selectMetric('airflowM3s', ['pressurePa'])).toBe('pressurePa')
    expect(selectMetric('pressurePa', ['airflowM3s', 'pressurePa'])).toBe('pressurePa')
    expect(selectMetric('airflowM3s', [])).toBe('airflowM3s')
  })

  it('a cached frame is a placeholder only for the SAME metric', () => {
    expect(ventilationPlaceholder(VENT_FRAME, 'airflowM3s')).toBe(VENT_FRAME)
    expect(ventilationPlaceholder(VENT_FRAME, 'pressurePa')).toBeUndefined()
    expect(ventilationPlaceholder(undefined, 'airflowM3s')).toBeUndefined()
  })

  it('an airflow frame is never committed under the pressure selection', () => {
    expect(ventilationFrameMatches(VENT_FRAME, VENT_FRAME.resultId, 'airflowM3s')).toBe(true)
    expect(ventilationFrameMatches(VENT_FRAME, VENT_FRAME.resultId, 'pressurePa')).toBe(false)
    expect(ventilationFrameMatches(VENT_FRAME, 'other', 'airflowM3s')).toBe(false)
  })
})
