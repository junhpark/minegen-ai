import { useEffect, useMemo, useRef } from 'react'
import type { SmoothedDeclinePayload } from '@/types/scene'
import {
  approximateChainage,
  bearingDegFromYaw,
  buildMinimapModel,
  MINIMAP_RADIUS_M,
  mineXYToMap,
} from './minimap'
import type { WalkthroughTelemetry } from './telemetry'

const SIZE = 176 // px
const SCALE = SIZE / (MINIMAP_RADIUS_M * 2) // px per metre

/**
 * North-up FOLLOW minimap (§12–19): a pure SVG overlay — no second Three
 * canvas, zero GPU draw calls. The centerline/portal are rendered ONCE
 * from the authoritative effective smoothed centerline (temporal contexts
 * receive only the ACTIVE prefix, future segments hidden); an 8 Hz
 * interval reads the shared telemetry ref and mutates transform/text
 * attributes directly — no per-frame React state. Position readout shows
 * E/N/RL plus approximate chainage (nearest centerline segment, computed
 * at the same 8 Hz).
 */
export function MinimapOverlay({
  smoothed,
  activeSegmentIds,
  telemetry,
}: {
  smoothed: SmoothedDeclinePayload
  activeSegmentIds: readonly string[] | null
  telemetry: WalkthroughTelemetry
}) {
  const model = useMemo(
    () => buildMinimapModel(smoothed, activeSegmentIds),
    [smoothed, activeSegmentIds],
  )
  const world = useRef<SVGGElement | null>(null)
  const arrow = useRef<SVGGElement | null>(null)
  const readout = useRef<HTMLDivElement | null>(null)
  const modeLine = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const id = window.setInterval(() => {
      const [e, n, rl] = telemetry.mine()
      if (world.current) {
        const [mx, my] = mineXYToMap(e, n)
        // FOLLOW: shift the world group so the player sits at the center
        world.current.setAttribute(
          'transform',
          `translate(${(SIZE / 2 - mx * SCALE).toFixed(1)} ${(SIZE / 2 - my * SCALE).toFixed(1)})`,
        )
      }
      if (arrow.current) {
        arrow.current.setAttribute(
          'transform',
          `translate(${SIZE / 2} ${SIZE / 2}) rotate(${bearingDegFromYaw(telemetry.headingYaw).toFixed(1)})`,
        )
      }
      if (readout.current) {
        const ch = approximateChainage([e, n, rl], model.chainagePoints)
        readout.current.textContent =
          `E ${e >= 0 ? '+' : ''}${e.toFixed(0)} m  N ${n >= 0 ? '+' : ''}${n.toFixed(0)} m\n` +
          `RL ${rl.toFixed(0)} m${ch ? `  CH ${ch.chainageM.toFixed(0)} m` : ''}`
      }
      if (modeLine.current) {
        modeLine.current.textContent = `${telemetry.mode}\nSpeed ${telemetry.speed.toFixed(1)} m/s`
      }
    }, 125)
    return () => window.clearInterval(id)
  }, [telemetry, model])

  return (
    <div className="pointer-events-none absolute left-3 top-3 flex flex-col gap-1">
      <svg
        width={SIZE}
        height={SIZE}
        className="rounded-sm border border-rock-700 bg-rock-950/85"
        role="img"
        aria-label="Minimap"
      >
        <g ref={world}>
          {model.polylines.map((p) => {
            const d = []
            for (let i = 0; i + 1 < p.xy.length; i += 2) {
              const [mx, my] = mineXYToMap(p.xy[i]!, p.xy[i + 1]!)
              d.push(`${i === 0 ? 'M' : 'L'}${(mx * SCALE).toFixed(1)} ${(my * SCALE).toFixed(1)}`)
            }
            return (
              <path
                key={p.segmentId}
                d={d.join(' ')}
                fill="none"
                stroke="#c9a35a"
                strokeWidth={1.6}
              />
            )
          })}
          {model.portal ? (
            <circle
              cx={mineXYToMap(...model.portal)[0] * SCALE}
              cy={mineXYToMap(...model.portal)[1] * SCALE}
              r={3.4}
              fill="#7fd18a"
            />
          ) : null}
          {model.end ? (
            <circle
              cx={mineXYToMap(...model.end)[0] * SCALE}
              cy={mineXYToMap(...model.end)[1] * SCALE}
              r={2.6}
              fill="#8a95a1"
            />
          ) : null}
        </g>
        {/* player: fixed at center, arrow rotated by compass bearing */}
        <g ref={arrow}>
          <polygon points="0,-6 4.2,4.6 0,2.2 -4.2,4.6" fill="#ffd894" />
        </g>
        {/* north indicator */}
        <text x={SIZE - 12} y={14} fill="#8a95a1" fontSize={10} className="readout">
          N
        </text>
        <line x1={SIZE - 8} y1={18} x2={SIZE - 8} y2={8} stroke="#8a95a1" strokeWidth={1} />
      </svg>
      <div
        ref={modeLine}
        className="readout whitespace-pre rounded-sm bg-rock-900/80 px-2 py-1 text-[11px] text-lamp"
      />
      <div
        ref={readout}
        className="readout whitespace-pre rounded-sm bg-rock-900/70 px-2 py-1 text-[10px] text-chalk-dim"
      />
    </div>
  )
}
