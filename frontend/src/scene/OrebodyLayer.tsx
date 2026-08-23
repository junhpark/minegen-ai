import { useMemo } from 'react'
import * as THREE from 'three'
import { positionsToThree } from '@/geometry/coordinateTransform'
import type { OrebodyPayload } from '@/types/scene'

export function OrebodyLayer({ orebody }: { orebody: OrebodyPayload }) {
  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(positionsToThree(orebody.positions), 3))
    g.setIndex(orebody.indices)
    g.computeVertexNormals()
    return g
  }, [orebody])

  return (
    <group>
      <mesh geometry={geometry} userData={{ objectId: 'orebody', kind: 'orebody' }}>
        <meshStandardMaterial
          color="#4fb3a5"
          transparent
          opacity={0.35}
          side={THREE.DoubleSide}
          depthWrite={false}
          roughness={0.6}
        />
      </mesh>
      <lineSegments>
        <edgesGeometry args={[geometry]} />
        <lineBasicMaterial color="#4fb3a5" transparent opacity={0.9} />
      </lineSegments>
    </group>
  )
}
