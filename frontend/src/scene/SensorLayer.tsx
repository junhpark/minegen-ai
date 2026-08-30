import { useLayoutEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'
import { mineToThree } from '@/geometry/coordinateTransform'
import { sensorMarkers } from '@/infrastructure/view'
import type { SensorPayload } from '@/types/scene'

const SENSOR_COLOR = new THREE.Color('#e0a94e')

/**
 * Phase 12 selected GAS_SENSOR markers (rules 93/98): pure assembly of
 * backend-selected placements. Positions are tunnel-centerline planning
 * references converted only through mineToThree — no mounting offset,
 * no gas cloud, no detection cone, no false RF link.
 */
export function SensorLayer({ sensors }: { sensors: SensorPayload }) {
  const markers = useMemo(() => sensorMarkers(sensors), [sensors])
  const meshRef = useRef<THREE.InstancedMesh>(null)

  useLayoutEffect(() => {
    const mesh = meshRef.current
    if (!mesh) return
    const m = new THREE.Matrix4()
    markers.forEach((marker, i) => {
      m.setPosition(...mineToThree(...marker.position))
      mesh.setMatrixAt(i, m)
      mesh.setColorAt(i, SENSOR_COLOR)
    })
    mesh.count = markers.length
    mesh.instanceMatrix.needsUpdate = true
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
  }, [markers])

  if (markers.length === 0) return null
  return (
    <instancedMesh
      ref={meshRef}
      args={[undefined, undefined, markers.length]}
      frustumCulled={false}
    >
      <tetrahedronGeometry args={[2.0, 0]} />
      <meshStandardMaterial roughness={0.5} metalness={0.15} />
    </instancedMesh>
  )
}
