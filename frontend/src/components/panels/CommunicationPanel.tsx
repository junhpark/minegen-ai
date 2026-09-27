import { useMutation } from '@tanstack/react-query'
import { api } from '@/api/client'
import { ActionButton } from '@/components/ui/ActionButton'
import { artifactTone, nextActionVariant } from '@/components/ui/presentation'
import { Disclosure } from '@/components/ui/Disclosure'
import { Metrics } from '@/components/ui/MetricRow'
import { WorkflowCard } from '@/components/ui/WorkflowCard'
import { canGenerateCommunication } from '@/infrastructure/view'
import { afterCommunicationRegen } from '@/scene/invalidation'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useViewerStore } from '@/stores/viewerStore'

/**
 * Communication planning panel. Independent component by design:
 * infrastructure features are movable without touching DesignPanel.
 *
 * Phase 20E: `active` decides only whether the panel RENDERS; the hooks above
 * the gate keep their pre-20E lifetime for both Systems tabs (§19).
 */
export function CommunicationPanel({ active = true }: { active?: boolean } = {}) {
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

  const canGenerate = canGenerateCommunication(network)
  if (!active) return null
  return (
    <WorkflowCard
      title="Communication"
      tone={artifactTone(communication, generate.isPending)}
      info="Underground mesh-router placement and backhaul planning. Coverage and backhaul are measured along the physical mine network, never straight through rock, and every selected router is connected back to the portal. It is an explicit planning proxy — not a calibrated radio prediction, not a globally optimal design, and router installation timing is not modelled."
      summary={
        metrics ? (
          <>
            {metrics.selectedAssetCount} routers · covered {metrics.coveredDemandCount}/
            {metrics.demandCount} ({(metrics.coverageFraction * 100).toFixed(1)}%)
          </>
        ) : null
      }
      failure={
        communication && communication.status !== 'SUCCESS' ? communication.failureReason : null
      }
      notice={canGenerate ? null : <>Requires a successful mine network.</>}
      action={
        <ActionButton
          variant={nextActionVariant(communication !== null, canGenerate && !generate.isPending)}
          disabled={!canGenerate || generate.isPending}
          onClick={() => generate.mutate()}
        >
          {generate.isPending
            ? 'Planning…'
            : communication
              ? 'Replan communication'
              : 'Plan communication'}
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
                  label: 'Serving distance',
                  value: `mean ${metrics.meanServingDistanceM?.toFixed(1) ?? '—'} m · max ${metrics.maxServingDistanceM?.toFixed(1) ?? '—'} m`,
                },
                { label: 'Backhaul hops', value: metrics.maxBackhaulHopCount },
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
                  {
                    label: 'Coverage / backhaul range',
                    value: `${config.coverageRangeM} / ${config.backhaulRangeM} m`,
                  },
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
