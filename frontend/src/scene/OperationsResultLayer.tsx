import { Html } from '@react-three/drei'
import { useMemo, useState } from 'react'
import * as THREE from 'three'
import { mineToThree } from '@/geometry/coordinateTransform'
import { useResultsStore, type OperationsOverlay } from '@/stores/resultsStore'
import { displayRange } from '@/results/colorScale'
import { buildSegments, buildVertexColors, OVERLAY_LIFT_M } from '@/results/overlayGeometry'
import { fmtValue } from '@/results/format'

const VEHICLE_RADIUS = 2.4
const STATUS_COLORS: Record<string, string> = {
  LOADED: '#e08a4e',
  HAUL: '#e08a4e',
  EMPTY: '#8fb8de',
  RETURN: '#8fb8de',
}
const DEFAULT_VEHICLE_COLOR = '#f2c14e'

/**
 * Phase 23C — the operations overlay: the network operational heatmap
 * (line geometry over the source-snapshot edge centerlines coloured by the
 * selected edge metric of the backend frame; missing = neutral) and the
 * vehicle markers at the backend-projected XYZ of the frame. Positions
 * between samples on the SAME edge were interpolated by the backend; the
 * frontend never invents a route. Tooltip = agentId / kind / status / load.
 */
export function OperationsResultLayer({
  overlay,
  showHeatmap,
  showVehicles,
}: {
  overlay: OperationsOverlay
  showHeatmap: boolean
  showVehicles: boolean
}) {
  const metric = useResultsStore((s) => s.operationsMetric)
  const manual = useResultsStore((s) => s.operationsRange)
  const [hovered, setHovered] = useState<string | null>(null)
  const edges = overlay.geometry.edges
  const segments = useMemo(() => buildSegments(edges), [edges])
  const valueByEdge = useMemo(() => {
    const m = new Map<string, number>()
    for (const row of overlay.frame.edgeMetrics) {
      const v = row[metric]
      if (v !== null && Number.isFinite(v)) m.set(row.edgeId, v)
    }
    return m
  }, [overlay.frame, metric])
  const extent = useMemo(() => {
    let min: number | null = null
    let max: number | null = null
    for (const v of valueByEdge.values()) {
      min = min === null ? v : Math.min(min, v)
      max = max === null ? v : Math.max(max, v)
    }
    return { min, max }
  }, [valueByEdge])
  const range = displayRange(extent.min, extent.max, manual)
  const colors = useMemo(
    () => buildVertexColors(segments, edges, valueByEdge, range),
    [segments, edges, valueByEdge, range],
  )
  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(segments.positions, 3))
    g.setAttribute('color', new THREE.BufferAttribute(colors, 3))
    return g
  }, [segments, colors])
  return (
    <group>
      {showHeatmap ? (
        <lineSegments geometry={geometry}>
          <lineBasicMaterial vertexColors />
        </lineSegments>
      ) : null}
      {showVehicles
        ? overlay.frame.vehicles.map((v) => {
            const color =
              (v.status && STATUS_COLORS[v.status.toUpperCase()]) || DEFAULT_VEHICLE_COLOR
            return (
              <mesh
                key={v.agentId}
                position={mineToThree(v.x, v.y, v.z + OVERLAY_LIFT_M)}
                onPointerOver={(e) => {
                  e.stopPropagation()
                  setHovered(v.agentId)
                }}
                onPointerOut={() => setHovered((h) => (h === v.agentId ? null : h))}
              >
                <sphereGeometry args={[VEHICLE_RADIUS, 12, 12]} />
                <meshBasicMaterial color={color} />
                {hovered === v.agentId ? (
                  <Html distanceFactor={80} style={{ pointerEvents: 'none' }}>
                    <div className="whitespace-nowrap rounded-sm border border-rock-700 bg-rock-900/90 px-2 py-1 text-[11px] text-chalk">
                      <div className="plate">{v.agentId}</div>
                      <div className="text-chalk-dim">
                        {v.agentKind ?? '—'} · {v.status ?? '—'} · load{' '}
                        {v.loadTonnes === null ? '—' : `${fmtValue(v.loadTonnes, 1)} t`}
                      </div>
                      <div className="text-mute">
                        {v.edgeId} @ {v.chainageFraction.toFixed(2)} ({v.placement.toLowerCase()})
                      </div>
                    </div>
                  </Html>
                ) : null}
              </mesh>
            )
          })
        : null}
    </group>
  )
}
