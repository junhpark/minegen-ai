import { Text } from '@react-three/drei'
import { useMemo } from 'react'
import { mineToThree, positionsToThree } from '@/geometry/coordinateTransform'
import type { ShaftsPayload } from '@/types/scene'

const AXIS_COLOR = '#c7a0e8'
const STATION_COLOR = '#e9d8ff'
const ACCESS_COLOR = '#b48ad6'
const FAILED_COLOR = '#d9655a'

/**
 * Phase 20C.2B (rules 182–184): shaft axes, collars, bottoms, level stations
 * and station drives exactly as delivered in shafts.json. Pure
 * visualization assembly — the backend planned and validated every
 * centerline; nothing is derived here (no default placement, no station
 * elevation, no connection target). A FAILED shaft keeps its typed reason
 * visible at the collar when the backend could place one.
 */
export function ShaftLayer({ shafts }: { shafts: ShaftsPayload }) {
  const items = useMemo(
    () =>
      shafts.shafts.map((sh) => {
        const segments = sh.segmentIndices
          .map((i) => shafts.centerlines[i])
          .filter((c) => c !== undefined)
          .map((c) => positionsToThree(c.centerline.points))
        const drives = sh.stations
          .filter((st) => st.accessCenterlineIndex !== null)
          .map((st) => shafts.centerlines[st.accessCenterlineIndex ?? -1])
          .filter((c) => c !== undefined)
          .map((c) => ({ key: c.id, positions: positionsToThree(c.centerline.points) }))
        return {
          key: sh.shaftId,
          ok: sh.status === 'OK',
          collar: sh.collar,
          bottom: sh.bottom,
          segments,
          drives,
          stations: sh.stations,
          label:
            sh.status === 'OK'
              ? `${sh.shaftId} · ${sh.role.toLowerCase()} · ⌀${sh.profile.diameter.toFixed(1)} m`
              : `${sh.shaftId} ${sh.failureCode ?? 'FAILED'}`,
        }
      }),
    [shafts],
  )
  return (
    <group>
      {items.map((it) => (
        <group key={it.key}>
          {it.segments.map((positions, i) => (
            <line key={`${it.key}-seg-${String(i)}`}>
              <bufferGeometry>
                <bufferAttribute attach="attributes-position" args={[positions, 3]} />
              </bufferGeometry>
              <lineBasicMaterial color={AXIS_COLOR} />
            </line>
          ))}
          {it.drives.map((d) => (
            <line key={d.key}>
              <bufferGeometry>
                <bufferAttribute attach="attributes-position" args={[d.positions, 3]} />
              </bufferGeometry>
              <lineBasicMaterial color={ACCESS_COLOR} />
            </line>
          ))}
          {it.stations.map((st) => (
            <mesh key={st.stationId} position={mineToThree(st.point[0], st.point[1], st.point[2])}>
              <sphereGeometry args={[2.4, 10, 10]} />
              <meshBasicMaterial color={st.status === 'OK' ? STATION_COLOR : FAILED_COLOR} />
            </mesh>
          ))}
          {it.ok ? (
            <>
              <mesh position={mineToThree(it.collar[0], it.collar[1], it.collar[2])}>
                <boxGeometry args={[4, 2, 4]} />
                <meshBasicMaterial color={AXIS_COLOR} />
              </mesh>
              <mesh position={mineToThree(it.bottom[0], it.bottom[1], it.bottom[2])}>
                <boxGeometry args={[3, 1.5, 3]} />
                <meshBasicMaterial color={AXIS_COLOR} />
              </mesh>
              <Text
                position={mineToThree(it.collar[0], it.collar[1], it.collar[2] + 8)}
                fontSize={6}
                color={AXIS_COLOR}
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
