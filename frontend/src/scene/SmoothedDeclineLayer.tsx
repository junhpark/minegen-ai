import { Text } from '@react-three/drei'
import { useMemo } from 'react'
import { mineToThree, positionsToThree } from '@/geometry/coordinateTransform'
import type { SmoothedDeclinePayload } from '@/types/scene'

const SMOOTHED_COLOR = '#7fd4b8'
const FALLBACK_COLOR = '#d9655a'

/**
 * Phase 05 validated effective centerline (rule 64: the only Phase 06 input).
 * One solid polyline per segment: mint = SMOOTHED, red = RAW_FALLBACK so a
 * fallback segment is never mistaken for a smoothed one.
 */
export function SmoothedDeclineLayer({ smoothed }: { smoothed: SmoothedDeclinePayload }) {
  const segments = useMemo(
    () =>
      smoothed.segments.map((s) => ({
        key: s.levelId,
        color: s.effectiveSource === 'SMOOTHED' ? SMOOTHED_COLOR : FALLBACK_COLOR,
        positions: positionsToThree(s.effectiveCenterline.points),
        end: s.effectiveCenterline.points.slice(-3) as [number, number, number],
        label:
          s.effectiveSource === 'SMOOTHED' ? `${s.levelId} smoothed` : `${s.levelId} raw fallback`,
        fallback: s.effectiveSource === 'RAW_FALLBACK',
      })),
    [smoothed],
  )

  return (
    <group>
      {segments.map((s) => (
        <group key={s.key}>
          <line>
            <bufferGeometry>
              <bufferAttribute attach="attributes-position" args={[s.positions, 3]} />
            </bufferGeometry>
            <lineBasicMaterial color={s.color} />
          </line>
          {s.fallback ? (
            <Text
              position={mineToThree(s.end[0], s.end[1], s.end[2] + 16)}
              fontSize={7}
              color={s.color}
              anchorX="center"
              anchorY="bottom"
            >
              {s.label}
            </Text>
          ) : null}
        </group>
      ))}
    </group>
  )
}
