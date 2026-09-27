import { useEffect, useMemo } from 'react'
import * as THREE from 'three'
import { productionSolids, productionUnitStates } from '@/scene/production'
import {
  stateRevisionAt,
  timelineBatches,
  transitionDays,
  type TimelineBatchState,
} from '@/scene/productionBatches'
import { mergeSolids, prepareSolid, type PreparedSolid } from '@/scene/solidGeometry'
import { useTimelineStore } from '@/stores/timelineStore'
import type { ProductionPayload, TimelinePayload } from '@/types/scene'

/** Visual-only state materials (rule 84): NOT an engineering or regulatory
 * classification. Geometry never changes between states. */
const STATE_STYLE: Record<TimelineBatchState, { color: string; opacity: number } | null> = {
  NOT_BUILT: null,
  PLANNED: { color: '#c9a4de', opacity: 0.1 },
  DEVELOPING: { color: '#e0c04e', opacity: 0.3 },
  ACTIVE: { color: '#e0714e', opacity: 0.55 },
  MINED: { color: '#a03f2e', opacity: 0.45 },
  VOID: { color: '#3a4550', opacity: 0.22 },
  BACKFILLED: { color: '#6f8f6a', opacity: 0.4 },
  CLOSED: { color: '#8a9199', opacity: 0.32 },
  /** retained pillars are never scheduled: one fixed material in 4D */
  RETAINED: { color: '#8d8f96', opacity: 0.5 },
}

/**
 * Phase 10 → 21B/C 4D production layer: EXACT backend vertices / triangle
 * indices (immutable geometry, rule 81); the timeline's state machines —
 * Longhole `stopes` or the generic `production.units` block — control
 * material and visibility only. A cut's backfill is the same volume in the
 * BACKFILLED state (no second geometry); pillars are retained material and
 * are drawn without a state.
 *
 * BATCHED (review item 5): every solid is prepared once (transformed
 * positions + persisted indices); the solids are grouped by visual state and
 * each group is ONE merged geometry + ONE material.
 *
 * Geometry LIFECYCLE (second review, blocker): playback drives `currentDay`
 * from requestAnimationFrame, but batch MEMBERSHIP only changes at a unit's
 * transition day. The merged geometries are therefore keyed by the STATE
 * REVISION (`stateRevisionAt` over the sorted transition days) — a frame
 * whose day crosses no transition reuses the previous geometries untouched —
 * and every replaced or unmounted merged geometry is `dispose()`d, so the
 * GPU buffers of a superseded batch never accumulate.
 */
export function TimelineProductionLayer({
  timeline,
  production,
}: {
  timeline: TimelinePayload
  production: ProductionPayload
}) {
  const currentDay = useTimelineStore((s) => s.currentDay)

  const solids = useMemo(() => productionSolids(production), [production])
  const prepared = useMemo(
    () => new Map<string, PreparedSolid>(solids.map((s) => [s.id, prepareSolid(s.geometry)])),
    [solids],
  )
  const unitById = useMemo(
    () => new Map(productionUnitStates(timeline).map((u) => [u.unitId, u])),
    [timeline],
  )
  const days = useMemo(() => transitionDays(unitById.values()), [unitById])
  // the ONLY temporal input of the geometry: membership is constant between
  // two transition days, so frames inside one revision rebuild nothing
  const revision = stateRevisionAt(days, currentDay)
  const revisionDay = days[revision - 1] ?? Number.NEGATIVE_INFINITY

  const meshes = useMemo(() => {
    // evaluated at the revision's own transition day (same membership as any
    // day of the revision); an unmapped scheduled solid is dropped (fail
    // closed, rule 117 analogue)
    const { batches } = timelineBatches(solids, unitById, revisionDay)
    return batches
      .map((b) => {
        const style = STATE_STYLE[b.state]
        if (!style) return null
        const parts = b.solids
          .map((s) => prepared.get(s.id))
          .filter((p): p is PreparedSolid => p !== undefined)
        return { key: b.key, style, geometry: mergeSolids(parts), count: parts.length }
      })
      .filter((x): x is NonNullable<typeof x> => x !== null)
  }, [solids, prepared, unitById, revisionDay])

  // release the GPU buffers of a superseded batch set (a revision change or
  // an unmount); the mesh keys are stable so R3F does not do this for us
  useEffect(() => {
    return () => {
      for (const m of meshes) m.geometry.dispose()
    }
  }, [meshes])

  return (
    <group>
      {meshes.map((m) => (
        <mesh
          key={m.key}
          geometry={m.geometry}
          frustumCulled={false}
          userData={{ batch: m.key, solids: m.count, revision }}
        >
          <meshStandardMaterial
            color={m.style.color}
            transparent
            opacity={m.style.opacity}
            side={THREE.DoubleSide}
            depthWrite={false}
          />
        </mesh>
      ))}
    </group>
  )
}
