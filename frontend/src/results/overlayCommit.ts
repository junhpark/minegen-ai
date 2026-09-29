import {
  OPERATIONS_EDGE_METRICS,
  type OperationsEdgeMetric,
  type ResultSummary,
  VENTILATION_METRICS,
  type VentilationFrame,
  type VentilationMetric,
} from '@/types/results'

/**
 * Phase 23C (PR #51 review B2) — metric AUTHORITY is the backend result
 * manifest: the selector offers only the metrics the stored result actually
 * carries (`metrics[].available`), activation keeps the current metric only
 * when the result carries it (else the first available one), and a frame is
 * committed to the overlay only when it belongs to the ACTIVE result AND the
 * SELECTED metric — a previous metric's frame is never shown under a new
 * metric's label, not even as a placeholder.
 */
export function availableVentilationMetrics(r: ResultSummary): VentilationMetric[] {
  const names = new Set(r.metrics.filter((m) => m.available).map((m) => m.name))
  return VENTILATION_METRICS.filter((m) => names.has(m))
}

export function availableOperationsMetrics(r: ResultSummary): OperationsEdgeMetric[] {
  const names = new Set(r.metrics.filter((m) => m.available).map((m) => m.name))
  return OPERATIONS_EDGE_METRICS.filter((m) => names.has(m))
}

/** The metric to show once a result is activated: the current one if the
 *  result carries it, else the first available; the current one when the
 *  result declares none (nothing can be requested for it anyway). */
export function selectMetric<M extends string>(current: M, available: readonly M[]): M {
  if (available.length === 0) return current
  return available.includes(current) ? current : (available[0] ?? current)
}

/** A cached frame may stand in while a NEW TIME of the SAME metric loads;
 *  never across a metric change. */
export function ventilationPlaceholder(
  prev: VentilationFrame | undefined,
  metric: VentilationMetric,
): VentilationFrame | undefined {
  return prev && prev.metric === metric ? prev : undefined
}

/** Commit condition of a ventilation frame to the overlay. */
export function ventilationFrameMatches(
  frame: VentilationFrame,
  resultId: string,
  metric: VentilationMetric,
): boolean {
  return frame.resultId === resultId && frame.metric === metric
}
