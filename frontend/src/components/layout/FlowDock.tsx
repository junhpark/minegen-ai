import { useMemo } from 'react'
import { useScenarioStore } from '@/stores/scenarioStore'
import { completedStagesFor, useViewerStore } from '@/stores/viewerStore'
import { STAGE_IDS, type StageId } from '@/types/workflow'
import { flowLayout, flowMetric, type FlowLayout } from './flowGraph'
import { useStageGlyphs } from './useStageGlyphs'
import { GLYPH_TEXT, STAGE_LABEL, type StageGlyph } from './workflow'
import { tr } from '@/i18n/t'

/**
 * Hardening PR-3 — the FLOW dock: the mine development stages drawn as a
 * node graph under the viewport (the way a node editor sits under a 3D
 * view), every node showing its status glyph and one backend-reported
 * metric, every edge the workflow prerequisite it presents. Clicking a node
 * goes back to that stage — its controls open in the Controls column, where
 * the stage can be regenerated or reset from (rule 219) — and nothing else:
 * the dock runs no generation, no mutation and no layer change. The nodes
 * are HTML buttons over an SVG edge layer, so the stage contract the stepper
 * carried (`data-stage`, `data-glyph`, `aria-current`) lives here now.
 */

const NODE_W = 118
const NODE_H = 38
const COL_PITCH = 146
const ROW_PITCH = 44
const PAD_X = 14
const PAD_Y = 8

export function FlowDock() {
  const stage = useViewerStore((s) => s.stage)
  const setStage = useViewerStore((s) => s.setStage)
  const setFlowDock = useViewerStore((s) => s.setFlowDock)
  const completion = useViewerStore((s) => s.completedViewerStages)
  const scenario = useScenarioStore((s) => s.scenario)
  const scene = useScenarioStore((s) => s.scene)
  const sceneRevision = useScenarioStore((s) => s.sceneRevision)
  const glyphs = useStageGlyphs()
  const metrics = useMemo(() => {
    const completed = completedStagesFor(completion, sceneRevision)
    return Object.fromEntries(
      STAGE_IDS.map((s) => [s, flowMetric(s, { scenario, scene, completed })]),
    ) as Record<StageId, string>
  }, [scenario, scene, completion, sceneRevision])
  return (
    <section
      className="shrink-0 border-t border-rock-700/70 bg-rock-900"
      data-testid="flow-dock"
      aria-label={tr('mine development flow')}
    >
      <header className="flex h-6 items-center gap-3 px-3">
        <span className="plate text-[11px] text-chalk-dim">{tr('Mine development flow')}</span>
        <span className="readout truncate text-[10px] text-mute">
          {tr(
            'click a stage to go back to it · ✓ done · ● next · ○ waiting · ✗ failed · ↻ running · – optional',
          )}
        </span>
        <button
          type="button"
          onClick={() => setFlowDock(false)}
          title={tr('Hide the flow (View › Flow shows it again)')}
          className="readout ml-auto rounded-sm px-1.5 text-[10px] text-mute hover:bg-rock-800 hover:text-chalk"
          data-testid="flow-dock-hide"
        >
          {tr('▾ hide')}
        </button>
      </header>
      <div className="overflow-x-auto">
        <FlowGraphBody stage={stage} glyphs={glyphs} metrics={metrics} onSelect={setStage} />
      </div>
    </section>
  )
}

interface GraphProps {
  layout?: FlowLayout
  stage: StageId
  glyphs: Record<StageId, StageGlyph>
  metrics: Record<StageId, string>
  onSelect: (stage: StageId) => void
}

const NODE_TONE: Record<StageGlyph, string> = {
  DONE: 'border-lamp/70 text-chalk',
  NEXT: 'border-chalk-dim text-chalk',
  RUNNING: 'border-chalk-dim text-chalk animate-pulse',
  FAILED: 'border-danger text-chalk',
  WAITING: 'border-rock-600 text-chalk-dim',
  OPTIONAL: 'border-dashed border-rock-600 text-mute',
}

