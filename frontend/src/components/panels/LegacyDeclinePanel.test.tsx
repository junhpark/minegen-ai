/**
 * Closeout v3 §1: the legacy Hybrid-A* decline workflow is ONE collapsed
 * "Advanced" section that auto-expands only for a scenario that actually
 * uses the legacy chain. Pure presentation — no engineering, no store.
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { RampSourceSummary, WorldScene } from '@/types/scene'
import { LEGACY_SECTION_NOTE, LEGACY_SECTION_TITLE, LegacyDeclineBody } from './LegacyDeclinePanel'
import { hasLegacyWork, legacySectionAutoOpen } from './rampSource'

function rampSource(
  active: 'LEGACY' | 'LAYOUT_V2',
  over: Partial<RampSourceSummary> = {},
): RampSourceSummary {
  return {
    activeSource: active,
    owningArtifact: active === 'LEGACY' ? 'decline_smoothed.json' : 'layout_v2_selected.json',
    available: false,
    legacyAvailable: false,
    layoutV2Available: false,
    layoutV2Selected: false,
    sourceKind: null,
    sourceRevision: null,
    candidateId: null,
    family: null,
    status: null,
    segmentCount: 0,
    ...over,
  }
}

function scene(over: Partial<WorldScene>): WorldScene {
  return {
    scenarioId: 'S',
    accessTargets: null,
    decline: null,
    legacySmoothedDecline: null,
    smoothedDecline: null,
    rampSource: rampSource('LEGACY'),
    ...over,
  } as unknown as WorldScene
}

const noop = () => undefined

function render(s: WorldScene | null, open: boolean): string {
  return renderToStaticMarkup(
    <LegacyDeclineBody
      scenario={null}
      scene={s}
      open={open}
      onToggle={noop}
      targetsPending={false}
      declineJob={null}
      declinePending={false}
      smoothJob={null}
      smoothPending={false}
      switching={false}
      errorText={null}
      onGenerateTargets={noop}
      onGenerateDecline={noop}
      onSmooth={noop}
      onSwitch={noop}
    />,
  )
}

describe('legacy section auto-open rule', () => {
  it('a new scenario (LEGACY source, no legacy artifact) stays collapsed', () => {
    const s = scene({})
    expect(hasLegacyWork(s)).toBe(false)
    expect(legacySectionAutoOpen(s)).toBe(false)
    expect(legacySectionAutoOpen(null)).toBe(false)
  })

  it('an existing legacy scenario (LEGACY active AND legacy work) auto-expands', () => {
    const s = scene({ accessTargets: { tag: 't' } as unknown as WorldScene['accessTargets'] })
    expect(hasLegacyWork(s)).toBe(true)
    expect(legacySectionAutoOpen(s)).toBe(true)
    const withDecline = scene({ decline: { tag: 'd' } as unknown as WorldScene['decline'] })
    expect(legacySectionAutoOpen(withDecline)).toBe(true)
  })

  it('legacy work under an active LAYOUT_V2 design stays collapsed', () => {
    const s = scene({
      accessTargets: { tag: 't' } as unknown as WorldScene['accessTargets'],
      rampSource: rampSource('LAYOUT_V2', { available: true, layoutV2Selected: true }),
    })
    expect(hasLegacyWork(s)).toBe(true)
    expect(legacySectionAutoOpen(s)).toBe(false)
  })
})

describe('LegacyDeclineBody', () => {
  it('collapsed: title + note only, no legacy controls', () => {
    const html = render(scene({}), false)
    expect(html).toContain(LEGACY_SECTION_TITLE)
    expect(html).toContain(LEGACY_SECTION_NOTE)
    expect(html).toContain('aria-expanded="false"')
    expect(html).not.toContain('Generate access targets')
    expect(html).not.toContain('role="radiogroup"')
  })

  it('expanded: the advanced source switch and the Phase 03–05 chain are available', () => {
    const html = render(scene({}), true)
    expect(html).toContain('aria-expanded="true"')
    expect(html).toContain('role="radiogroup"')
    expect(html).toContain('Legacy (Hybrid-A*)')
    expect(html).toContain('Generate access targets (Phase 03)')
    expect(html).toContain('Generate decline (Hybrid-A*, Phase 04)')
    expect(html).toContain('Smooth decline (Phase 05)')
    // LAYOUT_V2 cannot be switched to without a selection
    const idx = html.indexOf('>Layout v2</button>')
    expect(html.slice(html.lastIndexOf('<button', idx), idx)).toContain(' disabled=""')
    const html2 = render(
      scene({ rampSource: rampSource('LEGACY', { layoutV2Selected: true }) }),
      true,
    )
    const idx2 = html2.indexOf('>Layout v2</button>')
    expect(html2.slice(html2.lastIndexOf('<button', idx2), idx2)).not.toContain(' disabled=""')
  })
})
