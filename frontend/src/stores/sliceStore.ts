import { create } from 'zustand'
import type { SliceAxis, SliceField, SlicePayload } from '@/types/scene'

/** Axis-aligned block-field slice shown in the viewer (display state only). */
export interface SliceState {
  field: SliceField
  axis: SliceAxis
  index: number
  slice: SlicePayload | null
  setField: (field: SliceField) => void
  setAxis: (axis: SliceAxis) => void
  setIndex: (index: number) => void
  setSlice: (slice: SlicePayload | null) => void
}

export const useSliceStore = create<SliceState>()((set) => ({
  field: 'rockQuality',
  axis: 'z',
  index: 0,
  slice: null,
  setField: (field) => set({ field }),
  setAxis: (axis) => set({ axis, index: 0 }),
  setIndex: (index) => set({ index }),
  setSlice: (slice) => set({ slice }),
}))
