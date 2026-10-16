import { useScenarioStore } from '@/stores/scenarioStore'
import type { SceneMigration } from '@/types/scene'

/**
 * PR #54 review B2 — the notice of a scene read that MIGRATED legacy derived
 * artifacts: the backend recognized an earlier Cut & Fill artifact model and
 * discarded the level development and everything below it under the
 * scenario lock, keeping the world and the layout. The frontend shows the
 * backend's record verbatim and regenerates nothing — the stepper already
 * reads Levels as the next stage because the discarded artifacts are gone.
 */
export function SceneMigrationNotice() {
  const migrations = useScenarioStore((s) => s.scene?.migrations ?? null)
  if (!migrations || migrations.length === 0) return null
  return <SceneMigrationNoticeBody migrations={migrations} />
}

const CODE_TEXT: Record<SceneMigration['code'], string> = {
  CUT_FILL_LEGACY_ARTIFACTS_DISCARDED:
    'Legacy Cut & Fill artifacts were discarded on open: this mine was developed by an earlier Cut & Fill model. The world and the layout are kept; regenerate Levels, then Production and Schedule.',
}

/** pure presentation (tested as static markup) */
export function SceneMigrationNoticeBody({ migrations }: { migrations: SceneMigration[] }) {
  return (
    <section
      role="status"
      data-testid="scene-migration-notice"
      className="border-b border-lamp/50 bg-rock-900/70 px-4 py-3 text-[11px] leading-relaxed text-chalk-dim"
    >
      <h3 className="plate mb-1 text-[12px] text-lamp">Migration</h3>
      {migrations.map((m) => (
        <div key={m.code} data-migration={m.code}>
          <p>{CODE_TEXT[m.code]}</p>
          <p className="readout mt-1 break-words text-[10px] text-mute">
            discarded: {m.deleted.join(', ')}
          </p>
        </div>
      ))}
    </section>
  )
}
