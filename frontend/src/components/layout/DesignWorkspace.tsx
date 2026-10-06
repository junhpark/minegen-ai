import { DesignPanel } from '@/components/panels/DesignPanel'
import { LayoutPanel } from '@/components/panels/LayoutPanel'
import { LegacyDeclinePanel } from '@/components/panels/LegacyDeclinePanel'
import { useViewerStore } from '@/stores/viewerStore'

/**
 * The Design workflow panels. The stepper (hardening H1 §4.2) replaced the
 * secondary tabs as the navigation, but the panel containers keep their
 * `view` / `active` contract on the Design tab the current stage maps to:
 * every panel stays MOUNTED for every stage and renders only its own
 * context, so each job poll, query and effect keeps exactly its lifetime —
 * switching a stage performs no request, no mutation and no layer change.
 * The legacy Hybrid-A* chain stays an Advanced section of the Layout stage.
 */
export function DesignWorkspace() {
  const tab = useViewerStore((s) => s.designTab)
  const stage = useViewerStore((s) => s.stage)
  return (
    <div data-design-tab={tab}>
      <LayoutPanel active={tab === 'LAYOUT'} />
      <DesignPanel view={tab} />
      <div hidden={stage !== 'LAYOUT'}>
        <LegacyDeclinePanel active={tab === 'LAYOUT'} />
      </div>
    </div>
  )
}
