import { CommunicationPanel } from '@/components/panels/CommunicationPanel'
import { SensorPanel } from '@/components/panels/SensorPanel'
import { useViewerStore } from '@/stores/viewerStore'

/**
 * The infrastructure subsystem panels. Presentation grouping only:
 * communication and sensor planning keep their own independent API,
 * artifacts and planning semantics, and both panels stay mounted (gated on
 * the Systems tab the current stage maps to) so their queries and effects
 * are unchanged. A further subsystem is added by mounting its panel here.
 */
export function SystemsWorkspace() {
  const tab = useViewerStore((s) => s.systemsTab)
  return (
    <div data-systems-tab={tab}>
      <CommunicationPanel active={tab === 'COMMUNICATION'} />
      <SensorPanel active={tab === 'SENSORS'} />
    </div>
  )
}
