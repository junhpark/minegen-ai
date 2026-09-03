import { Text } from '@react-three/drei'
import { useMemo } from 'react'
import { mineToThree, positionsToThree } from '@/geometry/coordinateTransform'
import type { LevelAccessesPayload } from '@/types/scene'

const ACCESS_COLOR = '#f2c14e'
const ENTRY_COLOR = '#7fd4b8'
const FAILED_COLOR = '#d9655a'

/**
 * Phase 20B (rules 153–157): ramp junctions (turnouts), level-access
 * branches and the TRUE level entries, exactly as delivered in
 * level_accesses.json. Pure visualization assembly — the branch geometry,
 * welds and entries are backend-authored; nothing is reconstructed here.
 * The user can trace ramp → turnout → branch → level entry → drift.
 */
export function LevelAccessLayer({ accesses }: { accesses: LevelAccessesPayload }) {
  const items = useMemo(
    () =>
      accesses.accesses.map((a) => ({
        key: a.levelId,
        ok: a.status === 'OK',
        positions: a.centerline ? positionsToThree(a.centerline.points) : null,
        junction: a.rampJunction,
        entry: a.levelEntry ?? a.anchor?.position ?? null,
        label:
          a.status === 'OK'
            ? `${a.levelId} entry`
            : `${a.levelId} ${a.failureReason ?? 'no access'}`,
      })),
    [accesses],
  )
  return (
    <group>
      {items.map((it) => (
        <group key={it.key}>
          {it.positions ? (
            <line>
              <bufferGeometry>
                <bufferAttribute attach="attributes-position" args={[it.positions, 3]} />
              </bufferGeometry>
              <lineBasicMaterial color={ACCESS_COLOR} />
            </line>
          ) : null}
          {it.junction ? (
            <mesh position={mineToThree(it.junction[0], it.junction[1], it.junction[2])}>
              <sphereGeometry args={[2.2, 10, 10]} />
              <meshBasicMaterial color={ACCESS_COLOR} />
            </mesh>
          ) : null}
          {it.entry ? (
            <>
              <mesh position={mineToThree(it.entry[0], it.entry[1], it.entry[2])}>
                <boxGeometry args={[3.5, 3.5, 3.5]} />
                <meshBasicMaterial color={it.ok ? ENTRY_COLOR : FAILED_COLOR} />
              </mesh>
              <Text
                position={mineToThree(it.entry[0], it.entry[1], it.entry[2] + 7)}
                fontSize={6}
                color={it.ok ? ENTRY_COLOR : FAILED_COLOR}
                anchorX="center"
                anchorY="bottom"
              >
                {it.label}
              </Text>
            </>
          ) : null}
        </group>
      ))}
    </group>
  )
}
