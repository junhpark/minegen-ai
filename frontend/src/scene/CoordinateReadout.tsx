import { threeToMine } from '@/geometry/coordinateTransform'
import { fmtCoord } from '@/utils/format'

interface Props {
  /** orbit target in Three.js coordinates; converted for display only */
  threeTarget: [number, number, number]
}

/**
 * Total-station style readout of the orbit target in mine coordinates.
 * Display only: the conversion exists so a user can sanity-check ENU values
 * against the backend at a glance.
 */
export function CoordinateReadout({ threeTarget }: Props) {
  const [e, n, z] = threeToMine(...threeTarget)
  return (
    <div
      className="readout pointer-events-none absolute right-3 bottom-3 flex gap-4 rounded-sm border border-rock-700 bg-rock-900/85 px-3 py-1.5 text-[11px] text-chalk-dim"
      aria-label="orbit target in mine coordinates"
    >
      <span>
        <span className="text-mute">E </span>
        {fmtCoord(e)}
      </span>
      <span>
        <span className="text-mute">N </span>
        {fmtCoord(n)}
      </span>
      <span>
        <span className="text-mute">Z </span>
        {fmtCoord(z)}
      </span>
      <span className="text-mute">m · ENU</span>
    </div>
  )
}
