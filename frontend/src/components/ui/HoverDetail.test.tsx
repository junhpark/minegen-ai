import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { HoverDetail } from './HoverDetail'

describe('HoverDetail (hardening PR-3 round 2)', () => {
  it('renders only its trigger in static markup — the detail is a hover / focus panel, never inline', () => {
    const html = renderToStaticMarkup(
      <HoverDetail label="Option 1 details" detail={<span>D 1.23 · G 0.06 · M 0.88</span>}>
        <button type="button">Option 1</button>
      </HoverDetail>,
    )
    expect(html).toContain('<button type="button">Option 1</button>')
    expect(html).not.toContain('hover-detail')
    expect(html).not.toContain('D 1.23')
    // never a primary action of its own
    expect(html).not.toContain('data-variant')
  })
})
