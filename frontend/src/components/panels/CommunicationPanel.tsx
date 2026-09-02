import { useMutation } from '@tanstack/react-query'
import { api } from '@/api/client'
import { PanelSection } from '@/components/layout/PanelSection'
import { canGenerateCommunication } from '@/infrastructure/view'
import { afterCommunicationRegen } from '@/scene/invalidation'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useViewerStore } from '@/stores/viewerStore'

/**
 * Phase 11 communication planning panel (rules 87–92). Independent
 * component by design (Phase-10 UI review): infrastructure features must be
 * movable during the final UI redesign without touching DesignPanel.
 */
export function CommunicationPanel() {
  const scene = useScenarioStore((s) => s.scene)
  const scenario = useScenarioStore((s) => s.scenario)
  // §1: epoch-guarded store-internal write — never a captured `scene` copy
  const applyScene = useScenarioStore((s) => s.applyScene)
  const epoch = useScenarioStore((s) => s.epoch)
  const setLayerVisible = useViewerStore((s) => s.setLayerVisible)

  const network = scene?.network ?? null
  const communication = scene?.communication ?? null
  const config = scenario?.infrastructure?.communication ?? null

  const generate = useMutation({
    mutationFn: async () => {
      if (!scene) throw new Error('load a scenario first')
      return api.generateCommunication(scene.scenarioId)
    },
    onSuccess: (payload) => {
      // rule 92: communication regeneration touches nothing upstream
      applyScene(epoch, (current) => afterCommunicationRegen(current, payload))
      setLayerVisible('routers', true)
      setLayerVisible('coverage', true)
    },
  })

  const metrics = communication?.status === 'SUCCESS' ? communication.metrics : null

  return (
    <PanelSection title="Communication">
      {config ? (
        <div className="readout text-[11px] text-chalk-dim">
          <div className="flex justify-between">
            <span className="text-mute">asset</span>
            <span>{config.assetType}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-mute">candidate / demand spacing</span>
            <span>
              {config.candidateSpacingM} / {config.demandSpacingM} m
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-mute">coverage / backhaul range</span>
            <span>
              {config.coverageRangeM} / {config.backhaulRangeM} m
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-mute">required coverage</span>
            <span>{(config.requiredCoverageFraction * 100).toFixed(0)}%</span>
          </div>
        </div>
      ) : null}

      <button
        type="button"
        onClick={() => generate.mutate()}
        disabled={!canGenerateCommunication(network) || generate.isPending}
        className="plate mt-2 w-full rounded-sm border border-lamp px-3 py-1.5 text-[13px] text-lamp hover:bg-lamp hover:text-rock-950 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {generate.isPending
          ? 'Planning…'
          : communication
            ? 'Regenerate communication'
            : 'Generate communication'}
      </button>
      {!canGenerateCommunication(network) ? (
        <div className="mt-1 text-[11px] text-mute">requires a SUCCESS MineNetwork</div>
      ) : null}
      {generate.error ? (
        <div className="mt-1 text-[11px] text-danger">{String(generate.error)}</div>
      ) : null}

      {communication ? (
        <div className="readout mt-2 text-[11px]">
          <div className="flex justify-between text-chalk-dim">
            <span className={communication.status === 'SUCCESS' ? 'text-lamp' : 'text-danger'}>
              {communication.status}
            </span>
            {metrics ? (
              <span>{metrics.selectedAssetCount} routers (connected-greedy baseline)</span>
            ) : null}
          </div>
          {metrics ? (
            <>
              <div className="mt-1 flex justify-between text-chalk-dim">
                <span>
                  covered {metrics.coveredDemandCount} / {metrics.demandCount}
                </span>
                <span>{(metrics.coverageFraction * 100).toFixed(1)}%</span>
              </div>
              <div className="mt-1 flex justify-between text-mute">
                <span>
                  serving mean {metrics.meanServingDistanceM?.toFixed(1) ?? '—'} m · max{' '}
                  {metrics.maxServingDistanceM?.toFixed(1) ?? '—'} m
                </span>
                <span>{metrics.maxBackhaulHopCount} hops</span>
              </div>
            </>
          ) : (
            <div className="mt-1 text-danger">{communication.failureReason}</div>
          )}
          <div className="mt-1 text-mute">
            Network-distance communication planning proxy. Not a calibrated RF prediction or
            globally optimal design.
          </div>
        </div>
      ) : null}
    </PanelSection>
  )
}
