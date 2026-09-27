import { useMemo } from 'react'
import * as THREE from 'three'
import { solidGeometry } from '@/scene/solidGeometry'
import { productionSolids, productionUnitStates } from '@/scene/production'
import { useTimelineStore } from '@/stores/timelineStore'
import { stateAt } from '@/timeline/evaluate'
import type { ObjectStateId, ProductionPayload, TimelinePayload } from '@/types/scene'

/** Visual-only state materials (rule 84): NOT an engineering or regulatory
 * classification. Geometry never changes between states. */
const STATE_STYLE: Record<ObjectStateId, { color: string; opacity: number } | null> = {
  NOT_BUILT: null,
  PLANNED: { color: '#c9a4de', opacity: 0.1 },
  DEVELOPING: { color: '#e0c04e', opacity: 0.3 },
  ACTIVE: { color: '#e0714e', opacity: 0.55 },
  MINED: { color: '#a03f2e', opacity: 0.45 },
  VOID: { color: '#3a4550', opacity: 0.22 },
  BACKFILLED: { color: '#6f8f6a', opacity: 0.4 },
  CLOSED: { color: '#8a9199', opacity: 0.32 },
}
/** retained pillars are never scheduled: one fixed material in 4D */
const RETAINED_STYLE = { color: '#8d8f96', opacity: 0.5 }

/**
 * Phase 10 → 21B/C 4D production layer: EXACT backend vertices / triangle
 * indices (immutable geometry, rule 81); the timeline's state machines —
 * Longhole `stopes` or the generic `production.units` block — control
 * material and visibility only. A cut's backfill is the same volume in the
 * BACKFILLED state (no second geometry); pillars are retained material and
 * are drawn without a state.
 */
export function TimelineProductionLayer({
  timeline,
  production,
}: {
  timeline: TimelinePayload
  production: ProductionPayload
}) {
  const currentDay = useTimelineStore((s) => s.currentDay)

  const solids = useMemo(
    () => productionSolids(production).map((s) => ({ ...s, three: solidGeometry(s.geometry) })),
    [production],
  )
  const unitById = useMemo(
    () => new Map(productionUnitStates(timeline).map((u) => [u.unitId, u])),
    [timeline],
  )

  const items = useMemo(
    () =>
      solids
        .map((s) => {
          if (!s.scheduled) return { key: s.id, style: RETAINED_STYLE, geometry: s.three }
          const unit = unitById.get(s.id)
          if (!unit) return null // fail closed: an unmapped unit is not guessed (rule 117 analogue)
          const style = STATE_STYLE[stateAt(unit.initialState, unit.transitions, currentDay)]
          return style ? { key: s.id, style, geometry: s.three } : null
        })
        .filter((x): x is NonNullable<typeof x> => x !== null),
    [solids, unitById, currentDay],
  )

  return (
    <group>
      {items.map((it) => (
        <mesh key={it.key} geometry={it.geometry} frustumCulled={false}>
          <meshStandardMaterial
            color={it.style.color}
            transparent
            opacity={it.style.opacity}
            side={THREE.DoubleSide}
            depthWrite={false}
          />
        </mesh>
      ))}
    </group>
  )
}
