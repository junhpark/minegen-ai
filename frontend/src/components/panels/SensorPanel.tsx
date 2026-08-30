import { useMutation } from '@tanstack/react-query'
import { api } from '@/api/client'
import { PanelSection } from '@/components/layout/PanelSection'
import { canGenerateSensors } from '@/infrastructure/view'
import { afterSensorsRegen } from '@/scene/invalidation'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useViewerStore } from '@/stores/viewerStore'

/**
 * Phase 12 sensor placement panel (rules 93–98). Independent component by
 * design (Phase-10 UI review): infrastructure features remain movable
 * during the final UI redesign and are never appended to DesignPanel.
 */
export function SensorPanel() {
  const scene = useScenarioStore((s) => s.scene)
  const scenario = useScenarioStore((s) => s.scenario)
  const setScene = useScenarioStore((s) => s.setScene)
  const setLayerVisible = useViewerStore((s) => s.setLayerVisible)

  const network = scene?.network ?? null
  const sensors = scene?.sensors ?? null
  const config = scenario?.infrastructure?.sensors ?? null

  const generate = useMutation({
    mutationFn: async () => {
      if (!scene) throw new Error('load a scenario first')
      return api.generateSensors(scene.scenarioId)
    },
    onSuccess: (payload) => {
      // rule 98: sensor regeneration touches nothing else
      if (scene) setScene(afterSensorsRegen(scene, payload))
      setLayerVisible('sensors', true)
      setLayerVisible('sensorCoverage', true)
    },
  })

  const metrics = sensors?.status === 'SUCCESS' ? sensors.metrics : null

  return (
    <PanelSection title="Sensors">
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
            <span className="text-mute">monitoring range</span>
            <span>{config.monitoringRangeM} m</span>
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
        disabled={!canGenerateSensors(network) || generate.isPending}
        className="plate mt-2 w-full rounded-sm border border-lamp px-3 py-1.5 text-[13px] text-lamp hover:bg-lamp hover:text-rock-950 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {generate.isPending ? 'Placing…' : sensors ? 'Regenerate sensors' : 'Generate sensors'}
      </button>
      {!canGenerateSensors(network) ? (
        <div className="mt-1 text-[11px] text-mute">requires a SUCCESS MineNetwork</div>
      ) : null}
      {generate.error ? (
        <div className="mt-1 text-[11px] text-danger">{String(generate.error)}</div>
      ) : null}

      {sensors ? (
        <div className="readout mt-2 text-[11px]">
          <div className="flex justify-between text-chalk-dim">
            <span className={sensors.status === 'SUCCESS' ? 'text-lamp' : 'text-danger'}>
              {sensors.status}
            </span>
            {metrics ? <span>{metrics.selectedSensorCount} sensors (greedy baseline)</span> : null}
          </div>
          {metrics ? (
            <>
              <div className="mt-1 flex justify-between text-chalk-dim">
                <span>
                  covered {metrics.coveredDemandCount} / {metrics.demandCount}
                </span>
                <span>{(metrics.coverageFraction * 100).toFixed(1)}%</span>
              </div>
              <div className="mt-1 text-mute">
                monitoring mean {metrics.meanMonitoringDistanceM?.toFixed(1) ?? '—'} m · max{' '}
                {metrics.maxMonitoringDistanceM?.toFixed(1) ?? '—'} m
              </div>
            </>
          ) : (
            <div className="mt-1 text-danger">{sensors.failureReason}</div>
          )}
          <div className="mt-1 text-mute">
            Network-distance monitoring-layout proxy. Not a gas-dispersion or physical detection
            model. Communication and power feasibility are not enforced. Greedy baseline; no
            global-optimality claim.
          </div>
        </div>
      ) : null}
    </PanelSection>
  )
}
