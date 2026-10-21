import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import {
  BoxGeometry,
  EdgesGeometry,
  Group,
  LineBasicMaterial,
  type Material,
  MeshStandardMaterial,
} from 'three'
import { GHOST_OPACITY } from './cameraView'
import { truckLayout, type VehiclePreset } from './vehicle'

/**
 * Procedural third-person avatars (hardening PR-4 W2, PR-6 ghost / cab).
 * Low-poly primitives assembled from three.js geometries — no external
 * asset, no animation rig, no physics of their own (the kinematic body /
 * collider is the player's). Every avatar is authored in the body frame of
 * its RigidBody: origin at the body centre (`bodyHeightM / 2` above the
 * floor), +Y up, −Z forward (the camera convention `movement.ts` uses).
 * Visualization only — a truck avatar is the preset's planning box dressed
 * up (`vehicle.ts::truckLayout`, the one layout authority), never a
 * product model.
 *
 * PR-6: the truck is drawn as a GHOST in either view (translucent body,
 * depth write off, planning-box edges outlined so the envelope stays
 * legible while the drive ahead shows through) and without its cab shell
 * in the CAB view (the camera sits inside the cab box, so the shell and its
 * windscreen are not drawn from inside; the hood below the seat reads as
 * an outline over the floor when the driver looks down). Materials are module constants
 * shared by every instance; the ghost set is a one-time clone.
 */

const M = {
  hiVis: new MeshStandardMaterial({ color: '#ff7a1a', roughness: 0.8 }),
  helmet: new MeshStandardMaterial({ color: '#f2c200', roughness: 0.5 }),
  skin: new MeshStandardMaterial({ color: '#d9b38c', roughness: 0.9 }),
  dark: new MeshStandardMaterial({ color: '#2b2f33', roughness: 0.9 }),
  lamp: new MeshStandardMaterial({ color: '#fff4c2', emissive: '#ffe9a8', emissiveIntensity: 1.4 }),
  truck: new MeshStandardMaterial({ color: '#e0a526', roughness: 0.65, metalness: 0.15 }),
  bin: new MeshStandardMaterial({ color: '#4a4f55', roughness: 0.9, metalness: 0.2 }),
  tyre: new MeshStandardMaterial({ color: '#1b1d1f', roughness: 1 }),
  rim: new MeshStandardMaterial({ color: '#8a8f94', roughness: 0.6, metalness: 0.4 }),
  glass: new MeshStandardMaterial({ color: '#7fb3d5', roughness: 0.2, metalness: 0.1 }),
  headlight: new MeshStandardMaterial({
    color: '#fff7d6',
    emissive: '#fff1b8',
    emissiveIntensity: 1.2,
  }),
  drone: new MeshStandardMaterial({ color: '#2f3b46', roughness: 0.7, metalness: 0.3 }),
  rotor: new MeshStandardMaterial({
    color: '#b8c4cf',
    roughness: 0.4,
    transparent: true,
    opacity: 0.7,
  }),
  ledGreen: new MeshStandardMaterial({
    color: '#4cff7a',
    emissive: '#2bff66',
    emissiveIntensity: 1.5,
  }),
  ledRed: new MeshStandardMaterial({
    color: '#ff5a4c',
    emissive: '#ff3b2b',
    emissiveIntensity: 1.5,
  }),
}

type TruckMaterialKey = 'truck' | 'bin' | 'tyre' | 'rim' | 'glass' | 'headlight' | 'dark'

/** Ghost variants of the truck materials (PR-6): translucent, no depth
 * write (overlapping parts never punch holes into each other), otherwise
 * the same colour / roughness. Cloned once. */
const GHOST: Record<TruckMaterialKey, MeshStandardMaterial> = (() => {
  const keys: TruckMaterialKey[] = ['truck', 'bin', 'tyre', 'rim', 'glass', 'headlight', 'dark']
  const out = {} as Record<TruckMaterialKey, MeshStandardMaterial>
  for (const k of keys) {
    const m = M[k].clone()
    m.transparent = true
    m.opacity = GHOST_OPACITY
    m.depthWrite = false
    out[k] = m
  }
  return out
})()

/** Outline of the ghost's planning boxes. */
const GHOST_EDGE = new LineBasicMaterial({ color: '#f5d27a', transparent: true, opacity: 0.85 })

/** Upright miner: body 1.7 m (capsule centre at the origin), hi-vis torso,
 * helmet with a forward cap lamp. */
export function PersonAvatar({ bodyHeightM }: { bodyHeightM: number }) {
  const floor = -bodyHeightM / 2
  return (
    <group>
      {/* legs */}
      <mesh position={[-0.11, floor + 0.3, 0]} material={M.dark}>
        <cylinderGeometry args={[0.09, 0.09, 0.6, 8]} />
      </mesh>
      <mesh position={[0.11, floor + 0.3, 0]} material={M.dark}>
        <cylinderGeometry args={[0.09, 0.09, 0.6, 8]} />
      </mesh>
      {/* torso */}
      <mesh position={[0, floor + 0.95, 0]} material={M.hiVis}>
        <capsuleGeometry args={[0.22, 0.55, 4, 10]} />
      </mesh>
      {/* arms */}
      <mesh position={[-0.3, floor + 0.98, 0]} material={M.hiVis}>
        <cylinderGeometry args={[0.06, 0.06, 0.55, 8]} />
      </mesh>
      <mesh position={[0.3, floor + 0.98, 0]} material={M.hiVis}>
        <cylinderGeometry args={[0.06, 0.06, 0.55, 8]} />
      </mesh>
      {/* head + helmet + cap lamp */}
      <mesh position={[0, floor + 1.47, 0]} material={M.skin}>
        <sphereGeometry args={[0.13, 12, 10]} />
      </mesh>
      <mesh position={[0, floor + 1.53, 0]} material={M.helmet}>
        <sphereGeometry args={[0.16, 12, 10, 0, Math.PI * 2, 0, Math.PI * 0.6]} />
      </mesh>
      <mesh position={[0, floor + 1.55, -0.15]} material={M.lamp}>
        <boxGeometry args={[0.08, 0.06, 0.06]} />
      </mesh>
    </group>
  )
}

