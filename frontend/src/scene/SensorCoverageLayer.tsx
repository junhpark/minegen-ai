import { useMemo } from 'react'
import * as THREE from 'three'
import { mineToThree } from '@/geometry/coordinateTransform'
import { sensorDemandRenderData } from '@/infrastructure/view'
import type { SensorPayload } from '@/types/scene'

const COVERED_COLOR = '#8fb5e8'
const UNCOVERED_COLOR = '#d9655a'

/**
 * Phase 12 monitoring coverage (rule 95): renders covered/uncovered
 * monitoring demand POINTS from the backend assignment only. Deliberately
 * NO Euclidean spheres, gas clouds or detection cones — the model is a
 * network-geodesic layout proxy and none of those are modeled.
 */
function MonitoringPoints({
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

export function SensorCoverageLayer({ sensors }: { sensors: SensorPayload }) {
  const { covered, uncovered } = useMemo(() => sensorDemandRenderData(sensors), [sensors])
  return (
    <group>
      <MonitoringPoints positions={covered} color={COVERED_COLOR} size={3} />
      <MonitoringPoints positions={uncovered} color={UNCOVERED_COLOR} size={5} />
    </group>
  )
}
