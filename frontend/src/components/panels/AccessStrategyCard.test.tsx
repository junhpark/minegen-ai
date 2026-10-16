/**
 * PR #54 review B3 — Setup › Access: the access strategy (Ramp only / Ramp +
 * Shaft) is an explicit scenario declaration made before the layout; the
 * card edits `scenario.shafts` only and offers Apply for a real change.
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { ShaftPlanningConfig } from '@/types/api'
import { AccessStrategyCard } from './AccessPanel'
import { accessStrategyOf, withAccessStrategy } from './accessStrategy'
import { SHAFT_SPEC_DEFAULTS, persistedShafts } from './shaftDraft'

const RAMP_ONLY: ShaftPlanningConfig = persistedShafts(null)
const WITH_SHAFT: ShaftPlanningConfig = {
  ...RAMP_ONLY,
  specs: [{ shaftId: 'SHAFT-01', ...SHAFT_SPEC_DEFAULTS }],
}

describe('access strategy helpers', () => {
  it('reads the strategy from the declared specs', () => {
    expect(accessStrategyOf(RAMP_ONLY)).toBe('RAMP_ONLY')
    expect(accessStrategyOf(WITH_SHAFT)).toBe('RAMP_AND_SHAFT')
  })

  it('Ramp only clears the specs; Ramp + Shaft keeps them or seeds ONE schema-default shaft', () => {
    expect(withAccessStrategy(WITH_SHAFT, 'RAMP_ONLY').specs).toEqual([])
    expect(withAccessStrategy(WITH_SHAFT, 'RAMP_AND_SHAFT')).toBe(WITH_SHAFT)
    const seeded = withAccessStrategy(RAMP_ONLY, 'RAMP_AND_SHAFT')
    expect(seeded.specs).toEqual([{ shaftId: 'SHAFT-01', ...SHAFT_SPEC_DEFAULTS }])
    // the planning limits are untouched by the strategy switch
    expect(seeded.maximumStationAccessLength).toBe(RAMP_ONLY.maximumStationAccessLength)
  })
})

function render(persisted: ShaftPlanningConfig | null, hasWorld = true) {
  return renderToStaticMarkup(
    <AccessStrategyCard
      identity="s:1"
      persisted={persisted}
      hasScenario
      hasWorld={hasWorld}
      levelIds={[]}
      pending={false}
      error={null}
      onApply={() => undefined}
    />,
  )
}

describe('AccessStrategyCard markup', () => {
  it('a ramp-only mine: Ramp only checked, no shaft editor, Apply disabled (nothing changed)', () => {
    const html = render(null)
    expect(html).toContain('data-testid="access-strategy"')
    expect(html).toMatch(/data-testid="access-ramp-only"[^>]*checked/)
    expect(html).not.toMatch(/data-testid="access-ramp-shaft"[^>]*checked/)
    expect(html).not.toContain('data-testid="shaft-editor"')
    expect(html).toContain('Ramp only')
    expect(html).toMatch(/<button[^>]*disabled[^>]*>Apply access strategy/)
    // a clean draft is never the stage's primary action
    expect(html).not.toMatch(/data-variant="primary"[^>]*>Apply access strategy/)
  })

  it('a declared shaft: Ramp + Shaft checked and the explicit spec editor shown', () => {
    const html = render(WITH_SHAFT)
    expect(html).toMatch(/data-testid="access-ramp-shaft"[^>]*checked/)
    expect(html).toContain('data-testid="shaft-editor"')
    expect(html).toContain('SHAFT-01')
    expect(html).toContain('Ramp + 1 shaft')
    // no level development yet: the planner-default collar is explained, the
    // suggestion button is absent
    expect(html).not.toContain('Suggest collar')
  })

  it('without a scenario the card only says so', () => {
    const html = renderToStaticMarkup(
      <AccessStrategyCard
        identity=":0"
        persisted={null}
        hasScenario={false}
        hasWorld={false}
        levelIds={[]}
        pending={false}
        error={null}
        onApply={() => undefined}
      />,
    )
    expect(html).toContain('Create or open a mine first')
  })
})
