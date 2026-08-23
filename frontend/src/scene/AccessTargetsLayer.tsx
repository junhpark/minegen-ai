import { Text } from '@react-three/drei'
import { useLayoutEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'
import { mineToThree } from '@/geometry/coordinateTransform'
import { useViewerStore } from '@/stores/viewerStore'
import type { AccessTargetsPayload } from '@/types/scene'

const VALID_COLOR = new THREE.Color('#f0b84a')
const REJECTED_COLOR = new THREE.Color('#d9655a')
const SELECTED_COLOR = new THREE.Color('#e4dfd3')

/**
 * Level-aware footwall access candidates (Phase 03).
 * - valid candidates: solid amber spheres
 * - rejected candidates: smaller red spheres with a ring
 * - level grouping: a thin line joins the candidates of a level, labelled at its end
 * - portal: chalk marker on the surface
 * Assembly only; all values come from the targets payload.
 */
export function AccessTargetsLayer({ targets }: { targets: AccessTargetsPayload }) {
  const all = useMemo(() => targets.levels.flatMap((l) => l.candidates), [targets])
  const selected = useViewerStore((s) => s.selectedObjectId)
  const select = useViewerStore((s) => s.select)
  const ref = useRef<THREE.InstancedMesh>(null)

  useLayoutEffect(() => {
    const mesh = ref.current
    if (!mesh) return
    const m = new THREE.Matrix4()
    all.forEach((c, i) => {
      const s = c.valid ? 1 : 0.6
      m.makeScale(s, s, s)
      m.setPosition(...mineToThree(...c.position))
      mesh.setMatrixAt(i, m)
      mesh.setColorAt(
        i,
        c.id === selected ? SELECTED_COLOR : c.valid ? VALID_COLOR : REJECTED_COLOR,
      )
    })
    mesh.instanceMatrix.needsUpdate = true
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
  }, [all, selected])

  const levelLines = useMemo(
    () =>
      targets.levels.map((l) => {
        const pts = l.candidates.map((c) => mineToThree(...c.position))
        const flat = new Float32Array(pts.flat())
        const last = pts[pts.length - 1] ?? [0, 0, 0]
        return { id: l.levelId, flat, labelPos: last, elevation: l.elevation, nValid: l.nValid }
      }),
    [targets],
  )

  return (
    <group>
      {all.length > 0 ? (
        <instancedMesh
          ref={ref}
          args={[undefined, undefined, all.length]}
          onClick={(e) => {
            e.stopPropagation()
            const id = e.instanceId
            if (id !== undefined) select(all[id]?.id ?? null)
          }}
          userData={{ kind: 'accessTargets' }}
        >
          <sphereGeometry args={[3.5, 12, 10]} />
          <meshStandardMaterial roughness={0.4} metalness={0.1} />
        </instancedMesh>
      ) : null}

      {levelLines.map((l) => (
        <group key={l.id}>
          <line>
            <bufferGeometry>
              <bufferAttribute attach="attributes-position" args={[l.flat, 3]} />
            </bufferGeometry>
            <lineBasicMaterial
              color={l.nValid > 0 ? '#b8801c' : '#d9655a'}
              transparent
              opacity={0.7}
            />
          </line>
          <Text
            position={[l.labelPos[0] + 12, l.labelPos[1] + 4, l.labelPos[2]]}
            fontSize={7}
            color={l.nValid > 0 ? '#f0b84a' : '#d9655a'}
            anchorX="left"
            anchorY="middle"
          >
            {`${l.id}  ${l.elevation.toFixed(0)} m`}
          </Text>
        </group>
      ))}

      <mesh position={mineToThree(...targets.portal)}>
        <coneGeometry args={[6, 14, 4]} />
        <meshStandardMaterial color="#e4dfd3" emissive="#e4dfd3" emissiveIntensity={0.3} />
      </mesh>
      <Text
        position={mineToThree(targets.portal[0], targets.portal[1], targets.portal[2] + 22)}
        fontSize={9}
        color="#e4dfd3"
        anchorX="center"
        anchorY="middle"
      >
        {targets.portalGenerated ? 'PORTAL (auto)' : 'PORTAL'}
      </Text>
    </group>
  )
}
