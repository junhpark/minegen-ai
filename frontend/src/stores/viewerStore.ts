import { create } from 'zustand'
import type { AppMode, LayerId } from '@/types/enums'
import { useTimelineStore } from './timelineStore'
import { useScenarioStore } from './scenarioStore'
import { temporalSessionIdentity } from '@/walkthrough/temporalPlan'
import type { WalkthroughNavigationMode } from '@/walkthrough/navigation'
import type { AnalysisTab, DesignTab, SystemsTab } from '@/components/panels/workflowTabs'
import {
  analysisTabFor,
  designTabFor,
  modeForStage,
  systemsTabFor,
} from '@/components/layout/workflow'
import type { StageId, ViewMode } from '@/types/workflow'

export type CameraMode = 'orbit' | 'walkthrough'
export type WalkthroughContext = 'STATIC_FINAL' | 'TIMELINE_SNAPSHOT'

export interface ViewerState {
  mode: AppMode
  cameraMode: CameraMode
  selectedObjectId: string | null
  visibleLayers: Set<LayerId>
  walkthroughEnabled: boolean
  /** ephemeral walkthrough runtime context (rules 111-112); never persisted */
  walkthroughContext: WalkthroughContext | null
  /** MineTimeline day captured at 4D entry; immutable for the session */
  walkthroughSnapshotDay: number | null
  /** artifact identity captured at 4D entry (rule 112); a mismatch with
   * the live scene means the session must exit, never re-snapshot */
  walkthroughSnapshotIdentity: string | null
  walkthroughReturnMode: AppMode
  /** ephemeral navigation proxy (Phase 16 §3); never persisted */
  navigationMode: WalkthroughNavigationMode
  setNavigationMode: (mode: WalkthroughNavigationMode) => void
  /**
   * Phase 20E §19/§20 — which secondary workflow tab the left panel shows.
   * Presentation state only: it is frontend-local, survives panel rerenders
   * and a scenario change (like `mode`), is never written to a scenario and
   * never triggers a generation, mutation or layer reset.
   */
  designTab: DesignTab
  systemsTab: SystemsTab
  analysisTab: AnalysisTab
  setDesignTab: (tab: DesignTab) => void
  setSystemsTab: (tab: SystemsTab) => void
  setAnalysisTab: (tab: AnalysisTab) => void
  /**
   * Hardening H1 §4.1–4.3 — the guided-workflow STAGE the controls column
   * shows. Frontend-local presentation state like the tabs: never persisted,
   * never a generation or a layer reset. Selecting a stage also selects the
   * pre-shell tab of the panel that owns it and the application mode of its
   * controls — unless a 4D / Walk VIEW is active, which is kept.
   */
  stage: StageId
  setStage: (stage: StageId) => void
  /**
   * Review round 2 S2 / round 3 B1–B2 — the stages that own no artifact and
   * are completed by the viewer, BOUND to the scene revision they were
   * completed on: Analysis once its workspace was actually shown
   * (`AnalysisCenter` mounted over a scene), Export once a package of that
   * scene was downloaded. A completion established on another revision is
   * not a completion of the current mine (a reset or regeneration moves the
   * revision), so `completedStagesFor` yields nothing for it. Stepper
   * presentation only; cleared with the scenario-scoped state.
   */
  completedViewerStages: ViewerCompletion
  markViewerStageComplete: (stage: StageId, sceneRevision: number) => void
  /** 3D | 4D | Walk — the viewport's view mode, chosen apart from the stage */
  viewMode: () => ViewMode
  setViewMode: (view: ViewMode) => void
  /** camera preset request (nonce increments so the same preset can be re-applied) */
  cameraPreset: { kind: 'ISO' | 'TOP' | 'FIT'; nonce: number }
  requestCameraPreset: (kind: 'ISO' | 'TOP' | 'FIT') => void

