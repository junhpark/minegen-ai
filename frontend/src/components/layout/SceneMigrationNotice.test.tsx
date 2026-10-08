import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { SceneMigration } from '@/types/scene'
import { SceneMigrationNoticeBody } from './SceneMigrationNotice'

const MIGRATION: SceneMigration = {
  code: 'CUT_FILL_LEGACY_ARTIFACTS_DISCARDED',
  artifacts: ['levels.json', 'stopes.json'],
  derivedArtifacts: ['network.json', 'timeline.json'],
  reason: "the persisted artifact 'levels.json' is a legacy Cut & Fill artifact",
  resetFrom: 'LEVELS',
  deleted: ['levels.json', 'network.json', 'stopes.json', 'timeline.json'],
}

describe('SceneMigrationNoticeBody (PR #54 review B2)', () => {
  it('shows the backend migration record verbatim and names what was discarded', () => {
    const html = renderToStaticMarkup(<SceneMigrationNoticeBody migrations={[MIGRATION]} />)
    expect(html).toContain('data-testid="scene-migration-notice"')
    expect(html).toContain('role="status"')
    expect(html).toContain('Legacy Cut &amp; Fill artifacts were discarded')
    expect(html).toContain('regenerate Levels, then Production and Schedule')
    expect(html).toContain('levels.json, network.json, stopes.json, timeline.json')
    // a notice, never a control: the regeneration stays with the stage cards
    expect(html).not.toContain('<button')
  })
})
