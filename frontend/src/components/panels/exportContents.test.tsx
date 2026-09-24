/**
 * PR #44 correction S3: the export panel tells the user what the bundle will
 * hold RIGHT NOW (Option A availability summary + Option B helper text),
 * from the loaded scene only — no generation call, no inference, no
 * disabled button when the ramp is absent (a world-only export is normal).
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { WorldScene } from '@/types/scene'
import { ExportContents } from './ExportContents'
import { EXPORT_HELPER_TEXT, describeExportContents } from './exportContents'

function scene(over: Partial<WorldScene> = {}): WorldScene {
  return {
    faults: [{}, {}],
    rampSource: { activeSource: 'LEGACY' },
    smoothedDecline: null,
    levelAccesses: null,
    levels: null,
    shafts: null,
    tunnelMesh: null,
    developmentMesh: null,
    network: null,
    capabilityGraph: null,
    ...over,
  } as unknown as WorldScene
}

const ok = { status: 'SUCCESS' } as never
const failed = { status: 'FAILED' } as never

describe('describeExportContents', () => {
  it('reports nothing without a scene', () => {
    expect(describeExportContents(null, false)).toEqual([])
  })

  it('world-only: geology included, every design layer not generated', () => {
    const layers = describeExportContents(scene(), false)
    const byKey = Object.fromEntries(layers.map((l) => [l.key, l.state]))
    expect(byKey).toEqual({
      terrain: 'INCLUDED',
      orebody: 'INCLUDED',
      faults: 'INCLUDED',
      ramp: 'NOT_GENERATED',
      levels: 'NOT_GENERATED',
      tunnelMesh: 'NOT_GENERATED',
      developmentMesh: 'NOT_GENERATED',
      network: 'NOT_GENERATED',
      capability: 'NOT_GENERATED',
    })
    expect(layers.find((l) => l.key === 'faults')?.label).toBe('Faults (2)')
    // an undeclared shaft is not a missing layer; LEGACY has no level accesses
    expect(layers.some((l) => l.key === 'shafts')).toBe(false)
    expect(layers.some((l) => l.key === 'levelAccesses')).toBe(false)
  })

  it('partial: ramp + levels included, failed levels shown as failed, rest not generated', () => {
    const layers = describeExportContents(
      scene({
        rampSource: { activeSource: 'LAYOUT_V2' } as never,
        smoothedDecline: ok,
        levelAccesses: ok,
        levels: failed,
        tunnelMesh: ok,
      }),
      true,
    )
    const byKey = Object.fromEntries(layers.map((l) => [l.key, l.state]))
    expect(byKey.ramp).toBe('INCLUDED')
    expect(byKey.levelAccesses).toBe('INCLUDED')
    expect(byKey.levels).toBe('FAILED')
    expect(byKey.shafts).toBe('NOT_GENERATED')
    expect(byKey.tunnelMesh).toBe('INCLUDED')
    expect(byKey.developmentMesh).toBe('NOT_GENERATED')
    expect(byKey.network).toBe('NOT_GENERATED')
    expect(byKey.capability).toBe('NOT_GENERATED')
  })

  it('full: every layer included, a FAILED capability graph is failed (not omitted silently)', () => {
    const full = describeExportContents(
      scene({
        rampSource: { activeSource: 'LAYOUT_V2' } as never,
        smoothedDecline: ok,
        levelAccesses: ok,
        levels: ok,
        shafts: ok,
        tunnelMesh: ok,
        developmentMesh: ok,
        network: ok,
        capabilityGraph: ok,
      }),
      true,
    )
    expect(full.every((l) => l.state === 'INCLUDED')).toBe(true)
    expect(full.map((l) => l.key)).toEqual([
      'terrain',
      'orebody',
      'faults',
      'ramp',
      'levelAccesses',
      'levels',
      'shafts',
      'tunnelMesh',
      'developmentMesh',
      'network',
      'capability',
    ])
    const withFailedCap = describeExportContents(
      scene({ smoothedDecline: ok, levels: ok, network: ok, capabilityGraph: failed }),
      false,
    )
    expect(withFailedCap.find((l) => l.key === 'capability')?.state).toBe('FAILED')
  })
})

describe('ExportContents readout', () => {
  it('renders marks, states and the helper text; helper text alone without a scene', () => {
    const html = renderToStaticMarkup(
      <ExportContents layers={describeExportContents(scene({ smoothedDecline: ok }), true)} />,
    )
    expect(html).toContain('Current export contents')
    expect(html).toContain('Ramp')
    expect(html).toContain('Shafts')
    expect(html).toContain('(not generated)')
    expect(html).toContain(EXPORT_HELPER_TEXT)
    expect(html).toContain('data-state="INCLUDED"')
    expect(html).toContain('data-state="NOT_GENERATED"')
    const failedHtml = renderToStaticMarkup(
      <ExportContents layers={describeExportContents(scene({ levels: failed }), false)} />,
    )
    expect(failedHtml).toContain('(failed)')
    const empty = renderToStaticMarkup(<ExportContents layers={[]} />)
    expect(empty).not.toContain('Current export contents')
    expect(empty).toContain(EXPORT_HELPER_TEXT)
  })
})
