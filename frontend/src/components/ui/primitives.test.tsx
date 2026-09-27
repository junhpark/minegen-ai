/**
 * Phase 20E §26 A–C — the rendered contract of the panel primitives.
 *
 * Each primitive is rendered in BOTH states so the accessibility attributes
 * and the content visibility are pinned; the click / key behaviour itself is
 * pinned in `interaction.test.ts`, which the handlers delegate to.
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { Disclosure } from './Disclosure'
import { InfoPopover } from './InfoPopover'
import { PanelTabs, type PanelTab } from './PanelTabs'
import { StatusBadge } from './StatusBadge'
import { artifactTone, nextActionVariant } from './presentation'
import { WorkflowCard } from './WorkflowCard'
import { Metrics } from './MetricRow'

describe('InfoPopover', () => {
  const open = renderToStaticMarkup(
    <InfoPopover label="Mine network" defaultOpen>
      Where connections exist.
    </InfoPopover>,
  )
  const closed = renderToStaticMarkup(
    <InfoPopover label="Mine network">Where connections exist.</InfoPopover>,
  )

  it('is closed by default and reports it', () => {
    expect(closed).toContain('aria-expanded="false"')
    expect(closed).not.toContain('Where connections exist.')
  })

  it('renders its explanation when open', () => {
    expect(open).toContain('aria-expanded="true"')
    expect(open).toContain('Where connections exist.')
  })

  it('is a real button with an accessible name and owns its panel', () => {
    expect(closed).toContain('type="button"')
    expect(closed).toContain('aria-label="About Mine network"')
    const controls = /aria-controls="(info-[^"]+)"/.exec(open)
    expect(controls).not.toBeNull()
    // the id named by aria-controls is the panel that holds the explanation
    expect(open).toContain(`id="${controls![1]}"`)
    expect(open).toContain('role="note"')
  })

  it('carries no action: info never holds a nested control (§8)', () => {
    const body = open.slice(open.indexOf('role="note"'))
    expect(body).not.toContain('<button')
    expect(body).not.toContain('<input')
  })
})

describe('Disclosure', () => {
  const closed = renderToStaticMarkup(<Disclosure label="Details">42 rings</Disclosure>)
  const open = renderToStaticMarkup(
    <Disclosure label="Details" defaultOpen>
      42 rings
    </Disclosure>,
  )

  it('is collapsed by default', () => {
    expect(closed).toContain('aria-expanded="false"')
    // the region stays in the document and is hidden, so collapsed is a real
    // DOM-visibility state
    expect(closed).toMatch(/id="disclosure-[^"]+" hidden=""/)
  })

  it('expands to show its content', () => {
    expect(open).toContain('aria-expanded="true"')
    expect(open).not.toContain('hidden=""')
    expect(open).toContain('42 rings')
  })

  it('the trigger controls the region it owns', () => {
    const controls = /aria-controls="(disclosure-[^"]+)"/.exec(open)
    expect(controls).not.toBeNull()
    expect(open).toContain(`id="${controls![1]}"`)
    expect(open).toContain('type="button"')
  })

  it('a controlled disclosure takes its state from the owner', () => {
    const html = renderToStaticMarkup(
      <Disclosure label="New scenario" open onToggle={() => undefined}>
        form
      </Disclosure>,
    )
    expect(html).toContain('aria-expanded="true"')
    expect(html).toContain('form')
  })
})

describe('PanelTabs', () => {
  const tabs: PanelTab<'A' | 'B'>[] = [
    { id: 'A', label: 'Layout' },
    { id: 'B', label: 'Develop' },
  ]
  const html = renderToStaticMarkup(
    <PanelTabs
      tabs={tabs}
      active="B"
      onSelect={() => undefined}
      label="design workflow"
      panelId="p"
    />,
  )

  it('is a tablist whose active tab is the only selected one', () => {
    expect(html).toContain('role="tablist"')
    expect(html).toContain('aria-label="design workflow"')
    expect((html.match(/role="tab"/g) ?? []).length).toBe(2)
    expect((html.match(/aria-selected="true"/g) ?? []).length).toBe(1)
    const bIdx = html.indexOf('>Develop<')
    expect(html.slice(html.lastIndexOf('<button', bIdx), bIdx)).toContain('aria-selected="true"')
  })

  it('every tab is type=button, so a tab can never submit a form', () => {
    expect((html.match(/type="button"/g) ?? []).length).toBe(2)
  })

  it('uses a roving tabindex and points every tab at the one panel', () => {
    expect(html).toContain('tabindex="0"')
    expect(html).toContain('tabindex="-1"')
    expect((html.match(/aria-controls="p"/g) ?? []).length).toBe(2)
    expect(html).toContain('id="p-tab-A"')
  })
})

describe('StatusBadge', () => {
  it('maps a backend artifact report to a badge state, never a new vocabulary', () => {
    expect(artifactTone(null)).toBe('NOT_GENERATED')
    expect(artifactTone(undefined)).toBe('NOT_GENERATED')
    expect(artifactTone({ status: 'SUCCESS' })).toBe('READY')
    expect(artifactTone({ status: 'FAILED' })).toBe('FAILED')
    // a non-SUCCESS status reads Failed, exactly as each feature coloured it
    // before the badge existed
    expect(artifactTone({ status: 'NO_FEASIBLE_CANDIDATE' })).toBe('FAILED')
    // a running job wins over the persisted artifact
    expect(artifactTone(null, true)).toBe('RUNNING')
    expect(artifactTone({ status: 'SUCCESS' }, true)).toBe('RUNNING')
  })

  it('renders the state for assertions and a readable label', () => {
    expect(renderToStaticMarkup(<StatusBadge tone="READY" />)).toContain('data-status="READY"')
    expect(renderToStaticMarkup(<StatusBadge tone="READY" />)).toContain('Ready')
    expect(renderToStaticMarkup(<StatusBadge tone="NOT_GENERATED" />)).toContain('Not generated')
    expect(renderToStaticMarkup(<StatusBadge tone="FAILED" />)).toContain('Failed')
    expect(renderToStaticMarkup(<StatusBadge tone="ACTIVE" label="Active" />)).toContain('Active')
  })
})

describe('nextActionVariant', () => {
  it('only an actionable first generation is primary', () => {
    expect(nextActionVariant(false, true)).toBe('primary')
    expect(nextActionVariant(true, true)).toBe('secondary')
    expect(nextActionVariant(false, false)).toBe('secondary')
    expect(nextActionVariant(true, false)).toBe('secondary')
  })
})

describe('Metrics', () => {
  it('drops absent rows so a card never shows an empty metric', () => {
    const html = renderToStaticMarkup(
      <Metrics rows={[{ label: 'Rings', value: 12 }, null, { label: 'Gone', value: null }]} />,
    )
    expect(html).toContain('Rings')
    expect(html).not.toContain('Gone')
  })

  it('renders nothing at all when every row is absent', () => {
    expect(renderToStaticMarkup(<Metrics rows={[null]} />)).toBe('')
  })
})

describe('WorkflowCard', () => {
  it('keeps status, key metrics and the failure reason outside Details (§24)', () => {
    const html = renderToStaticMarkup(
      <WorkflowCard
        title="Level development"
        tone="FAILED"
        summary="12 drift pieces"
        failure="GRADE_LIMIT: access L05 cannot reach the entry"
        details={<Metrics rows={[{ label: 'Drifts', value: '1 200 m' }]} />}
      />,
    )
    const detailsRegion = html.slice(html.indexOf('hidden=""'))
    expect(html).toContain('data-status="FAILED"')
    expect(html).toContain('12 drift pieces')
    expect(html).toContain('GRADE_LIMIT: access L05 cannot reach the entry')
    // the failure text is above the collapsed region, never inside it
    expect(detailsRegion).not.toContain('GRADE_LIMIT')
    expect(detailsRegion).toContain('1 200 m')
  })

  it('shows no Details trigger when a feature has no result yet', () => {
    const html = renderToStaticMarkup(<WorkflowCard title="Shafts" tone="NOT_GENERATED" />)
    expect(html).toContain('Shafts')
    expect(html).toContain('data-status="NOT_GENERATED"')
    expect(html).not.toContain('Details')
  })
})