  setMode: (mode: AppMode) => void
  setCameraMode: (cameraMode: CameraMode) => void
  select: (id: string | null) => void
  toggleLayer: (layer: LayerId) => void
  setLayerVisible: (layer: LayerId, visible: boolean) => void
  isLayerVisible: (layer: LayerId) => boolean
  /**
   * Phase 17.1 §1: drop the viewer state that names objects of the previous
   * scenario. `visibleLayers`, `mode`, `navigationMode` and the Phase 20E
   * workflow tabs are user PREFERENCES, not derived state, and deliberately
   * survive.
   */
  resetScenarioScopedState: () => void
}

const DEFAULT_VISIBLE: LayerId[] = [
  'terrain',
  'orebody',
  'faults',
  // Phase 17.1 §2/§3: the raw Hybrid-A* search path and the block-field
  // slice are explicit opt-in diagnostic layers and default OFF —
  // 'rawSearchPath' and 'rockQuality' are intentionally absent here.
  // Phase 20B closeout v3 §1.C: the legacy 'accessTargets' layer is an
  // advanced legacy-workflow layer and defaults OFF too; generating legacy
  // access targets turns it on explicitly.
  'smoothedDecline',
  'layoutV2',
  'levelAccesses',
  'tunnelMesh',
  'developmentMesh',
  'ramp',
  'levels',
  'crosscuts',
  'shafts',
  'shaftMesh',
  'network',
  'stopes',
  // Phase 16 hotfix 2 (item 6): infrastructure families default ON — they
  // only render inside INFRASTRUCTURE mode, so other modes stay clean
  'routers',
  'coverage',
  'sensors',
  'sensorCoverage',
  // Phase 23C: overlays render only while a result is ACTIVE in the
  // Simulation Results tab, so the toggles default ON
  'ventilationResult',
  'operationsHeatmap',
  'operationsVehicles',
]

/** the viewer-completed stages of ONE scene revision (round 3 B2) */
export interface ViewerCompletion {
  sceneRevision: number
  stages: ReadonlySet<StageId>
}

const NO_COMPLETION: ViewerCompletion = { sceneRevision: -1, stages: new Set<StageId>() }
const NO_STAGES: ReadonlySet<StageId> = new Set<StageId>()

/** the completed stages that count for the CURRENT scene revision — a
 * completion established on any other revision counts for nothing */
export function completedStagesFor(
  completion: ViewerCompletion,
  sceneRevision: number,
): ReadonlySet<StageId> {
  return completion.sceneRevision === sceneRevision ? completion.stages : NO_STAGES
}

