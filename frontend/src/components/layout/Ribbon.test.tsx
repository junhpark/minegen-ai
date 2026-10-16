import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { STAGE_IDS, type StageId } from '@/types/workflow'
import { RibbonBandBody } from './Ribbon'
import { quickAccess, ribbonBand, type RibbonContext, type RibbonTab } from './ribbonModel'
import type { StageGlyph } from './workflow'

const WAITING = Object.fromEntries(STAGE_IDS.map((s) => [s, 'WAITING'])) as Record<
  StageId,
  StageGlyph
>

const ctx = (over: Partial<RibbonContext> = {}): RibbonContext => ({
  stage: 'ACCESS',
  glyphs: { ...WAITING, SCENARIO: 'DONE', METHOD: 'DONE', ACCESS: 'NEXT', SHAFTS: 'OPTIONAL' },
  view: '3D',
  walkBlocked: 'The ramp tunnel mesh is not generated',
  hasScenario: true,
  hasScene: true,
  demo: false,
  jobRunning: false,
  flowDock: true,
  panes: { controls: true, results: true },
  analysisTab: 'OVERVIEW',
  analysisShow3d: false,
  ...over,
})

const render = (tab: RibbonTab, c: RibbonContext) =>
  renderToStaticMarkup(
    <RibbonBandBody
      tab={tab}
      groups={ribbonBand(tab, c)}
      quick={quickAccess(c)}
      onStage={() => undefined}
      onCommand={() => undefined}
    />,
  )

describe('RibbonBandBody (hardening PR-3)', () => {
  it('renders the Setup band: group labels, stage tools with the stage contract, commands, quick access', () => {
    const html = render('SETUP', ctx())
    expect(html).toContain('data-testid="ribbon-band"')
    expect(html).toContain('data-tab="SETUP"')
    expect(html).toContain('>Mine<')
    expect(html).toContain('>1 Setup<')
    expect(html).toContain('data-tool="new-mine"')
    expect(html).toContain('data-tool="open-mine"')
    expect(html).toContain('data-tool="demos"')
    // the stage contract the stepper carried: data-stage / data-glyph / aria-current
    expect(html).toContain('data-stage="SCENARIO" data-glyph="DONE"')
    expect(html).toContain('aria-current="step" data-stage="ACCESS" data-glyph="NEXT"')
    expect(html).not.toContain('data-stage="LAYOUT"')
    // the two ways back
    expect(html).toContain('data-testid="ribbon-quick-access"')
    expect(html).toContain('data-tool="reset-from-here"')
    expect(html).toContain('data-tool="reset-mine"')
    // the band never carries a primary action: the one-primary invariant is untouched
    expect(html).not.toContain('data-variant')
  })

  it('shows a disabled tool with its reason as the title', () => {
    const html = render('VIEW', ctx())
    expect(html).toContain('aria-pressed="true" data-tool="view-3D"')
    expect(html).toContain('aria-pressed="false" data-tool="view-4D"')
    expect(html).toMatch(
      /<button[^>]*disabled=""[^>]*data-tool="view-WALK"[^>]*title="The ramp tunnel mesh is not generated"/,
    )
    expect(html).toContain('data-group="camera"')
    expect(html).toContain('data-group="panels"')
  })

  it('a demo has no quick access (viewer-only)', () => {
    const html = render('DESIGN', ctx({ demo: true, stage: 'LAYOUT' }))
    expect(html).not.toContain('data-testid="ribbon-quick-access"')
    expect(html).not.toContain('data-tool="reset-mine"')
    expect(html).toContain('data-tab="DESIGN"')
  })
})
