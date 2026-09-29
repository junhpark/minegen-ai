import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '@/api/client'
import { availableOperationsMetrics, availableVentilationMetrics } from '@/results/overlayCommit'
import { useResultsStore } from '@/stores/resultsStore'
import { useScenarioStore } from '@/stores/scenarioStore'
import type { ResultSummary, SourceApplication } from '@/types/results'
import { saveFile } from '@/utils/download'
import { SimulationResultsBody } from './SimulationResultsBody'

const errorText = (err: unknown): string | null =>
  err instanceof ApiError
    ? `${err.code}: ${err.message}`
    : err instanceof Error
      ? err.message
      : null

/**
 * Phase 23C — the Simulation Results container (Analysis › Simulation
 * Results). ONE list query keyed on the scenario id, one import mutation
 * (a MineResult ZIP posted as-is; the backend binds it), one delete
 * mutation and the export download. Importing or deleting refreshes the
 * results list ONLY: no scenario epoch bump, no scene clear, no derived
 * invalidation — results are not mine artifacts. The active result ids, the
 * metric / range choices and the result clock live in `resultsStore`
 * (frontend-only, reset on every scenario transition); the overlay frames
 * are fetched by `SimulationOverlayController` outside the canvas. The
 * panel stays MOUNTED for every Analysis tab (§19) and renders only in its
 * own tab context.
 */