export const useViewerStore = create<ViewerState>()((set, get) => ({
  mode: 'DESIGN',
  cameraMode: 'orbit',
  walkthroughContext: null,
  walkthroughSnapshotDay: null,
  walkthroughSnapshotIdentity: null,
  walkthroughReturnMode: 'DESIGN',
  navigationMode: 'PERSON',
  selectedObjectId: null,
  visibleLayers: new Set(DEFAULT_VISIBLE),
  walkthroughEnabled: false,

  designTab: 'LAYOUT',
  systemsTab: 'COMMUNICATION',
  setDesignTab: (designTab) => set({ designTab }),
  setSystemsTab: (systemsTab) => set({ systemsTab }),
  analysisTab: 'OVERVIEW',
  setAnalysisTab: (analysisTab) => set({ analysisTab }),

  stage: 'SCENARIO',
  completedViewerStages: NO_COMPLETION,
  markViewerStageComplete: (stage, sceneRevision) =>
    set((s) => {
      const current = s.completedViewerStages
      if (current.sceneRevision === sceneRevision && current.stages.has(stage)) return {}
      // a completion of an OLDER revision than the one already recorded is
      // stale (the mine moved on while it was being established): ignored
      if (sceneRevision < current.sceneRevision) return {}
      // a completion on a NEW revision starts a new set: nothing established
      // on the previous mine state carries over (round 3 B2)
      const stages =
        current.sceneRevision === sceneRevision
          ? new Set(current.stages).add(stage)
          : new Set<StageId>([stage])
      return { completedViewerStages: { sceneRevision, stages } }
    }),
  setStage: (stage) => {
    // round 3 B1: the Analysis workspace is the centre view rendered only in
    // the ANALYSIS mode, so opening the stage from a 4D / Walk view leaves
    // that view explicitly (the Walk exit clears its snapshot state, rule 112)
    const current = get()
    if (stage === 'ANALYSIS' && (current.mode === '4D' || current.mode === 'WALKTHROUGH')) {
      current.setMode('ANALYSIS')
    }
    set((s) => {
      const next: Partial<ViewerState> = { stage, designTab: designTabFor(stage) }
      const systems = systemsTabFor(stage)
      if (systems) next.systemsTab = systems
      const analysis = analysisTabFor(stage)
      if (analysis && s.analysisTab === 'SIMULATION') next.analysisTab = analysis
      // a 4D / Walk view is a VIEW choice and survives a stage change
      if (s.mode !== '4D' && s.mode !== 'WALKTHROUGH') next.mode = modeForStage(stage)
      return next
    })
  },
  viewMode: () => {
    const m = get().mode
    return m === '4D' ? '4D' : m === 'WALKTHROUGH' ? 'WALK' : '3D'
  },
  setViewMode: (view) => {
    const s = get()
    if (view === 'WALK') {
      s.setMode('WALKTHROUGH')
      return
    }
    if (view === '4D') {
      if (s.mode === 'WALKTHROUGH') s.setMode('4D')
      else set({ mode: '4D' })
      return
    }
    // back to the 3D view of the current stage's controls
    if (s.mode === 'WALKTHROUGH') s.setMode(modeForStage(s.stage))
    else set({ mode: modeForStage(s.stage) })
  },
  cameraPreset: { kind: 'ISO', nonce: 0 },
  requestCameraPreset: (kind) =>
    set((s) => ({ cameraPreset: { kind, nonce: s.cameraPreset.nonce + 1 } })),

  setNavigationMode: (navigationMode) => set({ navigationMode }),
  setMode: (mode) =>
    set((s) => {
      if (mode === 'WALKTHROUGH') {
        // rule 111: entering Walk from 4D captures the timeline day ONCE;
        // every other entry path is the static final-layout walkthrough
        const temporal = s.mode === '4D'
        return {
          mode,
          cameraMode: 'walkthrough' as CameraMode,
          walkthroughContext: temporal ? 'TIMELINE_SNAPSHOT' : 'STATIC_FINAL',
          walkthroughSnapshotDay: temporal ? useTimelineStore.getState().currentDay : null,
          walkthroughSnapshotIdentity: temporal
            ? temporalSessionIdentity(useScenarioStore.getState().scene)
            : null,
          // leaving Walk returns to the view it was entered from: 4D, or the
          // 3D view of the current stage's controls
          walkthroughReturnMode: temporal ? '4D' : modeForStage(s.stage),
        }
      }
      // leaving WALKTHROUGH clears the temporal snapshot state (rule 112)
      // and returns navigation to the PERSON default
      return {
        navigationMode: 'PERSON' as WalkthroughNavigationMode,
        mode,
        cameraMode: 'orbit' as CameraMode,
        walkthroughContext: null,
        walkthroughSnapshotDay: null,
        walkthroughSnapshotIdentity: null,
      }
    }),
  setCameraMode: (cameraMode) => set({ cameraMode }),
  select: (selectedObjectId) => set({ selectedObjectId }),
  toggleLayer: (layer) =>
    set((s) => {
      const next = new Set(s.visibleLayers)
      if (next.has(layer)) next.delete(layer)
      else next.add(layer)
      return { visibleLayers: next }
    }),
  setLayerVisible: (layer, visible) =>
    set((s) => {
      const next = new Set(s.visibleLayers)
      if (visible) next.add(layer)
      else next.delete(layer)
      return { visibleLayers: next }
    }),
  isLayerVisible: (layer) => get().visibleLayers.has(layer),
  resetScenarioScopedState: () =>
    set({
      selectedObjectId: null,
      walkthroughContext: null,
      walkthroughSnapshotDay: null,
      walkthroughSnapshotIdentity: null,
      completedViewerStages: NO_COMPLETION,
    }),
}))
