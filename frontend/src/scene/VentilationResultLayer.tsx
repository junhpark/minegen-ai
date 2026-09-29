import { useMemo } from 'react'
import * as THREE from 'three'
import { useResultsStore, type VentilationOverlay } from '@/stores/resultsStore'
import { displayRange } from '@/results/colorScale'
import { buildArrows, buildSegments, buildVertexColors } from '@/results/overlayGeometry'

const ARROW_LENGTH = 6
const ARROW_RADIUS = 1.6

/**
 * Phase 23C — the ventilation overlay: SEPARATE line geometry over the
 * result's source-snapshot edge centerlines, coloured by the active metric
 * of the backend frame (missing edges stay neutral, never zero), plus
 * optional airflow arrows whose sense is the sign of the value along the
 * MineNetwork edge axis. The base tunnel / centerline layers are untouched;
 * no engineering or simulation quantity is computed here.
 */
export function VentilationResultLayer({ overlay }: { overlay: VentilationOverlay }) {
  const manual = useResultsStore((s) => s.ventilationRange)
  const showArrows = useResultsStore((s) => s.showAirflowArrows)
  const edges = overlay.geometry.edges
  const segments = useMemo(() => buildSegments(edges), [edges])
  const valueByEdge = useMemo(
    () => new Map(overlay.frame.values.map((v) => [v.edgeId, v.value] as const)),
    [overlay.frame],
  )
  const range = displayRange(overlay.frame.min, overlay.frame.max, manual)
  const colors = useMemo(
    () => buildVertexColors(segments, edges, valueByEdge, range),
    [segments, edges, valueByEdge, range],
  )
  const arrows = useMemo(
    () =>
      showArrows && overlay.frame.metric === 'airflowM3s' ? buildArrows(edges, valueByEdge) : [],
    [showArrows, overlay.frame.metric, edges, valueByEdge],
  )
  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(segments.positions, 3))
    g.setAttribute('color', new THREE.BufferAttribute(colors, 3))
    return g
  }, [segments, colors])
  return (
    <group>
      <lineSegments geometry={geometry}>
        <lineBasicMaterial vertexColors />
      </lineSegments>
      {arrows.map((a) => {
        const dir = new THREE.Vector3(...a.direction).normalize()
        const q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir)
        return (
          <mesh key={a.edgeId} position={a.position} quaternion={q}>
            <coneGeometry args={[ARROW_RADIUS, ARROW_LENGTH, 8]} />
            <meshBasicMaterial color="#f2c14e" />
          </mesh>
        )
      })}
    </group>
  )
}
