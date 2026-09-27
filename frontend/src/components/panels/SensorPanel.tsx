import { useMutation } from '@tanstack/react-query'
import { api } from '@/api/client'
import { ActionButton } from '@/components/ui/ActionButton'
import { artifactTone, nextActionVariant } from '@/components/ui/presentation'
import { Disclosure } from '@/components/ui/Disclosure'
import { Metrics } from '@/components/ui/MetricRow'
import { WorkflowCard } from '@/components/ui/WorkflowCard'
import { canGenerateSensors } from '@/infrastructure/view'
import { afterSensorsRegen } from '@/scene/invalidation'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useViewerStore } from '@/stores/viewerStore'

/**
 * Sensor placement panel. Independent component by design: infrastructure
 * features remain movable and are never appended to DesignPanel.
 *
 * Phase 20E: `active` decides only whether the panel RENDERS; the hooks above
 * the gate keep their pre-20E lifetime for both Systems tabs (§19).
 */
export function SensorPanel({ active = true }: { active?: boolean } = {}) {
  const scene = useScenarioStore((s) => s.scene)
  const scenario = useScenarioStore((s) => s.scenario)
  // §1: epoch-guarded store-internal write — never a captured `scene` copy
  const applyScene = useScenarioStore((s) => s.applyScene)
  const epoch = useScenarioStore((s) => s.epoch)
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
      applyScene(epoch, (current) => afterSensorsRegen(current, payload))
      setLayerVisible('sensors', true)
      setLayerVisible('sensorCoverage', true)
    },
  })

  const metrics = sensors?.status === 'SUCCESS' ? sensors.metrics : null

  const canGenerate = canGenerateSensors(network)
  if (!active) return null
  return (
    <WorkflowCard
      title="Sensors"
      tone={artifactTone(sensors, generate.isPending)}
      info="Gas-sensor placement over the mine network: a deterministic greedy set-cover of monitoring demand along physical mine distance, never straight through rock. It is a monitoring-layout proxy — it does not represent gas transport, sensor response, detection probability or a calibrated sensing range, and communication, power and installation timing are not modelled."
      summary={
        metrics ? (
          <>
            {metrics.selectedSensorCount} sensors · covered {metrics.coveredDemandCount}/
            {metrics.demandCount} ({(metrics.coverageFraction * 100).toFixed(1)}%)
          </>
        ) : null
      }
      failure={sensors && sensors.status !== 'SUCCESS' ? sensors.failureReason : null}
      notice={canGenerate ? null : <>Requires a successful mine network.</>}
      action={
        <ActionButton
          variant={nextActionVariant(sensors !== null, canGenerate && !generate.isPending)}
          disabled={!canGenerate || generate.isPending}
          onClick={() => generate.mutate()}
        >
          {generate.isPending ? 'Placing…' : sensors ? 'Replace sensors' : 'Place sensors'}
        </ActionButton>
      }
      progress={
        generate.error ? (
          <p role="alert" className="mt-1 text-[11px] text-danger">
            {String(generate.error)}
          </p>
        ) : null
      }
      details={
        <>
          {metrics ? (
            <Metrics
              rows={[
                {
                  label: 'Monitoring distance',
                  value: `mean ${metrics.meanMonitoringDistanceM?.toFixed(1) ?? '—'} m · max ${metrics.maxMonitoringDistanceM?.toFixed(1) ?? '—'} m`,
                },
              ]}
            />
          ) : null}
          {config ? (
            <Disclosure label="Planning inputs">
              <Metrics
                rows={[
                  { label: 'Asset', value: config.assetType },
                  {
                    label: 'Candidate / demand spacing',
                    value: `${config.candidateSpacingM} / ${config.demandSpacingM} m`,
                  },
                  { label: 'Monitoring range', value: `${config.monitoringRangeM} m` },
                  {
                    label: 'Required coverage',
                    value: `${(config.requiredCoverageFraction * 100).toFixed(0)} %`,
                  },
                ]}
              />
            </Disclosure>
          ) : null}
        </>
      }
    />
  )
}
