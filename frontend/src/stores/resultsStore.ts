import { create } from 'zustand'
import type {
  OperationsEdgeMetric,
  OperationsFrame,
  ResultGeometryPayload,
  ResultTimeAxis,
  VentilationFrame,
  VentilationMetric,
} from '@/types/results'
import type { DisplayRange } from '@/results/colorScale'
import { selectMetric } from '@/results/overlayCommit'

export type ResultSpeed = 1 | 10 | 60

export interface VentilationOverlay {
  resultId: string
  geometry: ResultGeometryPayload
  frame: VentilationFrame
}

export interface OperationsOverlay {
  resultId: string
  geometry: ResultGeometryPayload
  frame: OperationsFrame
}

/**
 * Phase 23C — Simulation Results viewer state (frontend-only, never
 * persisted, scenario-scoped: `reset()` runs in every scenario transition).
 *
 * The RESULT CLOCK is separate from the MineTimeline day cursor: a ventilation
 * or operations result plays on its own time axis (STATIC | ELAPSED_SECONDS |
 * MINE_DAY) and never drives, and is never driven by, the 4D `currentDay`.
 * The overlays hold the last frames the backend served; the layers render
 * them and compute nothing.
 */
export interface ResultsState {
  activeVentilationResultId: string | null
  activeOperationsResultId: string | null
  ventilationMetric: VentilationMetric
  /** metrics the ACTIVE ventilation result carries (backend `metrics[].available`) */
  ventilationMetrics: VentilationMetric[]
  ventilationAxis: ResultTimeAxis | null
  ventilationTime: number
  ventilationRange: DisplayRange | null
  showAirflowArrows: boolean
  operationsMetric: OperationsEdgeMetric
  /** edge metrics the ACTIVE operations result carries */
  operationsMetrics: OperationsEdgeMetric[]
  operationsAxis: ResultTimeAxis | null
  operationsTime: number
  operationsPlaying: boolean
  operationsSpeed: ResultSpeed
  operationsRange: DisplayRange | null
  ventilationOverlay: VentilationOverlay | null
  operationsOverlay: OperationsOverlay | null
  ventilationOverlayError: string | null
  operationsOverlayError: string | null

  setActiveVentilation: (
    resultId: string | null,
    axis: ResultTimeAxis | null,
    metrics?: VentilationMetric[],
  ) => void
  setActiveOperations: (
    resultId: string | null,
    axis: ResultTimeAxis | null,
    metrics?: OperationsEdgeMetric[],
  ) => void
  setVentilationMetric: (metric: VentilationMetric) => void
  setVentilationTime: (t: number) => void
  setVentilationRange: (range: DisplayRange | null) => void
  setShowAirflowArrows: (show: boolean) => void
  setOperationsMetric: (metric: OperationsEdgeMetric) => void
  setOperationsTime: (t: number) => void
  setOperationsRange: (range: DisplayRange | null) => void
  playOperations: () => void
  pauseOperations: () => void
  setOperationsSpeed: (speed: ResultSpeed) => void
  setVentilationOverlay: (overlay: VentilationOverlay | null, error?: string | null) => void
  setOperationsOverlay: (overlay: OperationsOverlay | null, error?: string | null) => void
  reset: () => void
}

const INITIAL = {
  activeVentilationResultId: null,
  activeOperationsResultId: null,
  ventilationMetric: 'airflowM3s' as VentilationMetric,
  ventilationMetrics: [] as VentilationMetric[],
  ventilationAxis: null,
  ventilationTime: 0,
  ventilationRange: null,
  showAirflowArrows: true,
  operationsMetric: 'utilization' as OperationsEdgeMetric,
  operationsMetrics: [] as OperationsEdgeMetric[],
  operationsAxis: null,
  operationsTime: 0,
  operationsPlaying: false,
  operationsSpeed: 10 as ResultSpeed,
  operationsRange: null,
  ventilationOverlay: null,
  operationsOverlay: null,
  ventilationOverlayError: null,
  operationsOverlayError: null,
}

function clamp(t: number, axis: ResultTimeAxis | null): number {
  if (!axis || axis.start === null || axis.end === null) return 0
  return Math.min(Math.max(t, axis.start), axis.end)
}

export const useResultsStore = create<ResultsState>()((set) => ({
  ...INITIAL,

  setActiveVentilation: (resultId, axis, metrics = []) =>
    set((s) => ({
      activeVentilationResultId: resultId,
      ventilationMetrics: resultId === null ? [] : metrics,
      // the metric is chosen from what the result CARRIES (B2): kept when
      // available, else the first available one
      ventilationMetric:
        resultId === null ? s.ventilationMetric : selectMetric(s.ventilationMetric, metrics),
      ventilationAxis: axis,
      ventilationTime: axis?.start ?? 0,
      ventilationOverlay: null,
      ventilationOverlayError: null,
      ventilationRange: null,
    })),
  setActiveOperations: (resultId, axis, metrics = []) =>
    set((s) => ({
      activeOperationsResultId: resultId,
      operationsMetrics: resultId === null ? [] : metrics,
      operationsMetric:
        resultId === null ? s.operationsMetric : selectMetric(s.operationsMetric, metrics),
      operationsAxis: axis,
      operationsTime: axis?.start ?? 0,
      operationsPlaying: false,
      operationsOverlay: null,
      operationsOverlayError: null,
      operationsRange: null,
    })),
  // a metric change drops the previous metric's frame: the overlay shows a
  // frame of the SELECTED metric or nothing (never a mixed label / data)
  setVentilationMetric: (ventilationMetric) =>
    set({
      ventilationMetric,
      ventilationRange: null,
      ventilationOverlay: null,
      ventilationOverlayError: null,
    }),
  setVentilationTime: (t) => set((s) => ({ ventilationTime: clamp(t, s.ventilationAxis) })),
  setVentilationRange: (ventilationRange) => set({ ventilationRange }),
  setShowAirflowArrows: (showAirflowArrows) => set({ showAirflowArrows }),
  setOperationsMetric: (operationsMetric) => set({ operationsMetric, operationsRange: null }),
  setOperationsTime: (t) => set((s) => ({ operationsTime: clamp(t, s.operationsAxis) })),
  setOperationsRange: (operationsRange) => set({ operationsRange }),
  playOperations: () => set({ operationsPlaying: true }),
  pauseOperations: () => set({ operationsPlaying: false }),
  setOperationsSpeed: (operationsSpeed) => set({ operationsSpeed }),
  setVentilationOverlay: (ventilationOverlay, error = null) =>
    set({ ventilationOverlay, ventilationOverlayError: error }),
  setOperationsOverlay: (operationsOverlay, error = null) =>
    set({ operationsOverlay, operationsOverlayError: error }),
  reset: () => set({ ...INITIAL }),
}))
