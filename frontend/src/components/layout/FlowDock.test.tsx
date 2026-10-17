import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { STAGE_IDS, type StageId } from '@/types/workflow'
import { FlowGraphBody } from './FlowDock'
import type { StageGlyph } from './workflow'

const glyphs = {
  ...(Object.fromEntries(STAGE_IDS.map((s) => [s, 'WAITING'])) as Record<StageId, StageGlyph>),
  SCENARIO: 'DONE',
  METHOD: 'DONE',
  ACCESS: 'DONE',
  LAYOUT: 'DONE',
  LEVELS: 'FAILED',
  SHAFTS: 'OPTIONAL',
} as Record<StageId, StageGlyph>
const metrics = Object.fromEntries(
  STAGE_IDS.map((s) => [s, `${s.toLowerCase()} metric`]),
) as Record<StageId, string>

describe('FlowGraphBody (hardening PR-3 — the development flow)', () => {
  const html = renderToStaticMarkup(
    <FlowGraphBody stage="LEVELS" glyphs={glyphs} metrics={metrics} onSelect={() => undefined} />,
  )

  it('draws every stage as a node carrying the stage contract and its metric', () => {
    expect(html).toContain('data-testid="flow-graph"')
    expect(html.match(/data-stage="/g)).toHaveLength(STAGE_IDS.length)
    expect(html).toContain('data-stage="SCENARIO" data-glyph="DONE"')
    expect(html).toContain('data-stage="SHAFTS" data-glyph="OPTIONAL"')
    expect(html).toContain('aria-current="step" data-stage="LEVELS" data-glyph="FAILED"')
    expect(html.match(/aria-current="step"/g)).toHaveLength(1)
    expect(html).toContain('levels metric')
    expect(html).toContain('export metric')
  })

  it('draws the prerequisite chain as edges, lit up to the done stages', () => {
    expect(html.match(/data-edge="/g)).toHaveLength(14)
    expect(html).toMatch(
      /data-edge="ACCESS-LAYOUT"[^>]*|class="stroke-lamp\/60"[^>]*data-edge="ACCESS-LAYOUT"/,
    )
    expect(html).toMatch(/class="stroke-rock-600"[^>]*data-edge="LEVELS-NETWORK"/)
    expect(html).toMatch(/class="stroke-lamp\/60"[^>]*data-edge="METHOD-ACCESS"/)
  })

  it('is navigation only — no primary action lives in the dock', () => {
    expect(html).not.toContain('data-variant')
  })
})
