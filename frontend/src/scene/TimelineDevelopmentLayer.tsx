import { useMemo } from 'react'
import { rampOwningArtifact } from '@/walkthrough/temporalPlan'
import { extend, type ThreeElement } from '@react-three/fiber'
import { Line } from 'three'

// React's JSX resolves <line> to the SVG element, which rejects Three
// props like frustumCulled — register an explicit Three Line element
// (R3F v9 pattern) so the timeline polylines are properly typed.
extend({ TimelineLine: Line })

declare module '@react-three/fiber' {
  interface ThreeElements {
    timelineLine: ThreeElement<typeof Line>
  }
}
import { positionsToThree } from '@/geometry/coordinateTransform'
import { useTimelineStore } from '@/stores/timelineStore'
import { clipPolylineByFractions, developmentProgress, stateAt } from '@/timeline/evaluate'
import type {
  LevelAccessesPayload,
  LevelsPayload,
  SmoothedDeclinePayload,
  TimelinePayload,
} from '@/types/scene'

export const LEVEL_ACCESSES_ARTIFACT = 'level_accesses.json'

const COLORS: Record<string, string> = {
  RAMP: '#7fd4b8',
  LEVEL_ACCESS: '#f2c14e',
  DRIFT: '#8fb8de',
  CROSSCUT: '#deb46a',
}

/**
 * Phase 10 4D development layer (rules 31/83/86): consumes backend
 * centerline geometry (via each development's geometryRef) and backend
 * pointChainageFractions, evaluating only the linear progress window and
 * ONE interpolated cut point. NOT_BUILT developments are hidden; a
 * DEVELOPING edge is never drawn at full extent; ACTIVE renders complete.
 */
export function TimelineDevelopmentLayer({
  timeline,
  smoothed,
  levels,
  levelAccesses = null,
  skipEdgeIds = null,
}: {
  timeline: TimelinePayload
  smoothed: SmoothedDeclinePayload
  levels: LevelsPayload
  levelAccesses?: LevelAccessesPayload | null
  /** Phase 20B.2-F: developments already shown as progressive excavation
   * meshes keep no duplicate centerline; unmapped ones still draw here */
  skipEdgeIds?: ReadonlySet<string> | null
}) {
  const currentDay = useTimelineStore((s) => s.currentDay)

  const lines = useMemo(() => {
    const out: { key: string; color: string; positions: Float32Array }[] = []
    for (const dev of timeline.developments) {
      if (skipEdgeIds?.has(dev.edgeId)) continue
      const state = stateAt(dev.initialState, dev.transitions, currentDay)
      if (state === 'NOT_BUILT') continue
      const ref = dev.geometryRef
      // rule 157: every geometryRef resolves against its OWNING artifact
      const points =
        ref.artifact === rampOwningArtifact(smoothed)
          ? smoothed.segments[ref.segmentIndex]?.effectiveCenterline.points
          : ref.artifact === LEVEL_ACCESSES_ARTIFACT
            ? (levelAccesses?.accesses[ref.segmentIndex]?.centerline?.points ?? undefined)
            : levels.developments[ref.segmentIndex]?.centerline.points
      if (!points) continue
      const clipped =
        state === 'DEVELOPING'
          ? clipPolylineByFractions(
              points,
              dev.pointChainageFractions,
              developmentProgress(dev, currentDay),
            )
          : points
      if (clipped.length < 6) continue
      out.push({
        key: dev.edgeId,
        color: COLORS[dev.edgeType] ?? '#cccccc',
        positions: positionsToThree(clipped),
      })
    }
    return out
  }, [timeline, smoothed, levels, levelAccesses, currentDay, skipEdgeIds])

  return (
    <group>
      {lines.map((l) => (
        <timelineLine key={l.key} frustumCulled={false}>
          <bufferGeometry>
            <bufferAttribute attach="attributes-position" args={[l.positions, 3]} />
          </bufferGeometry>
          <lineBasicMaterial color={l.color} transparent opacity={0.95} />
        </timelineLine>
      ))}
    </group>
  )
}
