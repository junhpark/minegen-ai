import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { api, ApiError } from '@/api/client'
import { ExportContents } from '@/components/panels/ExportContents'
import {
  type ExportTargetKey,
  describeExportContents,
  describeExportTargets,
} from '@/components/panels/exportContents'
import { ActionButton } from '@/components/ui/ActionButton'
import { WorkflowCard } from '@/components/ui/WorkflowCard'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useViewerStore } from '@/stores/viewerStore'
import { saveFile } from '@/utils/download'

const INPUT =
  'w-full rounded-sm border border-rock-700 bg-rock-900 px-2 py-1 text-chalk focus:border-lamp focus:outline-none'

/**
 * Hardening H1 §4.3 — the Export stage (also reached from File › Export:
 * two paths, one implementation). One export action over a compact target
 * selector. The backend is the only authority on what a package contains
 * (MineExchange manifest omissions, adapter_manifest.json); the panel
 * mirrors each adapter's required sources from the scene and generates
 * nothing.
 */
export function ExportPanel() {
  const scenario = useScenarioStore((s) => s.scenario)
  const scene = useScenarioStore((s) => s.scene)
  const markViewerStageComplete = useViewerStore((s) => s.markViewerStageComplete)
  const [exportTarget, setExportTarget] = useState<ExportTargetKey>('MINE_EXCHANGE')
  const exportTargets = describeExportTargets(scene ?? null)
  const selectedTarget = exportTargets.find((t) => t.key === exportTarget) ?? exportTargets[0]
  const exportPackage = useMutation({
    mutationFn: async () => {
      if (!scenario) throw new Error('no scenario selected')
      const file =
        exportTarget === 'MINE_EXCHANGE'
          ? await api.exportMineExchange(scenario.id)
          : await api.exportAdapter(scenario.id, exportTarget)
      saveFile(file.blob, file.filename)
    },
    // S2: a downloaded package completes the Export stage for this viewer
    onSuccess: () => markViewerStageComplete('EXPORT'),
  })
  const error = exportPackage.error
  const errorText =
    error instanceof ApiError ? `${error.code}: ${error.message}` : error ? error.message : null
  const exportLayers = describeExportContents(scene, (scenario?.shafts?.specs.length ?? 0) > 0)
  const included = exportLayers.filter((l) => l.state === 'INCLUDED').length
  const enabled = Boolean(scenario && scene && selectedTarget?.enabled) && !exportPackage.isPending

  return (
    <WorkflowCard
      stage="EXPORT"
      title="Export"
      tone={scene ? 'READY' : 'NOT_GENERATED'}
      statusLabel={
        scene ? `${String(included)} / ${String(exportLayers.length)} layers` : 'No world'
      }
      info="MineExchange is a versioned, read-only projection of the current mine state; the Ventsim, AnyLogic, Unity and Unreal packages are built on the backend from that bundle and record their sources, assumptions and omissions in adapter_manifest.json. An export persists nothing and changes nothing."
      summary={
        scene
          ? `${String(included)} of ${String(exportLayers.length)} layers available for export`
          : 'Generate a world first — a world-only export is valid; missing layers are recorded in the manifest.'
      }
      action={
        <div>
          <label className="mb-1 block text-[11px] text-chalk-dim">
            Target
            <select
              data-testid="export-target-select"
              className={`${INPUT} mt-1`}
              value={exportTarget}
              disabled={!scenario || exportPackage.isPending}
              onChange={(e) => setExportTarget(e.target.value as ExportTargetKey)}
            >
              {exportTargets.map((t) => (
                <option key={t.key} value={t.key}>
                  {t.label} — {t.description}
                </option>
              ))}
            </select>
          </label>
          <p className="mb-1.5 text-[11px] text-chalk-dim" data-testid="export-target-reason">
            {selectedTarget?.description}
            {selectedTarget && !selectedTarget.enabled ? ` · ${selectedTarget.reason}` : ''}
          </p>
          <ActionButton
            variant={enabled ? 'primary' : 'secondary'}
            disabled={!enabled}
            title={
              exportTarget === 'MINE_EXCHANGE'
                ? 'Download the MineExchange bundle of the currently available mine state (a world-only export is valid; missing layers are recorded in the manifest)'
                : `${selectedTarget?.label ?? ''} package built on the backend from the MineExchange bundle; adapter_manifest.json records sources, assumptions and omissions. ${selectedTarget?.reason ?? ''}`
            }
            onClick={() => exportPackage.mutate()}
          >
            {exportPackage.isPending
              ? 'Preparing export…'
              : `Export ${selectedTarget?.label ?? 'MineExchange'} (.zip)`}
          </ActionButton>
          {errorText ? (
            <p role="alert" className="mt-2 text-[11px] text-danger">
              {errorText}
            </p>
          ) : null}
        </div>
      }
      details={<ExportContents layers={exportLayers} />}
      detailsLabel="Export contents"
    />
  )
}