export function SimulationResultsPanel({ active }: { active: boolean }) {
  const scenarioId = useScenarioStore((s) => s.scenario?.id ?? null)
  const qc = useQueryClient()
  const [importTarget, setImportTarget] = useState<SourceApplication>('VENTSIM')
  const [importNotice, setImportNotice] = useState<string | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)
  const results = useResultsStore()

  const list = useQuery({
    queryKey: ['simulation-results', scenarioId],
    queryFn: () => api.listSimulationResults(scenarioId ?? ''),
    enabled: scenarioId !== null,
    retry: false,
  })

  // an active result that disappeared or went STALE is released (its overlay
  // is refused by the backend; the frontend never guesses a frame)
  const listed = list.data?.results ?? null
  useEffect(() => {
    // judged on a FRESH list only (the effect follows the list data, never
    // the store: right after an import the active id precedes the refetch)
    if (!listed) return
    const store = useResultsStore.getState()
    const vent = listed.find((r) => r.resultId === store.activeVentilationResultId)
    if (store.activeVentilationResultId && (!vent || vent.compatibility !== 'COMPATIBLE')) {
      store.setActiveVentilation(null, null)
    }
    const ops = listed.find((r) => r.resultId === store.activeOperationsResultId)
    if (store.activeOperationsResultId && (!ops || ops.compatibility !== 'COMPATIBLE')) {
      store.setActiveOperations(null, null)
    }
  }, [listed])

  // activation hands the store the metrics the result CARRIES (B2): the
  // selector and the first frame request follow the backend manifest
  const activate = (r: ResultSummary) =>
    r.domain === 'VENTILATION'
      ? results.setActiveVentilation(r.resultId, r.timeAxis, availableVentilationMetrics(r))
      : results.setActiveOperations(r.resultId, r.timeAxis, availableOperationsMetrics(r))

  const importResult = useMutation({
    mutationFn: async (file: File) => {
      if (!scenarioId) throw new Error('load a scenario first')
      return api.importSimulationResult(scenarioId, importTarget, file)
    },
    onSuccess: ({ status, payload }) => {
      setImportNotice(
        status === 201
          ? `Imported ${payload.result.resultId} (${payload.result.compatibility}).`
          : `Identical result already stored as ${payload.result.resultId}.`,
      )
      void qc.invalidateQueries({ queryKey: ['simulation-results', scenarioId] })
      const r = payload.result
      if (r.compatibility === 'COMPATIBLE') activate(r)
    },
  })
  const deleteResult = useMutation({
    mutationFn: async (r: ResultSummary) => {
      if (!scenarioId) throw new Error('load a scenario first')
      await api.deleteSimulationResult(scenarioId, r.resultId)
      return r
    },
    onSuccess: (r) => {
      if (results.activeVentilationResultId === r.resultId) results.setActiveVentilation(null, null)
      if (results.activeOperationsResultId === r.resultId) results.setActiveOperations(null, null)
      void qc.invalidateQueries({ queryKey: ['simulation-results', scenarioId] })
    },
  })

  // the operations result clock: plays on its OWN axis at `speed` axis units
  // per real second (never the MineTimeline day cursor)
  const frame = useRef<number | null>(null)
  const last = useRef<number | null>(null)
  const playing = results.operationsPlaying
  useEffect(() => {
    if (!playing) {
      last.current = null
      return
    }
    const tick = (t: number) => {
      const store = useResultsStore.getState()
      const axis = store.operationsAxis
      if (!axis || axis.end === null) {
        store.pauseOperations()
        return
      }
      if (last.current !== null) {
        const next = store.operationsTime + ((t - last.current) / 1000) * store.operationsSpeed
        if (next >= axis.end) {
          store.setOperationsTime(axis.end)
          store.pauseOperations()
          last.current = null
          return
        }
        store.setOperationsTime(next)
      }
      last.current = t
      frame.current = requestAnimationFrame(tick)
    }
    frame.current = requestAnimationFrame(tick)
    return () => {
      if (frame.current !== null) cancelAnimationFrame(frame.current)
      last.current = null
    }
  }, [playing])

  const onExport = (r: ResultSummary) => {
    if (!scenarioId) return
    setExportError(null)
    const download = api.exportSimulationResult(scenarioId, r.resultId)
    download
      .then((f) => saveFile(f.blob, f.filename))
      .catch((err: unknown) => setExportError(errorText(err)))
  }

  if (!active) return null
  return (
    <SimulationResultsBody
      scenarioId={scenarioId}
      results={listed}
      listError={errorText(list.error)}
      listLoading={list.isPending && scenarioId !== null}
      importTarget={importTarget}
      importing={importResult.isPending}
      importError={errorText(importResult.error)}
      importNotice={importNotice}
      deleting={deleteResult.isPending ? (deleteResult.variables?.resultId ?? null) : null}
      deleteError={errorText(deleteResult.error)}
      exportError={exportError}
      activeVentilationResultId={results.activeVentilationResultId}
      activeOperationsResultId={results.activeOperationsResultId}
      ventilation={{
        metric: results.ventilationMetric,
        metrics: results.ventilationMetrics,
        time: results.ventilationTime,
        axis: results.ventilationAxis,
        range: results.ventilationRange,
        showArrows: results.showAirflowArrows,
        frame: results.ventilationOverlay?.frame ?? null,
        error: results.ventilationOverlayError,
        onMetric: results.setVentilationMetric,
        onTime: results.setVentilationTime,
        onRange: results.setVentilationRange,
        onShowArrows: results.setShowAirflowArrows,
      }}
      operations={{
        metric: results.operationsMetric,
        metrics: results.operationsMetrics,
        time: results.operationsTime,
        axis: results.operationsAxis,
        range: results.operationsRange,
        playing: results.operationsPlaying,
        speed: results.operationsSpeed,
        frame: results.operationsOverlay?.frame ?? null,
        error: results.operationsOverlayError,
        onMetric: results.setOperationsMetric,
        onTime: results.setOperationsTime,
        onRange: results.setOperationsRange,
        onPlay: results.playOperations,
        onPause: results.pauseOperations,
        onSpeed: results.setOperationsSpeed,
      }}
      onImportTarget={(t) => {
        setImportNotice(null)
        setImportTarget(t)
      }}
      onImportFile={(file) => {
        setImportNotice(null)
        importResult.mutate(file)
      }}
      onActivate={activate}
      onDeactivate={(r) =>
        r.domain === 'VENTILATION'
          ? results.setActiveVentilation(null, null)
          : results.setActiveOperations(null, null)
      }
      onDelete={(r) => deleteResult.mutate(r)}
      onExport={onExport}
    />
  )
}
