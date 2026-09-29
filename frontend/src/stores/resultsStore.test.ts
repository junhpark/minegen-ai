import { beforeEach, describe, expect, it } from 'vitest'
import { useResultsStore } from './resultsStore'

const axis = { kind: 'ELAPSED_SECONDS', unit: 's', sampleCount: 3, start: 10, end: 610 } as const

beforeEach(() => useResultsStore.setState(useResultsStore.getInitialState()))

describe('results store', () => {
  it('activating a result starts its clock at the axis start and drops the previous overlay', () => {
    const s = useResultsStore.getState()
    s.setVentilationOverlay({
      resultId: 'x',
      geometry: { resultId: 'x', coordinateFrame: 'LOCAL_ENU_Z_UP', edges: [] },
      frame: {
        resultId: 'x',
        metric: 'airflowM3s',
        unit: 'm3/s',
        timeAxisKind: 'STATIC',
        time: null,
        sampleTime: null,
        values: [],
        missingEdgeIds: [],
        min: null,
        max: null,
        signConvention: null,
      },
    })
    s.setActiveVentilation('aaaaaaaaaaaaaaaa', axis)
    expect(useResultsStore.getState().ventilationTime).toBe(10)
    expect(useResultsStore.getState().ventilationOverlay).toBeNull()
    expect(useResultsStore.getState().ventilationOverlayError).toBeNull()
  })

  it('clamps the clock to the axis and pauses on activation', () => {
    const s = useResultsStore.getState()
    s.setActiveOperations('bbbbbbbbbbbbbbbb', axis)
    s.playOperations()
    s.setOperationsTime(10_000)
    expect(useResultsStore.getState().operationsTime).toBe(610)
    s.setOperationsTime(-1)
    expect(useResultsStore.getState().operationsTime).toBe(10)
    s.setActiveOperations('cccccccccccccccc', axis)
    expect(useResultsStore.getState().operationsPlaying).toBe(false)
    s.setActiveOperations(null, null)
    s.setOperationsTime(50)
    expect(useResultsStore.getState().operationsTime).toBe(0)
  })

  it('activation chooses the metric from what the result CARRIES (B2)', () => {
    const s = useResultsStore.getState()
    // default airflow, pressure-only result → pressure is requested first
    s.setActiveVentilation('dddddddddddddddd', axis, ['pressurePa'])
    expect(useResultsStore.getState().ventilationMetric).toBe('pressurePa')
    expect(useResultsStore.getState().ventilationMetrics).toEqual(['pressurePa'])
    // the current metric is kept when the next result carries it
    s.setActiveVentilation('eeeeeeeeeeeeeeee', axis, ['airflowM3s', 'pressurePa'])
    expect(useResultsStore.getState().ventilationMetric).toBe('pressurePa')
    // deactivation clears the carried list and keeps the metric
    s.setActiveVentilation(null, null)
    expect(useResultsStore.getState().ventilationMetrics).toEqual([])
    expect(useResultsStore.getState().ventilationMetric).toBe('pressurePa')
    s.setActiveOperations('ffffffffffffffff', axis, ['queueCount'])
    expect(useResultsStore.getState().operationsMetric).toBe('queueCount')
    // a result carrying no edge metric keeps the current metric (nothing to request)
    s.setActiveOperations('0000000000000000', axis, [])
    expect(useResultsStore.getState().operationsMetric).toBe('queueCount')
  })

  it('changing the ventilation metric drops the previous metric frame (B2)', () => {
    const s = useResultsStore.getState()
    s.setActiveVentilation('aaaaaaaaaaaaaaaa', axis, ['airflowM3s', 'pressurePa'])
    s.setVentilationOverlay({
      resultId: 'aaaaaaaaaaaaaaaa',
      geometry: { resultId: 'aaaaaaaaaaaaaaaa', coordinateFrame: 'LOCAL_ENU_Z_UP', edges: [] },
      frame: {
        resultId: 'aaaaaaaaaaaaaaaa',
        metric: 'airflowM3s',
        unit: 'm3/s',
        timeAxisKind: 'STATIC',
        time: null,
        sampleTime: null,
        values: [],
        missingEdgeIds: [],
        min: null,
        max: null,
        signConvention: null,
      },
    })
    s.setVentilationMetric('pressurePa')
    expect(useResultsStore.getState().ventilationOverlay).toBeNull()
    expect(useResultsStore.getState().ventilationOverlayError).toBeNull()
  })

  it('changing a metric clears the manual range; reset restores the defaults', () => {
    const s = useResultsStore.getState()
    s.setVentilationRange({ min: 1, max: 2 })
    s.setVentilationMetric('pressurePa')
    expect(useResultsStore.getState().ventilationRange).toBeNull()
    expect(useResultsStore.getState().ventilationMetric).toBe('pressurePa')
    s.setShowAirflowArrows(false)
    s.setOperationsSpeed(60)
    s.reset()
    const after = useResultsStore.getState()
    expect(after.showAirflowArrows).toBe(true)
    expect(after.operationsSpeed).toBe(10)
    expect(after.ventilationMetric).toBe('airflowM3s')
    expect(after.activeVentilationResultId).toBeNull()
  })
})
