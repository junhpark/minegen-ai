import { create } from 'zustand'
import type { AppMode, LayerId } from '@/types/enums'

export type CameraMode = 'orbit' | 'walkthrough'

export interface ViewerState {
  mode: AppMode
  cameraMode: CameraMode
  selectedObjectId: string | null
  visibleLayers: Set<LayerId>
  walkthroughEnabled: boolean

  setMode: (mode: AppMode) => void
  setCameraMode: (cameraMode: CameraMode) => void
  select: (id: string | null) => void
  toggleLayer: (layer: LayerId) => void
  setLayerVisible: (layer: LayerId, visible: boolean) => void
  isLayerVisible: (layer: LayerId) => boolean
}

const DEFAULT_VISIBLE: LayerId[] = [
  'terrain',
  'orebody',
  'gradeBlocks',
  'rockQuality',
  'faults',
  'accessTargets',
  'rawSearchPath',
  'smoothedDecline',
  'tunnelMesh',
  'ramp',
  'levels',
  'crosscuts',
  'network',
  'stopes',
]

export const useViewerStore = create<ViewerState>()((set, get) => ({
  mode: 'DESIGN',
  cameraMode: 'orbit',
  selectedObjectId: null,
  visibleLayers: new Set(DEFAULT_VISIBLE),
  walkthroughEnabled: false,

  setMode: (mode) =>
    set({
      mode,
      cameraMode: mode === 'WALKTHROUGH' ? 'walkthrough' : 'orbit',
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
}))
