import { create } from 'zustand'
import type { AppMode, LayerId } from '@/types/enums'
import { useTimelineStore } from './timelineStore'
import { useScenarioStore } from './scenarioStore'
import { temporalSessionIdentity } from '@/walkthrough/temporalPlan'
import type { WalkthroughNavigationMode } from '@/walkthrough/navigation'

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

  setMode: (mode: AppMode) => void
  setCameraMode: (cameraMode: CameraMode) => void
  select: (id: string | null) => void
  toggleLayer: (layer: LayerId) => void
  setLayerVisible: (layer: LayerId, visible: boolean) => void
  isLayerVisible: (layer: LayerId) => boolean
  /**
   * Phase 17.1 §1: drop the viewer state that names objects of the previous
   * scenario. `visibleLayers`, `mode` and `navigationMode` are user
   * PREFERENCES, not derived state, and deliberately survive.
   */
  resetScenarioScopedState: () => void
}

const DEFAULT_VISIBLE: LayerId[] = [
  'terrain',
  'orebody',
  'faults',
  'accessTargets',
  // Phase 17.1 §2/§3: the raw Hybrid-A* search path and the block-field
  // slice are explicit opt-in diagnostic layers and default OFF —
  // 'rawSearchPath' and 'rockQuality' are intentionally absent here
  'smoothedDecline',
  'layoutV2',
  'levelAccesses',
  'tunnelMesh',
  'ramp',
  'levels',
  'crosscuts',
  'network',
  'stopes',
  // Phase 16 hotfix 2 (item 6): infrastructure families default ON — they
  // only render inside INFRASTRUCTURE mode, so other modes stay clean
  'routers',
  'coverage',
  'sensors',
  'sensorCoverage',
]

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
          walkthroughReturnMode: (temporal ? '4D' : 'DESIGN') as AppMode,
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
    }),
}))
