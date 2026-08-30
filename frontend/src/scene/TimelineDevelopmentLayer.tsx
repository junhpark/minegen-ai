import { useMemo } from 'react'
import { positionsToThree } from '@/geometry/coordinateTransform'
import { useTimelineStore } from '@/stores/timelineStore'
import { clipPolylineByFractions, developmentProgress, stateAt } from '@/timeline/evaluate'
import type { LevelsPayload, SmoothedDeclinePayload, TimelinePayload } from '@/types/scene'

const COLORS: Record<string, string> = {
  RAMP: '#7fd4b8',
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
}: {
  timeline: TimelinePayload
  smoothed: SmoothedDeclinePayload
  levels: LevelsPayload
}) {
  const currentDay = useTimelineStore((s) => s.currentDay)

  const lines = useMemo(() => {
    const out: { key: string; color: string; positions: Float32Array }[] = []
    for (const dev of timeline.developments) {
      const state = stateAt(dev.initialState, dev.transitions, currentDay)
      if (state === 'NOT_BUILT') continue
      const ref = dev.geometryRef
      const points =
        ref.artifact === 'decline_smoothed.json'
          ? smoothed.segments[ref.segmentIndex]?.effectiveCenterline.points
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
  }, [timeline, smoothed, levels, currentDay])

  return (
    <group>
      {lines.map((l) => (
        <line key={l.key}>
          <bufferGeometry>
            <bufferAttribute attach="attributes-position" args={[l.positions, 3]} />
          </bufferGeometry>
          <lineBasicMaterial color={l.color} transparent opacity={0.95} />
        </line>
      ))}
    </group>
  )
}
