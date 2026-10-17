import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { Group, MeshStandardMaterial } from 'three'
import type { VehiclePreset } from './vehicle'

/**
 * Procedural third-person avatars (hardening PR-4 W2). Low-poly primitives
 * assembled from three.js geometries — no external asset, no animation rig,
 * no physics of their own (the kinematic body / collider is the player's).
 * Every avatar is authored in the body frame of its RigidBody: origin at
 * the body centre (`bodyHeightM / 2` above the floor), +Y up, −Z forward
 * (the camera convention `movement.ts` uses). Visualization only — a truck
 * avatar is the preset's planning box dressed up, never a product model.
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

function Wheel({ x, z, y, r }: { x: number; z: number; y: number; r: number }) {
  return (
    <group position={[x, y, z]} rotation={[0, 0, Math.PI / 2]}>
      <mesh material={M.tyre}>
        <cylinderGeometry args={[r, r, 0.6, 16]} />
      </mesh>
      <mesh material={M.rim}>
        <cylinderGeometry args={[r * 0.55, r * 0.55, 0.62, 12]} />
      </mesh>
    </group>
  )
}

/**
 * Truck dressed on the preset's planning box: articulated (front power unit
 * + rear dump body on separate chassis) or rigid (one chassis). Length along
 * −Z (front at negative z), width along X, height along Y; the box floor is
 * at −heightM / 2.
 */
export function TruckAvatar({ preset }: { preset: VehiclePreset }) {
  const L = preset.lengthM
  const W = preset.widthM
  const H = preset.heightM
  const floor = -H / 2
  const r = preset.wheelRadiusM
  const axleY = floor + r
  const frontL = preset.articulated ? L * 0.42 : L * 0.3
  const rearL = preset.articulated ? L * 0.52 : L * 0.68
  const frontZ = -L / 2 + frontL / 2
  const rearZ = L / 2 - rearL / 2
  const chassisH = Math.max(0.5, H * 0.22)
  const chassisY = axleY + chassisH / 2
  // the bin top is EXACTLY the preset height: the visual envelope never
  // exceeds the collider box (the chase anchor sits on that roof)
  const binH = H - r - chassisH
  const cabH = H - r - chassisH
  return (
    <group>
      {/* front power unit / rigid front */}
      <mesh position={[0, chassisY, frontZ]} material={M.truck}>
        <boxGeometry args={[W * 0.92, chassisH, frontL]} />
      </mesh>
      {/* engine hood */}
      <mesh
        position={[0, chassisY + chassisH / 2 + H * 0.17, -L / 2 + frontL * 0.72]}
        material={M.truck}
      >
        <boxGeometry args={[W * 0.78, H * 0.34, frontL * 0.5]} />
      </mesh>
      {/* cab, left-hand side */}
      <group position={[-W * 0.18, chassisY + chassisH / 2 + cabH / 2, -L / 2 + frontL * 0.3]}>
        <mesh material={M.truck}>
          <boxGeometry args={[W * 0.5, cabH, frontL * 0.42]} />
        </mesh>
        <mesh position={[0, cabH * 0.15, -frontL * 0.215]} material={M.glass}>
          <boxGeometry args={[W * 0.42, cabH * 0.5, 0.02]} />
        </mesh>
      </group>
      {/* rear chassis + dump body */}
      <mesh position={[0, chassisY, rearZ]} material={M.truck}>
        <boxGeometry args={[W * 0.92, chassisH, rearL]} />
      </mesh>
      <mesh
        position={[0, chassisY + chassisH / 2 + binH / 2, rearZ + rearL * 0.02]}
        material={M.bin}
      >
        <boxGeometry args={[W, binH, rearL * 0.96]} />
      </mesh>
      {/* articulation hinge */}
      {preset.articulated ? (
        <mesh
          position={[0, chassisY, -L / 2 + frontL + (L - frontL - rearL) / 2]}
          material={M.dark}
        >
          <boxGeometry args={[W * 0.4, chassisH * 0.8, L - frontL - rearL + 0.2]} />
        </mesh>
      ) : null}
      {/* wheels */}
      <Wheel x={-(W / 2 - 0.3)} z={-L / 2 + frontL * 0.55} y={axleY} r={r} />
      <Wheel x={W / 2 - 0.3} z={-L / 2 + frontL * 0.55} y={axleY} r={r} />
      <Wheel x={-(W / 2 - 0.3)} z={L / 2 - rearL * 0.45} y={axleY} r={r} />
      <Wheel x={W / 2 - 0.3} z={L / 2 - rearL * 0.45} y={axleY} r={r} />
      {!preset.articulated ? (
        <>
          <Wheel x={-(W / 2 - 0.3)} z={L / 2 - rearL * 0.15} y={axleY} r={r} />
          <Wheel x={W / 2 - 0.3} z={L / 2 - rearL * 0.15} y={axleY} r={r} />
        </>
      ) : null}
      {/* headlights */}
      <mesh position={[-W * 0.3, chassisY + chassisH * 0.3, -L / 2 - 0.02]} material={M.headlight}>
        <boxGeometry args={[0.3, 0.16, 0.05]} />
      </mesh>
      <mesh position={[W * 0.3, chassisY + chassisH * 0.3, -L / 2 - 0.02]} material={M.headlight}>
        <boxGeometry args={[0.3, 0.16, 0.05]} />
      </mesh>
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
