import { useMemo } from 'react'
import * as THREE from 'three'
import { positionsToThree } from '@/geometry/coordinateTransform'
import type { FaultPayload } from '@/types/scene'

function FaultPolygon({ fault }: { fault: FaultPayload }) {
  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(positionsToThree(fault.polygon), 3))
    const idx: number[] = []
    for (let i = 1; i < fault.vertexCount - 1; i++) idx.push(0, i, i + 1) // fan
    g.setIndex(idx)
    g.computeVertexNormals()
    return g
  }, [fault])

  return (
    <group>
      <mesh geometry={geometry} userData={{ objectId: fault.id, kind: 'fault' }}>
        <meshBasicMaterial
          color="#d9655a"
          transparent
          opacity={0.22}
          side={THREE.DoubleSide}
          depthWrite={false}
        />
      </mesh>
      <lineSegments>
        <edgesGeometry args={[geometry]} />
        <lineBasicMaterial color="#d9655a" />
      </lineSegments>
    </group>
  )
}

export function FaultLayer({ faults }: { faults: FaultPayload[] }) {
  return (
    <group>
      {faults.map((f) => (
        <FaultPolygon key={f.id} fault={f} />
      ))}
    </group>
  )
}
