import { useMemo } from 'react'
import * as THREE from 'three'
import { mineToThree } from '@/geometry/coordinateTransform'
import type { StopesPayload } from '@/types/scene'

const PLANNED_COLOR = '#c9a4de'
const INVALID_COLOR = '#d9655a'

/**
 * Phase 09 planned stopes (rules 75–80): translucent prisms assembled
 * verbatim from the backend world-space vertices + triangle indices in
 * stopes.json. The frontend performs NO stope engineering calculations —
 * no stationU arithmetic, no dip or thickness derivation (rule 80).
 * Temporal states (PLANNED → … → BACKFILLED) belong to Phase 10; every
 * stope here is PLANNED and rendered uniformly.
 */
export function StopeLayer({ stopes }: { stopes: StopesPayload }) {
  const meshes = useMemo(
    () =>
      stopes.stopes.map((s) => {
        const v = s.geometry.vertices
        const positions = new Float32Array(v.length)
        for (let i = 0; i + 2 < v.length; i += 3) {
          const p = mineToThree(v[i] ?? 0, v[i + 1] ?? 0, v[i + 2] ?? 0)
          positions[i] = p[0]
          positions[i + 1] = p[1]
          positions[i + 2] = p[2]
        }
        const geometry = new THREE.BufferGeometry()
        geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
        geometry.setIndex(s.geometry.triangleIndices)
        geometry.computeVertexNormals()
        return { key: s.id, geometry, valid: s.report.valid }
      }),
    [stopes],
  )

  return (
    <group>
      {meshes.map((m) => (
        <mesh key={m.key} geometry={m.geometry}>
          <meshStandardMaterial
            color={m.valid ? PLANNED_COLOR : INVALID_COLOR}
            transparent
            opacity={0.28}
            side={THREE.DoubleSide}
            depthWrite={false}
          />
        </mesh>
      ))}
    </group>
  )
}
