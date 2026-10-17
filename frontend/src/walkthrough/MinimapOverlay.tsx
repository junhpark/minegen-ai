import { useEffect, useMemo, useRef, useState } from 'react'
import type { WorldScene } from '@/types/scene'
import { tr } from '@/i18n/t'
import {
  buildLadderModel,
  buildLevelMapModel,
  collectLevels,
  levelHalfBand,
  pickLevel,
  portalRl,
  projectToMap,
  type LevelRef,
  type MapLineKind,
  type MapMarkerKind,
} from './levelMap'
import { approximateChainage, bearingDegFromYaw, buildMinimapModel } from './minimap'
import type { WalkthroughTelemetry } from './telemetry'

const SIZE = 176 // px, square map
const LADDER_W = 34 // px, level ladder beside the map
const LADDER_PAD = 10

const LINE_STYLE: Record<MapLineKind, { stroke: string; width: number; dash?: string }> = {
  RAMP: { stroke: '#c9a35a', width: 2.0 },
  ACCESS: { stroke: '#e8a33d', width: 1.6 },
  DRIFT: { stroke: '#d8dde2', width: 1.7 },
  CROSSCUT: { stroke: '#8a95a1', width: 1.1 },
}
const MARKER_STYLE: Record<MapMarkerKind, { fill: string; r: number }> = {
  PORTAL: { fill: '#7fd18a', r: 3.4 },
  TURNOUT: { fill: '#e8a33d', r: 2.8 },
  ENTRY: { fill: '#ffd894', r: 3.0 },
  STOPE_ACCESS: { fill: '#8a95a1', r: 1.8 },
  SHAFT_STATION: { fill: '#43c6b8', r: 2.6 },
}

/**
 * Level-aware minimap (PR-4 W3; replaces the Phase 16 FOLLOW map): a pure SVG
 * overlay — no second Three canvas, zero GPU draw calls. The avatar's RL
 * (sampled from the shared telemetry at 8 Hz) picks the level shown; the
 * level map is rebuilt ONLY when the picked level changes, fitted north-up
 * to that level's development, and the avatar arrow is placed inside it by
 * attribute writes. The ladder on the right places the RL among every
 * level. Temporal contexts receive only the ACTIVE ramp prefix / ACTIVE
 * development pieces, so the map can never imply a walkable future.
 */
