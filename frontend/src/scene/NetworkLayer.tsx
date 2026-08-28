import { useMemo } from 'react'
import { mineToThree } from '@/geometry/coordinateTransform'
import type { NetworkPayload } from '@/types/scene'

const NODE_COLORS: Record<string, string> = {
  PORTAL: '#f2c14e',
  LEVEL_ENTRY: '#7fd4b8',
  JUNCTION: '#9aa3ad',
  STOPE_ACCESS: '#e08a4e',
}
const NODE_SIZES: Record<string, number> = {
  PORTAL: 8,
  LEVEL_ENTRY: 6,
  JUNCTION: 3.5,
  STOPE_ACCESS: 4.5,
}
const EDGE_COLORS: Record<string, string> = {
  RAMP: '#7fd4b8',
  DRIFT: '#8fb8de',
  CROSSCUT: '#deb46a',
  RAISE: '#c7a0e8',
  SHAFT: '#c7a0e8',
}

/**
 * Phase 08 MineNetwork overlay (rule 73): nodes and straight edge chords
 * exactly as delivered in network.json. This is the GRAPH visualization —
 * true curved geometry stays with the owning centerline layers; the chord
 * only communicates topology (rule 13 keeps them siblings, not derivations).
 */
export function NetworkLayer({ network }: { network: NetworkPayload }) {
  const nodeGroups = useMemo(() => {
    const byType = new Map<string, number[]>()
    for (const n of network.nodes) {
      const p = mineToThree(n.position[0], n.position[1], n.position[2])
      const arr = byType.get(n.type) ?? []
      arr.push(p[0], p[1], p[2])
      byType.set(n.type, arr)
    }
    return [...byType.entries()].map(([type, coords]) => ({
      type,
      positions: new Float32Array(coords),
    }))
  }, [network])

  const edgeGroups = useMemo(() => {
    const pos = new Map<string, [number, number, number]>()
    for (const n of network.nodes) {
      pos.set(n.id, mineToThree(n.position[0], n.position[1], n.position[2]))
    }
    const byType = new Map<string, number[]>()
    for (const e of network.edges) {
      const a = pos.get(e.fromNode)
      const b = pos.get(e.toNode)
      if (!a || !b) continue
      const arr = byType.get(e.type) ?? []
      arr.push(...a, ...b)
      byType.set(e.type, arr)
    }
    return [...byType.entries()].map(([type, coords]) => ({
      type,
      positions: new Float32Array(coords),
    }))
  }, [network])

  return (
    <group>
      {edgeGroups.map((g) => (
        <lineSegments key={`edges-${g.type}`}>
          <bufferGeometry>
            <bufferAttribute attach="attributes-position" args={[g.positions, 3]} />
          </bufferGeometry>
          <lineBasicMaterial color={EDGE_COLORS[g.type] ?? '#888888'} transparent opacity={0.55} />
        </lineSegments>
      ))}
      {nodeGroups.map((g) => (
        <points key={`nodes-${g.type}`}>
          <bufferGeometry>
            <bufferAttribute attach="attributes-position" args={[g.positions, 3]} />
          </bufferGeometry>
          <pointsMaterial
            color={NODE_COLORS[g.type] ?? '#ffffff'}
            size={NODE_SIZES[g.type] ?? 4}
            sizeAttenuation
            transparent
            opacity={0.95}
          />
        </points>
      ))}
    </group>
  )
}