function Wheel({
  x,
  z,
  y,
  r,
  ghost,
}: {
  x: number
  z: number
  y: number
  r: number
  ghost: boolean
}) {
  const mat = ghost ? GHOST : M
  return (
    <group position={[x, y, z]} rotation={[0, 0, Math.PI / 2]}>
      <mesh material={mat.tyre}>
        <cylinderGeometry args={[r, r, 0.6, 16]} />
      </mesh>
      <mesh material={mat.rim}>
        <cylinderGeometry args={[r * 0.55, r * 0.55, 0.62, 12]} />
      </mesh>
    </group>
  )
}

/** One planning box of the truck: the mesh, plus its outlined edges when
 * drawn as a ghost (the geometry is owned here and disposed on unmount). */
function TruckBoxMesh({
  center,
  size,
  material,
  ghost,
}: {
  center: readonly [number, number, number]
  size: readonly [number, number, number]
  material: Material
  ghost: boolean
}) {
  const geometry = useMemo(() => new BoxGeometry(size[0], size[1], size[2]), [size])
  const edges = useMemo(() => (ghost ? new EdgesGeometry(geometry) : null), [geometry, ghost])
  useEffect(
    () => () => {
      geometry.dispose()
      edges?.dispose()
    },
    [geometry, edges],
  )
  return (
    <group position={[center[0], center[1], center[2]]}>
      <mesh geometry={geometry} material={material} />
      {edges ? <lineSegments geometry={edges} material={GHOST_EDGE} /> : null}
    </group>
  )
}

/**
 * Truck dressed on the preset's planning box (`truckLayout`): articulated
 * (front power unit + rear dump body on separate chassis) or rigid (one
 * chassis). Length along −Z (front at negative z), width along X, height
 * along Y; the box floor is at −heightM / 2. `ghost` draws the translucent
 * outlined body of the chase view; `cabVisible = false` omits the cab shell
 * and its windscreen (the CAB view sits inside them).
 */
export function TruckAvatar({
  preset,
  ghost = false,
  cabVisible = true,
}: {
  preset: VehiclePreset
  ghost?: boolean
  cabVisible?: boolean
}) {
  const layout = useMemo(() => truckLayout(preset), [preset])
  const mat = ghost ? GHOST : M
  const materialOf = (id: (typeof layout.boxes)[number]['id']): Material => {
    if (id === 'BIN') return mat.bin
    if (id === 'CAB_GLASS') return mat.glass
    if (id === 'HINGE') return mat.dark
    return mat.truck
  }
  return (
    <group>
      {layout.boxes.map((b) =>
        !cabVisible && (b.id === 'CAB' || b.id === 'CAB_GLASS') ? null : (
          <TruckBoxMesh
            key={b.id}
            center={b.center}
            size={b.size}
            material={materialOf(b.id)}
            ghost={ghost && b.id !== 'CAB_GLASS'}
          />
        ),
      )}
      {layout.wheels.map(([x, z]) => (
        <Wheel
          key={`${x},${z}`}
          x={x}
          z={z}
          y={layout.axleY}
          r={preset.wheelRadiusM}
          ghost={ghost}
        />
      ))}
      {layout.headlights.map((p) => (
        <mesh key={`h${p[0]}`} position={[p[0], p[1], p[2]]} material={mat.headlight}>
          <boxGeometry args={[0.3, 0.16, 0.05]} />
        </mesh>
      ))}
    </group>
  )
}

/** Quad-rotor inspection drone: body, four arms, spinning rotor discs,
 * green (front) / red (rear) LEDs. */
export function DroneAvatar() {
  const rotors = useRef<Group>(null)
  const arms = useMemo(
    () =>
      [
        [0.42, 0.42],
        [-0.42, 0.42],
        [0.42, -0.42],
        [-0.42, -0.42],
      ] as const,
    [],
  )
  useFrame((_, dt) => {
    if (rotors.current) rotors.current.rotation.y += dt * 18
  })
  return (
    <group>
      <mesh material={M.drone}>
        <boxGeometry args={[0.5, 0.18, 0.5]} />
      </mesh>
      {arms.map(([x, z]) => (
        <mesh
          key={`${x},${z}`}
          position={[x / 2, 0, z / 2]}
          rotation={[0, Math.atan2(x, z), 0]}
          material={M.drone}
        >
          <boxGeometry args={[0.06, 0.05, 0.62]} />
        </mesh>
      ))}
      <group ref={rotors}>
        {arms.map(([x, z]) => (
          <mesh key={`r${x},${z}`} position={[x, 0.1, z]} material={M.rotor}>
            <cylinderGeometry args={[0.26, 0.26, 0.015, 14]} />
          </mesh>
        ))}
      </group>
      <mesh position={[0, 0.04, -0.3]} material={M.ledGreen}>
        <sphereGeometry args={[0.04, 8, 6]} />
      </mesh>
      <mesh position={[0, 0.04, 0.3]} material={M.ledRed}>
        <sphereGeometry args={[0.04, 8, 6]} />
      </mesh>
      <mesh position={[0, -0.12, -0.1]} material={M.lamp}>
        <boxGeometry args={[0.12, 0.06, 0.08]} />
      </mesh>
    </group>
  )
}
