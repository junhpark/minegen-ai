import { Text } from '@react-three/drei'
import { useMemo } from 'react'
import { mineToThree, positionsToThree } from '@/geometry/coordinateTransform'
import type { SmoothedDeclinePayload } from '@/types/scene'

const PREVIEW_COLOR = '#c9a24a'

/**
 * Preview of the SELECTED layout-v2 candidate while it is not the active
 * ramp source (Phase 20A). Dashed-looking thin polylines plus the backend
 * level connection labels; pure visualization assembly of backend points.
 * When LAYOUT_V2 is active the same geometry is rendered by
 * SmoothedDeclineLayer as the effective ramp instead.
 */
export function LayoutSelectedLayer({ selected }: { selected: SmoothedDeclinePayload }) {
  const segments = useMemo(
    () =>
      selected.segments.map((s) => ({
        key: s.segmentId ?? s.levelId ?? '',
        positions: positionsToThree(s.effectiveCenterline.points),
        end: s.effectiveCenterline.points.slice(-3) as [number, number, number],
      })),
    [selected],
  )
  return (
    <group>
      {segments.map((s) => (
        <group key={s.key}>
          <line>
            <bufferGeometry>
              <bufferAttribute attach="attributes-position" args={[s.positions, 3]} />
            </bufferGeometry>
            <lineBasicMaterial color={PREVIEW_COLOR} transparent opacity={0.6} />
          </line>
          <Text
            position={mineToThree(s.end[0], s.end[1], s.end[2] + 8)}
            fontSize={6}
            color={PREVIEW_COLOR}
            anchorX="center"
            anchorY="bottom"
          >
            {`${s.key.replace('RAMP_JUNCTION:', '⊢ ')} (selected)`}
          </Text>
        </group>
      ))}
    </group>
  )
}
