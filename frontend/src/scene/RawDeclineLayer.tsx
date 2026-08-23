import { Text } from '@react-three/drei'
import { useMemo } from 'react'
import { mineToThree, positionsToThree } from '@/geometry/coordinateTransform'
import type { DeclinePayload } from '@/types/scene'

const SEGMENT_COLORS = ['#f0b84a', '#e4dfd3']
const REJECTED_COLOR = '#d9655a'

/**
 * Raw Hybrid-A* centerline (Phase 04). Diagnostic layer: a polyline per
 * selected segment, alternating colors per level, plus faint lines for
 * non-selected successful candidates. No tunnel mesh — that is Phase 06
 * after Phase 05 smoothing (CLAUDE.md rule 11).
 */
export function RawDeclineLayer({ decline }: { decline: DeclinePayload }) {
  const segments = useMemo(
    () =>
      decline.levels.flatMap((lv, i) =>
        lv.candidateResults
          .filter((c) => c.path !== null)
          .map((c) => ({
            key: `${lv.levelId}-${c.candidateId}`,
            selected: c.selected,
            color: c.selected ? (SEGMENT_COLORS[i % 2] as string) : REJECTED_COLOR,
            positions: positionsToThree((c.path as NonNullable<typeof c.path>).points),
            end: (c.path as NonNullable<typeof c.path>).points.slice(-3) as [
              number,
              number,
              number,
            ],
            label: `${lv.levelId} ${c.candidateId.slice(-3)} ${(c.path as NonNullable<typeof c.path>).length.toFixed(0)} m`,
          })),
      ),
    [decline],
  )

  return (
    <group>
      {segments.map((s) => (
        <group key={s.key}>
          <line>
            <bufferGeometry>
              <bufferAttribute attach="attributes-position" args={[s.positions, 3]} />
            </bufferGeometry>
            <lineBasicMaterial
              color={s.color}
              transparent
              opacity={s.selected ? 1 : 0.18}
              depthTest={s.selected}
            />
          </line>
          {s.selected ? (
            <Text
              position={mineToThree(s.end[0], s.end[1], s.end[2] + 8)}
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
