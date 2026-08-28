import { useMemo } from 'react'
import { positionsToThree } from '@/geometry/coordinateTransform'
import type { LevelsPayload } from '@/types/scene'

const DRIFT_COLOR = '#8fb8de'
const CROSSCUT_COLOR = '#deb46a'
const INVALID_COLOR = '#d9655a'

/**
 * Phase 08 level developments (rules 71–74): renders the backend-provided
 * drift/crosscut centerlines exactly as delivered in levels.json. No
 * engineering geometry is computed here (rule 32) — this is a pure polyline
 * visualization; the volumetric development mesh is deferred by design.
 */
export function LevelDevelopmentLayer({
  levels,
  showDrifts,
  showCrosscuts,
}: {
  levels: LevelsPayload
  showDrifts: boolean
  showCrosscuts: boolean
}) {
  const lines = useMemo(
    () =>
      levels.developments
        .filter((d) => (d.kind === 'DRIFT' ? showDrifts : showCrosscuts))
        .map((d) => ({
          key: d.id,
          color: !d.report.valid
            ? INVALID_COLOR
            : d.kind === 'DRIFT'
              ? DRIFT_COLOR
              : CROSSCUT_COLOR,
          positions: positionsToThree(d.centerline.points),
        })),
    [levels, showDrifts, showCrosscuts],
  )

  return (
    <group>
      {lines.map((l) => (
        <line key={l.key}>
          <bufferGeometry>
            <bufferAttribute attach="attributes-position" args={[l.positions, 3]} />
          </bufferGeometry>
          <lineBasicMaterial color={l.color} transparent opacity={0.9} />
        </line>
      ))}
    </group>
  )
}
