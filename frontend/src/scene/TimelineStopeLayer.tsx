import { useMemo } from 'react'
import * as THREE from 'three'
import { mineToThree } from '@/geometry/coordinateTransform'
import { useTimelineStore } from '@/stores/timelineStore'
import { stateAt } from '@/timeline/evaluate'
import type { ObjectStateId, StopesPayload, TimelinePayload } from '@/types/scene'

/** Visual-only state materials (rule 84): NOT an engineering or regulatory
 * classification. Geometry never changes between states in Phase 10. */
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

/**
 * Phase 10 4D stope layer: EXACT Phase 09 backend vertices/triangleIndices
 * (immutable geometry, rule 81); the timeline state controls material and
 * visibility only.
 */
export function TimelineStopeLayer({
  timeline,
  stopes,
}: {
  timeline: TimelinePayload
  stopes: StopesPayload
}) {
  const currentDay = useTimelineStore((s) => s.currentDay)

  const geometryById = useMemo(() => {
    const map = new Map<string, THREE.BufferGeometry>()
    for (const s of stopes.stopes) {
      const v = s.geometry.vertices
      const positions = new Float32Array(v.length)
      for (let i = 0; i + 2 < v.length; i += 3) {
        const p = mineToThree(v[i] ?? 0, v[i + 1] ?? 0, v[i + 2] ?? 0)
        positions[i] = p[0]
        positions[i + 1] = p[1]
        positions[i + 2] = p[2]
      }
      const g = new THREE.BufferGeometry()
      g.setAttribute('position', new THREE.BufferAttribute(positions, 3))
      g.setIndex(s.geometry.triangleIndices)
      g.computeVertexNormals()
      map.set(s.id, g)
    }
    return map
  }, [stopes])

  const items = useMemo(
    () =>
      timeline.stopes
        .map((st) => {
          const style = STATE_STYLE[stateAt(st.initialState, st.transitions, currentDay)]
          const geometry = geometryById.get(st.stopeId)
          return style && geometry ? { key: st.stopeId, style, geometry } : null
        })
        .filter((x): x is NonNullable<typeof x> => x !== null),
    [timeline, geometryById, currentDay],
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
