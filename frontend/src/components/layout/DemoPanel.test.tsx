import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { DemoCatalogEntry } from '@/types/api'
import { DemoPanelBody } from './DemoPanel'

const DEMO: DemoCatalogEntry = {
  id: 'demo-tabular-longhole',
  title: 'Tabular orebody · Longhole Open Stoping',
  description: 'The baseline synthetic tabular mine.',
  orebodyType: 'TABULAR',
  miningMethod: 'LONGHOLE_OPEN_STOPING',
  preset: 'BASELINE',
  seed: 1,
  faultCount: 1,
  stages: ['WORLD', 'LAYOUT', 'LEVELS'],
  labels: ['DEMO', 'SYNTHETIC'],
  available: true,
  reason: null,
}

const render = (over: Partial<Parameters<typeof DemoPanelBody>[0]> = {}) =>
  renderToStaticMarkup(
    <DemoPanelBody
      demo={DEMO}
      tour
      onTour={() => undefined}
      cloning={false}
      cloneError={null}
      onClone={() => undefined}
      {...over}
    />,
  )

describe('DemoPanel (hardening PR-2 H4 — demo mode)', () => {
  it('shows the DEMO / SYNTHETIC labels, the identity, the viewer-only note and ONE primary action', () => {
    const html = render()
    expect(html).toContain('data-testid="demo-panel"')
    expect(html).toContain('>DEMO<')
    expect(html).toContain('>SYNTHETIC<')
    expect(html).toContain('Tabular orebody · Longhole Open Stoping')
    expect(html).toContain('WORLD → LAYOUT → LEVELS')
    expect(html).toContain('data-testid="demo-viewer-only"')
    expect(html).toContain('never a measured, estimated or imported orebody')
    expect(html).toContain('data-testid="demo-auto-tour"')
    expect(html).toContain('checked=""')
    expect((html.match(/data-variant="primary"/g) ?? []).length).toBe(1)
    expect(html).toContain('Clone to edit')
    // no generation vocabulary of the workflow cards
    for (const word of ['Generate', 'Regenerate', 'Reset from here', 'Create mine']) {
      expect(html).not.toContain(word)
    }
  })

  it('renders the clone error and the pending state', () => {
    expect(render({ cloneError: 'DEMO_READ_ONLY: x' })).toContain('DEMO_READ_ONLY: x')
    const pending = render({ cloning: true })
    expect(pending).toContain('Cloning…')
    expect(pending).toContain('disabled=""')
  })
})
