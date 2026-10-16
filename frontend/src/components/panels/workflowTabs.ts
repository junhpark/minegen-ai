import type { PanelTab } from '@/components/ui/PanelTabs'

/**
 * Phase 20E §4 — the Design workflow order:
 *
 *   Layout → Develop → Network → Mining
 *
 * These are PRESENTATION groupings of features that already exist. They do
 * not rename, reorder or gate any backend workflow: the dependency chain
 * (ramp → level development → network → stopes → timeline) is unchanged and
 * every prerequisite is still enforced by the feature's own disabled
 * condition.
 */
export type DesignTab = 'LAYOUT' | 'DEVELOP' | 'NETWORK' | 'MINING'

export const DESIGN_TABS: readonly PanelTab<DesignTab>[] = [
  { id: 'LAYOUT', label: 'Layout' },
  { id: 'DEVELOP', label: 'Develop' },
  { id: 'NETWORK', label: 'Network' },
  { id: 'MINING', label: 'Mining' },
]

/** Phase 20E §5 — infrastructure subsystems, one tab each. */
export type SystemsTab = 'COMMUNICATION' | 'SENSORS'

export const SYSTEMS_TABS: readonly PanelTab<SystemsTab>[] = [
  { id: 'COMMUNICATION', label: 'Communication' },
  { id: 'SENSORS', label: 'Sensors' },
]

/**
 * Phase 22A/B/C — the Analysis workspace: quantities first, economics second,
 * then the Design Rulebook (a presentation of the Phase 20D.3 design
 * assessment — never a second rule evaluator) and the Layout comparison
 * (comparable development cost over the persisted layout-v2 catalogue).
 */
export type AnalysisTab =
  | 'OVERVIEW'
  | 'ECONOMICS'
  | 'SENSITIVITY'
  | 'SCHEDULE'
  | 'RULES'
  | 'LAYOUT_COMPARISON'
  | 'SIMULATION'

/** hardening PR-2 H3 §8: the full-screen Analysis workspace tabs — Sensitivity
 * (read-only what-if grid) and Schedule (timeline + time series) join; the
 * layout comparison is labelled "Layouts" (its id and content are unchanged) */
export const ANALYSIS_TABS: readonly PanelTab<AnalysisTab>[] = [
  { id: 'OVERVIEW', label: 'Overview' },
  { id: 'ECONOMICS', label: 'Economics' },
  { id: 'SENSITIVITY', label: 'Sensitivity' },
  { id: 'SCHEDULE', label: 'Schedule' },
  { id: 'RULES', label: 'Rules' },
  { id: 'LAYOUT_COMPARISON', label: 'Layouts' },
  // Phase 23C: external simulation results imported over MineExchange
  // bundles and overlaid on the mine — a separate container, no new AppMode
  { id: 'SIMULATION', label: 'Simulation Results' },
]

export const DESIGN_PANEL_ID = 'design-workflow-panel'
export const ANALYSIS_PANEL_ID = 'analysis-workflow-panel'
export const SYSTEMS_PANEL_ID = 'systems-workflow-panel'

/**
 * Which Design tab owns a feature. Used by the navigation tests to state the
 * expected grouping in one place, and by `DesignPanel` to render one
 * workflow context at a time.
 */
export const DESIGN_TAB_FEATURES: Record<DesignTab, readonly string[]> = {
  LAYOUT: ['Mine layout', 'Design assessment', 'Legacy decline'],
  DEVELOP: ['Level development', 'Development mesh', 'Ramp tunnel mesh', 'Shafts'],
  NETWORK: ['Mine network', 'Capabilities'],
  // Phase 21B/C: the method card (selector + explicit parameters) sits above
  // the method-generic Production card
  MINING: ['Mining method', 'Production', 'Schedule'],
}
