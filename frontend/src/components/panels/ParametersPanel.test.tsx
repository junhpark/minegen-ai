/**
 * Parameters readout layout (Phase 17.1 §4).
 *
 * The old `grid-cols-[auto_1fr]` sized its first column to the LONGEST
 * label — "Rock quality (synthetic RMR-like, 0-100)" — which left almost
 * nothing for the value column in the 280 px panel. The label column is now
 * fixed and labels wrap inside it, so every value keeps the same left edge.
 * The synthetic-RMR disclaimer must survive in full: abbreviating it to
 * "RMR" would claim a real Rock Mass Rating the field is not.
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { Scenario } from '@/types/api'
import { ParametersPanel } from './ScenarioPanel'

const SCENARIO = {
  id: 's1',
  world: { sizeX: 1200, sizeY: 1200, depth: 500 },
  terrain: { baseElevation: 300 },
  orebody: { orebodyType: 'TABULAR', strikeDeg: 45, dipDeg: 70, thickness: 12 },
  geology: { rockQuality: { mean: 62, std: 12 }, faults: [{}, {}] },
  fieldSampling: { spacingX: 10, spacingY: 10, spacingZ: 10 },
  ramp: { maxGradient: 0.14, minTurnRadius: 25 },
} as unknown as Scenario

describe('Parameters readout layout', () => {
  const html = renderToStaticMarkup(<ParametersPanel scenario={SCENARIO} />)

  it('uses a fixed label column so long labels cannot compress values', () => {
    expect(html).toContain('grid-cols-[7.5rem_minmax(0,1fr)]')
    expect(html).not.toContain('grid-cols-[auto_1fr]')
  })

  it('keeps the synthetic-RMR disclaimer in full, never a bare "RMR" label', () => {
    expect(html).toContain('Rock quality')
    expect(html).toContain('synthetic RMR-like, 0-100')
    expect(html).not.toMatch(/>\s*RMR\s*</)
  })

  it('renders every parameter value', () => {
    for (const value of ['1200', '500', 'TABULAR', '45', '70', '62', '12', '25', '14']) {
      expect(html).toContain(value)
    }
  })

  it('exposes numerical field spacing, never a "Block" size (Phase 18)', () => {
    expect(html).toContain('Field sampling')
    expect(html).toContain('numerical spacing')
    expect(html).not.toMatch(/>\s*Block\s*</)
    expect(html).not.toContain('blockModel')
  })

  it('shows an explicit empty state with no scenario', () => {
    const empty = renderToStaticMarkup(<ParametersPanel scenario={null} />)
    expect(empty).toContain('No scenario loaded')
    expect(empty).not.toContain('<dl')
  })
})