const GLYPH_TONE: Record<StageGlyph, string> = {
  DONE: 'text-lamp',
  NEXT: 'text-chalk',
  RUNNING: 'text-chalk',
  FAILED: 'text-danger',
  WAITING: 'text-mute',
  OPTIONAL: 'text-mute',
}

/** pure presentation of the graph (testable as static markup) */
export function FlowGraphBody({
  layout = flowLayout(),
  stage,
  glyphs,
  metrics,
  onSelect,
}: GraphProps) {
  const width = PAD_X * 2 + (layout.columns - 1) * COL_PITCH + NODE_W
  const height = PAD_Y * 2 + (layout.rows - 1) * ROW_PITCH + NODE_H
  const at = (s: StageId): { x: number; y: number } => {
    const node = layout.nodes.find((n) => n.stage === s)
    if (!node) return { x: 0, y: 0 }
    // columns are centred vertically on the tallest column
    const offset = (layout.rows - (layout.rowsInColumn[node.column] ?? 1)) / 2
    return { x: PAD_X + node.column * COL_PITCH, y: PAD_Y + (node.row + offset) * ROW_PITCH }
  }
  return (
    <div
      className="relative"
      style={{ width, height }}
      data-testid="flow-graph"
      role="group"
      aria-label={tr('development stages')}
    >
      <svg className="absolute inset-0" width={width} height={height} aria-hidden>
        {layout.edges.map((e) => {
          const a = at(e.from)
          const b = at(e.to)
          const x1 = a.x + NODE_W
          const y1 = a.y + NODE_H / 2
          const x2 = b.x
          const y2 = b.y + NODE_H / 2
          const dx = Math.max(12, (x2 - x1) / 2)
          const done = glyphs[e.to] === 'DONE' || glyphs[e.to] === 'RUNNING'
          return (
            <path
              key={`${e.from}-${e.to}`}
              d={`M ${String(x1)} ${String(y1)} C ${String(x1 + dx)} ${String(y1)}, ${String(x2 - dx)} ${String(y2)}, ${String(x2)} ${String(y2)}`}
              fill="none"
              strokeWidth={1.5}
              className={done ? 'stroke-lamp/60' : 'stroke-rock-600'}
              data-edge={`${e.from}-${e.to}`}
            />
          )
        })}
      </svg>
      {layout.nodes.map((n) => {
        const g = glyphs[n.stage]
        const current = n.stage === stage
        const { x, y } = at(n.stage)
        return (
          <button
            key={n.stage}
            type="button"
            onClick={() => onSelect(n.stage)}
            aria-current={current ? 'step' : undefined}
            data-stage={n.stage}
            data-glyph={g}
            title={`${tr(STAGE_LABEL[n.stage])} — ${tr(g.toLowerCase())} · ${metrics[n.stage]}`}
            style={{ left: x, top: y, width: NODE_W, height: NODE_H }}
            className={[
              'absolute flex flex-col justify-center rounded-md border bg-gradient-to-b from-rock-800 to-rock-900 px-2 text-left shadow-card transition-colors hover:from-rock-700 hover:to-rock-800',
              NODE_TONE[g],
              current ? 'ring-2 ring-lamp shadow-glow' : '',
            ].join(' ')}
          >
            <span className="flex items-center gap-1 text-[11px] leading-none">
              <span aria-hidden className={`readout text-[10px] ${GLYPH_TONE[g]}`}>
                {GLYPH_TEXT[g]}
              </span>
              <span className="plate truncate">{tr(STAGE_LABEL[n.stage])}</span>
            </span>
            <span className="readout mt-0.5 truncate text-[9px] text-mute" data-metric>
              {metrics[n.stage]}
            </span>
          </button>
        )
      })}
    </div>
  )
}
