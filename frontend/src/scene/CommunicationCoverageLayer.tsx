import { useMemo } from 'react'
import * as THREE from 'three'
import { mineToThree } from '@/geometry/coordinateTransform'
import { demandRenderData } from '@/infrastructure/view'
import type { CommunicationPayload } from '@/types/scene'

const COVERED_COLOR = '#5fbf7a'
const UNCOVERED_COLOR = '#d9655a'

/**
 * Phase 11 demand coverage (rule 88): renders covered/uncovered demand
 * POINTS from the backend assignment only. Deliberately NO Euclidean
 * coverage spheres and NO straight router-to-router beams — the model is
 * network-geodesic, and an XYZ sphere/beam through rock would visually
 * misrepresent the engineering contract.
 */
function DemandPoints({
  positions,
  color,
  size,
}: {
  positions: [number, number, number][]
  color: string
  size: number
}) {
  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry()
    const arr = new Float32Array(positions.length * 3)
    positions.forEach((p, i) => {
      const [x, y, z] = mineToThree(...p)
      arr[i * 3] = x
      arr[i * 3 + 1] = y
      arr[i * 3 + 2] = z
    })
    g.setAttribute('position', new THREE.BufferAttribute(arr, 3))
    return g
  }, [positions])
  if (positions.length === 0) return null
  return (
    <points geometry={geometry} frustumCulled={false}>
      <pointsMaterial color={color} size={size} sizeAttenuation={false} depthWrite={false} />
    </points>
  )
}

export function CommunicationCoverageLayer({
  communication,
}: {
  communication: CommunicationPayload
}) {
  const { covered, uncovered } = useMemo(() => demandRenderData(communication), [communication])
  return (
    <group>
      <DemandPoints positions={covered} color={COVERED_COLOR} size={3} />
      <DemandPoints positions={uncovered} color={UNCOVERED_COLOR} size={5} />
    </group>
  )
}
