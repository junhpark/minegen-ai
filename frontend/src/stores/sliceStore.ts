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
  /** Phase 17.1 §1: slice data belongs to one scenario and never survives a
   * scenario change. Called by the single scenario-session transition. */
  reset: () => void
}

const INITIAL: Pick<SliceState, 'field' | 'axis' | 'index' | 'slice'> = {
  field: 'rockQuality',
  axis: 'z',
  index: 0,
  slice: null,
}

export const useSliceStore = create<SliceState>()((set) => ({
  ...INITIAL,
  setField: (field) => set({ field }),
  setAxis: (axis) => set({ axis, index: 0 }),
  setIndex: (index) => set({ index }),
  setSlice: (slice) => set({ slice }),
  reset: () => set({ ...INITIAL }),
}))
