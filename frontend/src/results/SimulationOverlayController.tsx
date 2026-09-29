import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { api, ApiError } from '@/api/client'
import { useResultsStore } from '@/stores/resultsStore'
import { useScenarioStore } from '@/stores/scenarioStore'
import { quantizeTime } from './overlayGeometry'

const errorText = (err: unknown): string | null =>
  err instanceof ApiError
    ? `${err.code}: ${err.message}`
    : err instanceof Error
      ? err.message
      : null

/**
 * Phase 23C — fetches the overlay data of the ACTIVE results (geometry once,
 * frames per metric / quantized clock time) OUTSIDE the R3F canvas and hands
 * the backend frames to the results store; the scene layers render them and
 * compute nothing. Frames are backend slices (`GET …/ventilation`,
 * `GET …/operations/frame`): the frontend never interpolates across edges
 * or invents a value, and a STALE result (RESULT_STALE) clears the overlay
 * with its typed reason.
 */
export function SimulationOverlayController() {
  const scenarioId = useScenarioStore((s) => s.scenario?.id ?? null)
  const ventId = useResultsStore((s) => s.activeVentilationResultId)
  const ventMetric = useResultsStore((s) => s.ventilationMetric)
  const ventAxis = useResultsStore((s) => s.ventilationAxis)
  const ventTime = useResultsStore((s) => s.ventilationTime)
  const opsId = useResultsStore((s) => s.activeOperationsResultId)
  const opsAxis = useResultsStore((s) => s.operationsAxis)
  const opsTime = useResultsStore((s) => s.operationsTime)
  const setVent = useResultsStore((s) => s.setVentilationOverlay)
  const setOps = useResultsStore((s) => s.setOperationsOverlay)

  const ventStatic = ventAxis?.kind === 'STATIC' || ventAxis === null
  const ventT =
    ventStatic || ventAxis.start === null || ventAxis.end === null
      ? null
      : quantizeTime(ventTime, ventAxis.start, ventAxis.end)
  const opsT =
    opsAxis && opsAxis.start !== null && opsAxis.end !== null
      ? quantizeTime(opsTime, opsAxis.start, opsAxis.end)
      : 0

  const ventGeometry = useQuery({
    queryKey: ['simulation-result', scenarioId, ventId, 'geometry'],
    queryFn: () => api.getSimulationResultGeometry(scenarioId ?? '', ventId ?? ''),
    enabled: scenarioId !== null && ventId !== null,
    retry: false,
    staleTime: Infinity,
  })
  const ventFrame = useQuery({
    queryKey: ['simulation-result-frame', scenarioId, ventId, ventMetric, ventT],
    queryFn: () => api.getVentilationFrame(scenarioId ?? '', ventId ?? '', ventMetric, ventT),
    enabled: scenarioId !== null && ventId !== null,
    retry: false,
    staleTime: Infinity,
    placeholderData: (prev) => prev,
  })
  const opsGeometry = useQuery({
    queryKey: ['simulation-result', scenarioId, opsId, 'geometry'],
    queryFn: () => api.getSimulationResultGeometry(scenarioId ?? '', opsId ?? ''),
    enabled: scenarioId !== null && opsId !== null,
    retry: false,
    staleTime: Infinity,
  })
  const opsFrame = useQuery({
    queryKey: ['simulation-result-frame', scenarioId, opsId, 'operations', opsT],
    queryFn: () => api.getOperationsFrame(scenarioId ?? '', opsId ?? '', opsT),
    enabled: scenarioId !== null && opsId !== null,
    retry: false,
    staleTime: Infinity,
    placeholderData: (prev) => prev,
  })

  useEffect(() => {
    if (ventId === null) return
    const err = ventGeometry.error ?? ventFrame.error
    if (err) {
      setVent(null, errorText(err))
      return
    }
    const geometry = ventGeometry.data
    const frame = ventFrame.data
    if (geometry && frame && geometry.resultId === ventId && frame.resultId === ventId) {
      setVent({ resultId: ventId, geometry, frame })
    }
  }, [ventId, ventGeometry.data, ventGeometry.error, ventFrame.data, ventFrame.error, setVent])

  useEffect(() => {
    if (opsId === null) return
    const err = opsGeometry.error ?? opsFrame.error
    if (err) {
      setOps(null, errorText(err))
      return
    }
    const geometry = opsGeometry.data
    const frame = opsFrame.data
    if (geometry && frame && geometry.resultId === opsId && frame.resultId === opsId) {
      setOps({ resultId: opsId, geometry, frame })
    }
  }, [opsId, opsGeometry.data, opsGeometry.error, opsFrame.data, opsFrame.error, setOps])

  return null
}
