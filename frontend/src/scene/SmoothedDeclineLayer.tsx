import { Text } from '@react-three/drei'
import { useMemo } from 'react'
import { mineToThree, positionsToThree } from '@/geometry/coordinateTransform'
import type { SmoothedDeclinePayload } from '@/types/scene'

const SMOOTHED_COLOR = '#7fd4b8'
const FALLBACK_COLOR = '#d9655a'
const PARAMETRIC_COLOR = '#f2c14e'

/**
 * The ACTIVE Effective Ramp (rules 64/149): one solid polyline per segment.
 * mint = legacy SMOOTHED, red = legacy RAW_FALLBACK, amber = PARAMETRIC_V2
 * (layout-v2), so the provenance of every segment is visible. Layout-v2
 * segments carry backend-authored level connection points, labelled by
 * level id (L01 …) — display only, no engineering derivation here.
 */
export function SmoothedDeclineLayer({ smoothed }: { smoothed: SmoothedDeclinePayload }) {
  const segments = useMemo(
    () =>
      smoothed.segments.map((s) => {
        const parametric = s.effectiveSource === 'PARAMETRIC_V2'
        const fallback = s.effectiveSource === 'RAW_FALLBACK'
        const color = parametric ? PARAMETRIC_COLOR : fallback ? FALLBACK_COLOR : SMOOTHED_COLOR
        const end = s.effectiveCenterline.points.slice(-3) as [number, number, number]
        return {
          key: s.levelId,
          color,
          positions: positionsToThree(s.effectiveCenterline.points),
          end,
          label: parametric
            ? s.levelId
            : fallback
              ? `${s.levelId} raw fallback`
              : `${s.levelId} smoothed`,
          labelled: fallback || parametric,
          labelOffset: parametric ? 8 : 16,
        }
      }),
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
          {s.labelled ? (
            <Text
              position={mineToThree(s.end[0], s.end[1], s.end[2] + s.labelOffset)}
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
