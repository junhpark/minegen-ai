import type { LayerId } from '@/types/enums'

export interface LayerRow {
  id: LayerId
  label: string
  /** phase in which the layer gets content; disabled until then */
  phase: number
}

/**
 * The Visibility tree rows. PR-3 round 3: every row toggles a layer the scene
 * READS (`MineScene` tests `visible.has(id)`; `LayerPanel.test.ts` scans
 * for it) — the former `ramp` / `backfill` rows toggled nothing and the
 * "Network graph" row toggled `networkGraph` while the scene read `network`,
 * so the network could not be hidden from the tree.
 */
export const LAYER_GROUPS: { title: string; rows: LayerRow[] }[] = [
  {
    title: 'World',
    rows: [
      { id: 'terrain', label: 'Terrain', phase: 2 },
      { id: 'orebody', label: 'Orebody', phase: 2 },
      { id: 'faults', label: 'Faults', phase: 2 },
      // §3: explicit opt-in viewer layer, default OFF
      { id: 'rockQuality', label: 'Field slice', phase: 2 },
    ],
  },
  {
    title: 'Design',
    rows: [
      { id: 'smoothedDecline', label: 'Effective ramp (active design)', phase: 5 },
      { id: 'layoutV2', label: 'Layout candidate', phase: 20 },
      { id: 'levelAccesses', label: 'Ramp junctions & level accesses', phase: 20 },
      { id: 'levels', label: 'Level drifts (centerline)', phase: 8 },
      { id: 'crosscuts', label: 'Crosscuts (centerline)', phase: 8 },
      { id: 'tunnelMesh', label: 'Ramp tunnel mesh', phase: 6 },
      { id: 'developmentMesh', label: 'Development mesh (access · drift · crosscut)', phase: 20 },
      { id: 'shafts', label: 'Shafts (axis · stations · station drives)', phase: 20 },
      { id: 'shaftMesh', label: 'Shaft excavation mesh (barrel · caps · drives)', phase: 20 },
    ],
  },
  {
    title: 'Network',
    rows: [{ id: 'network', label: 'Network (nodes · edges)', phase: 7 }],
  },
  {
    title: 'Production',
    rows: [{ id: 'stopes', label: 'Production (stopes · cuts · rooms)', phase: 9 }],
  },
  {
    title: 'Systems',
    rows: [
      { id: 'routers', label: 'Routers', phase: 11 },
      { id: 'coverage', label: 'Communication coverage', phase: 11 },
      { id: 'sensors', label: 'Sensors', phase: 12 },
      { id: 'sensorCoverage', label: 'Monitoring coverage', phase: 12 },
    ],
  },
  {
    // Phase 23C: external simulation results (MineResult overlays)
    title: 'Results',
    rows: [
      { id: 'ventilationResult', label: 'Ventilation overlay (active result)', phase: 20 },
      { id: 'operationsHeatmap', label: 'Operations edge heatmap', phase: 20 },
      { id: 'operationsVehicles', label: 'Operations vehicles', phase: 20 },
    ],
  },
  {
    // closeout v3 §1.C: legacy diagnostic layers, default OFF
    title: 'Legacy decline (advanced)',
    rows: [
      { id: 'accessTargets', label: 'Access targets (legacy)', phase: 3 },
      // §2: default OFF, and suppressed outright in 4D / TIMELINE_SNAPSHOT
      { id: 'rawSearchPath', label: 'Raw Hybrid-A* search path', phase: 4 },
    ],
  },
]
