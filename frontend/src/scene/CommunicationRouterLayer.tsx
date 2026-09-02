import { useLayoutEffect, useMemo, useRef } from 'react'
import { useViewerStore } from '@/stores/viewerStore'
import * as THREE from 'three'
import { mineToThree } from '@/geometry/coordinateTransform'
import { routerMarkers } from '@/infrastructure/view'
import type { CommunicationPayload } from '@/types/scene'

const ROUTER_COLOR = new THREE.Color('#4ac8f0')
const ROOT_COLOR = new THREE.Color('#f0b84a')

/**
 * Phase 11 selected MESH_ROUTER markers (rules 89/92): pure assembly of
 * backend-selected placements. Positions are tunnel-centerline planning
 * references converted only through mineToThree — the frontend invents no
 * wall-mount offset, no coverage sphere and no through-rock backhaul beam.
 */
export function CommunicationRouterLayer({
  communication,
}: {
  communication: CommunicationPayload
}) {
  const markers = useMemo(() => routerMarkers(communication), [communication])
  const meshRef = useRef<THREE.InstancedMesh>(null)
  const select = useViewerStore((s) => s.select)

  useLayoutEffect(() => {
    const mesh = meshRef.current
    if (!mesh) return
    const m = new THREE.Matrix4()
    markers.forEach((marker, i) => {
      m.setPosition(...mineToThree(...marker.position))
      mesh.setMatrixAt(i, m)
      mesh.setColorAt(i, marker.hopCount === 0 ? ROOT_COLOR : ROUTER_COLOR)
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
      onClick={(e) => {
        // hotfix 2 (item 12): orbit-mode click selection — the transient
        // instanceId only LOOKS UP the authoritative backend asset id
        // (rule 109: indices never become identity)
        e.stopPropagation()
        const i = e.instanceId
        const marker = i != null ? markers[i] : undefined
        if (marker) select(marker.id)
      }}
    >
      <octahedronGeometry args={[2.2, 0]} />
      <meshStandardMaterial roughness={0.4} metalness={0.2} />
    </instancedMesh>
  )
}