export function MinimapOverlay({
  scene,
  activeSegmentIds,
  activePieceIds,
  telemetry,
}: {
  scene: WorldScene
  /** TIMELINE_SNAPSHOT: the ACTIVE ramp prefix; null = every segment */
  activeSegmentIds: readonly string[] | null
  /** TIMELINE_SNAPSHOT: the ACTIVE development pieces; null = every piece */
  activePieceIds: ReadonlySet<string> | null
  telemetry: WalkthroughTelemetry
}) {
  const levels = useMemo(() => collectLevels(scene), [scene])
  const halfBand = useMemo(() => levelHalfBand(levels), [levels])
  const ramp = useMemo(
    () => buildMinimapModel(scene.smoothedDecline, activeSegmentIds),
    [scene.smoothedDecline, activeSegmentIds],
  )
  const [level, setLevel] = useState<LevelRef | null>(null)
  // the ramp band follows the RL only between levels: quantize so the fitted
  // bounds do not jitter with every metre of descent
  const [bandRl, setBandRl] = useState(0)
  const model = useMemo(
    () =>
      buildLevelMapModel({
        scene,
        level,
        rl: bandRl,
        halfBand,
        activeRampSegmentIds: activeSegmentIds,
        activePieceIds,
      }),
    [scene, level, bandRl, halfBand, activeSegmentIds, activePieceIds],
  )
  const surface = useMemo(() => portalRl(scene.smoothedDecline), [scene.smoothedDecline])
  const arrow = useRef<SVGGElement | null>(null)
  const ladderDot = useRef<SVGCircleElement | null>(null)
  const readout = useRef<HTMLDivElement | null>(null)
  const levelLine = useRef<HTMLDivElement | null>(null)
  const modeLine = useRef<HTMLDivElement | null>(null)
  const ladder = useMemo(() => buildLadderModel(levels, bandRl, surface), [levels, bandRl, surface])

  useEffect(() => {
    const id = window.setInterval(() => {
      const [e, n, rl] = telemetry.mine()
      const picked = pickLevel(rl, levels, halfBand)
      setLevel((prev) => (prev?.levelId === picked?.levelId ? prev : picked))
      setBandRl((prev) => (Math.abs(prev - rl) > halfBand / 2 ? Math.round(rl / 5) * 5 : prev))
      if (arrow.current) {
        const [u, v] = projectToMap(model.bounds, e, n)
        const cu = Math.min(0.985, Math.max(0.015, u))
        const cv = Math.min(0.985, Math.max(0.015, v))
        arrow.current.setAttribute(
          'transform',
          `translate(${(cu * SIZE).toFixed(1)} ${(cv * SIZE).toFixed(1)}) rotate(${bearingDegFromYaw(telemetry.headingYaw).toFixed(1)})`,
        )
        arrow.current.setAttribute('opacity', u === cu && v === cv ? '1' : '0.45')
      }
      if (ladderDot.current && ladder) {
        const span = Math.max(ladder.zTop - ladder.zBottom, 1e-6)
        const t = Math.min(1, Math.max(0, (ladder.zTop - rl) / span))
        ladderDot.current.setAttribute('cy', (LADDER_PAD + t * (SIZE - 2 * LADDER_PAD)).toFixed(1))
      }
      if (levelLine.current) {
        levelLine.current.textContent = picked
          ? `${picked.levelId} · RL ${picked.elevation.toFixed(0)} m`
          : `${tr('Ramp')} · RL ${rl.toFixed(0)} m`
      }
      if (readout.current) {
        const ch = approximateChainage([e, n, rl], ramp.chainagePoints)
        readout.current.textContent =
          `E ${e >= 0 ? '+' : ''}${e.toFixed(0)} m  N ${n >= 0 ? '+' : ''}${n.toFixed(0)} m\n` +
          `RL ${rl.toFixed(0)} m${ch ? `  CH ${ch.chainageM.toFixed(0)} m` : ''}`
      }
      if (modeLine.current) {
        modeLine.current.textContent = `${tr(telemetry.mode === 'PERSON' ? 'Person' : telemetry.mode === 'VEHICLE' ? 'Vehicle' : 'Drone')}\n${tr('Speed')} ${telemetry.speed.toFixed(1)} m/s`
      }
    }, 125)
    return () => window.clearInterval(id)
  }, [telemetry, levels, halfBand, model, ramp, ladder])

  const path = (xy: number[]) => {
    const d: string[] = []
    for (let i = 0; i + 1 < xy.length; i += 2) {
      const [u, v] = projectToMap(model.bounds, xy[i]!, xy[i + 1]!)
      d.push(`${i === 0 ? 'M' : 'L'}${(u * SIZE).toFixed(1)} ${(v * SIZE).toFixed(1)}`)
    }
    return d.join(' ')
  }
  const extentM = model.bounds.maxX - model.bounds.minX
  const scaleBarM = extentM > 300 ? 100 : extentM > 120 ? 50 : 20
  const scaleBarPx = (scaleBarM / extentM) * SIZE

  return (
    <div className="pointer-events-none absolute left-3 top-3 flex flex-col gap-1">
      <div
        ref={levelLine}
        className="plate rounded-sm bg-rock-900/85 px-2 py-0.5 text-[11px] text-lamp"
      />
      <div className="flex gap-1">
        <svg
          width={SIZE}
          height={SIZE}
          className="rounded-sm border border-rock-700 bg-rock-950/85"
          role="img"
          aria-label={tr('Minimap')}
        >
          {model.polylines.map((p) => (
            <path
              key={p.id}
              d={path(p.xy)}
              fill="none"
              stroke={LINE_STYLE[p.kind].stroke}
              strokeWidth={LINE_STYLE[p.kind].width}
              strokeLinecap="round"
              strokeLinejoin="round"
              opacity={p.kind === 'RAMP' && model.level ? 0.75 : 1}
            />
          ))}
          {model.markers.map((m) => {
            const [u, v] = projectToMap(model.bounds, m.xy[0], m.xy[1])
            return (
              <circle
                key={m.id}
                cx={u * SIZE}
                cy={v * SIZE}
                r={MARKER_STYLE[m.kind].r}
                fill={MARKER_STYLE[m.kind].fill}
              />
            )
          })}
          {/* avatar: placed inside the fitted map, arrow rotated by compass bearing */}
          <g ref={arrow}>
            <polygon
              points="0,-6.5 4.6,5 0,2.4 -4.6,5"
              fill="#ffd894"
              stroke="#1b1d1f"
              strokeWidth={0.6}
            />
          </g>
          {/* north indicator + scale bar */}
          <text x={SIZE - 12} y={14} fill="#8a95a1" fontSize={10} className="readout">
            N
          </text>
          <line x1={SIZE - 8} y1={18} x2={SIZE - 8} y2={8} stroke="#8a95a1" strokeWidth={1} />
          <line
            x1={6}
            y1={SIZE - 8}
            x2={6 + scaleBarPx}
            y2={SIZE - 8}
            stroke="#8a95a1"
            strokeWidth={1.2}
          />
          <text x={8 + scaleBarPx} y={SIZE - 5} fill="#8a95a1" fontSize={9} className="readout">
            {scaleBarM} m
          </text>
        </svg>
        {ladder ? (
          <svg
            width={LADDER_W}
            height={SIZE}
            className="rounded-sm border border-rock-700 bg-rock-950/85"
            role="img"
            aria-label={tr('Level ladder')}
          >
            <line
              x1={9}
              y1={LADDER_PAD}
              x2={9}
              y2={SIZE - LADDER_PAD}
              stroke="#4a4f55"
              strokeWidth={1.2}
            />
            {ladder.ticks.map((t) => {
              const y = LADDER_PAD + t.t * (SIZE - 2 * LADDER_PAD)
              const current = model.level?.levelId === t.levelId
              return (
                <g key={t.levelId}>
                  <line
                    x1={5}
                    y1={y}
                    x2={13}
                    y2={y}
                    stroke={current ? '#ffd894' : '#8a95a1'}
                    strokeWidth={current ? 2 : 1}
                  />
                  <text
                    x={16}
                    y={y + 3}
                    fill={current ? '#ffd894' : '#8a95a1'}
                    fontSize={7}
                    className="readout"
                  >
                    {t.levelId}
                  </text>
                </g>
              )
            })}
            <circle ref={ladderDot} cx={9} cy={LADDER_PAD} r={3} fill="#ffd894" />
          </svg>
        ) : null}
      </div>
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
