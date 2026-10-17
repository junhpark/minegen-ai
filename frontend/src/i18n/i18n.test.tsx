import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it } from 'vitest'
import { RibbonBandBody } from '@/components/layout/Ribbon'
import { quickAccess, ribbonBand, type RibbonContext } from '@/components/layout/ribbonModel'
import type { StageGlyph } from '@/components/layout/workflow'
import { Metrics } from '@/components/ui/MetricRow'
import { StatusBadge } from '@/components/ui/StatusBadge'
import type { LayerId } from '@/types/enums'
import { STAGE_IDS, type StageId } from '@/types/workflow'
import { KO } from './ko'
import { LOCALES, resolveDefaultLocale, useLocaleStore } from './locale'
import { tr, translate } from './t'

const WAITING = Object.fromEntries(STAGE_IDS.map((s) => [s, 'WAITING'])) as Record<
  StageId,
  StageGlyph
>
const ctx: RibbonContext = {
  stage: 'LAYOUT',
  glyphs: { ...WAITING, SCENARIO: 'DONE', METHOD: 'DONE', ACCESS: 'DONE', LAYOUT: 'NEXT' },
  view: '3D',
  walkBlocked: 'The ramp tunnel mesh is not generated',
  hasScenario: true,
  hasScene: true,
  demo: false,
  jobRunning: false,
  flowDock: true,
  panes: { controls: true, results: true },
  layers: new Set<LayerId>(['terrain']),
  analysisTab: 'OVERVIEW',
  analysisShow3d: false,
}

afterEach(() => useLocaleStore.getState().setLocale('en'))

describe('UI locale (PR-3 round 4)', () => {
  it('defaults to Korean; VITE_DEFAULT_LOCALE pins a build, a stored choice wins', () => {
    expect(LOCALES).toEqual(['ko', 'en'])
    expect(resolveDefaultLocale(undefined, null)).toBe('ko')
    expect(resolveDefaultLocale('en', null)).toBe('en')
    expect(resolveDefaultLocale('ko', null)).toBe('ko')
    expect(resolveDefaultLocale('fr', null)).toBe('ko')
    expect(resolveDefaultLocale('en', 'ko')).toBe('ko')
    expect(resolveDefaultLocale(undefined, 'en')).toBe('en')
    expect(resolveDefaultLocale(undefined, 'nonsense')).toBe('ko')
    // the test build is pinned to English so every English assertion keeps its meaning
    expect(useLocaleStore.getState().locale).toBe('en')
  })

  it('translates the English source string, substitutes placeholders after the lookup and falls back to English', () => {
    expect(translate('Create mine', 'ko')).toBe('광산 생성')
    expect(translate('Create mine', 'en')).toBe('Create mine')
    expect(translate('Reset from {stage}', 'ko', { stage: '배치' })).toBe('배치부터 초기화')
    expect(translate('{n} levels', 'ko', { n: 13 })).toBe('레벨 13개')
    expect(translate('{n} levels', 'en', { n: 13 })).toBe('13 levels')
    expect(translate('No such string anywhere', 'ko')).toBe('No such string anywhere')
    expect(translate('Delete {n} files', 'ko', { n: 5 })).toBe('파일 5개 삭제')
    // `tr` reads the live store
    useLocaleStore.getState().setLocale('ko')
    expect(tr('Setup')).toBe('설정')
    useLocaleStore.getState().setLocale('en')
    expect(tr('Setup')).toBe('Setup')
  })

  it('the dictionary is sound: no empty entry, every placeholder of the key survives, no Korean key', () => {
    const entries = Object.entries(KO)
    expect(entries.length).toBeGreaterThan(700)
    for (const [k, v] of entries) {
      expect(k.trim().length, k).toBeGreaterThan(0)
      expect(v.trim().length, k).toBeGreaterThan(0)
      expect(/[가-힣]/.test(k), `Korean in key: ${k}`).toBe(false)
      for (const ph of k.match(/\{\w+\}/g) ?? []) expect(v, `${k} → ${v}`).toContain(ph)
    }
  })

  it('renders the shell in Korean through the same contract (data-* / aria untouched)', () => {
    useLocaleStore.getState().setLocale('ko')
    const html = renderToStaticMarkup(
      <RibbonBandBody
        tab="VIEW"
        groups={ribbonBand('VIEW', ctx)}
        quick={quickAccess(ctx)}
        onStage={() => undefined}
        onCommand={() => undefined}
      />,
    )
    expect(html).toContain('data-tool="layer-terrain"')
    expect(html).toContain('>지형<')
    expect(html).toContain('>배치부터 초기화<')
    expect(html).toContain('>광산 초기화<')
    expect(html).toContain('data-tool="reset-mine"')
    const badge = renderToStaticMarkup(<StatusBadge tone="READY" />)
    expect(badge).toContain('data-status="READY"')
    expect(badge).toContain('준비됨')
    const rows = renderToStaticMarkup(
      <Metrics rows={[{ label: 'Mine duration', value: '3.1 yr (1,133 d)' }]} />,
    )
    expect(rows).toContain('광산 수명')
    expect(rows).toContain('3.1 yr (1,133 d)')
  })
})
