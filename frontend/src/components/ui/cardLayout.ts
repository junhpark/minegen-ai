import { createContext } from 'react'
import type { StageId } from '@/types/workflow'

/**
 * How the shell lays out a staged card. `FULL` (the default, and every
 * pre-shell test) renders the whole card inline. `SPLIT` renders the action
 * half only when the card's stage is the CURRENT stage, and the results half
 * only when its stage belongs to the current STEP, each into its column host.
 */
export interface CardLayout {
  placement: 'FULL' | 'SPLIT'
  stage: StageId | null
  stepStages: readonly StageId[]
  controlsHost: HTMLElement | null
  resultsHost: HTMLElement | null
}

export const FULL_CARD_LAYOUT: CardLayout = {
  placement: 'FULL',
  stage: null,
  stepStages: [],
  controlsHost: null,
  resultsHost: null,
}

export const CardLayoutContext = createContext<CardLayout>(FULL_CARD_LAYOUT)
