import { useStageGlyphs } from '@/components/layout/useStageGlyphs'
import { GLYPH_TEXT, STAGE_LABEL, WORKFLOW_STEPS } from '@/components/layout/workflow'
import { useViewerStore } from '@/stores/viewerStore'

/**
 * Hardening H1 §4.2 — the stage stepper under the ribbon:
 *
 *   [Scenario ✓][Method ✓] │ [Layout ●][Levels ○][Excavation ○][Shafts –] │ …
 *
 * ✓ done · ● next · ○ waiting · ✗ failed · ↻ running · – optional. A chip is
 * a plain navigation control: clicking it shows that stage's controls and
 * its step's results — it never generates, resets or changes anything
 * (the stage is frontend-local viewer state).
 */
export function StepperBar() {
  const stage = useViewerStore((s) => s.stage)
  const setStage = useViewerStore((s) => s.setStage)
  const glyphs = useStageGlyphs()
  return (
    <nav
      aria-label="workflow stages"
      className="flex h-8 items-center gap-1 overflow-x-auto border-b border-rock-700 bg-rock-900 px-3"
      data-testid="stepper"
    >
      {WORKFLOW_STEPS.map((step, i) => (
        <div key={step.id} className="flex items-center gap-1">
          {i > 0 ? <span aria-hidden className="mx-1 h-4 w-px bg-rock-700" /> : null}
          {step.stages.map((st) => {
            const g = glyphs[st]
            const current = st === stage
            const tone =
              g === 'DONE'
                ? 'text-lamp'
                : g === 'FAILED'
                  ? 'text-danger'
                  : g === 'NEXT' || g === 'RUNNING'
                    ? 'text-chalk'
                    : 'text-mute'
            return (
              <button
                key={st}
                type="button"
                onClick={() => setStage(st)}
                aria-current={current ? 'step' : undefined}
                data-stage={st}
                data-glyph={g}
                title={`${STAGE_LABEL[st]} — ${g.toLowerCase()}`}
                className={[
                  'plate flex items-center gap-1 whitespace-nowrap rounded-sm px-1.5 py-0.5 text-[11px]',
                  current
                    ? 'bg-rock-700 shadow-[inset_0_-2px_0_0_var(--color-lamp)]'
                    : 'hover:bg-rock-800',
                  tone,
                ].join(' ')}
              >
                <span aria-hidden className="readout text-[10px]">
                  {GLYPH_TEXT[g]}
                </span>
                {STAGE_LABEL[st]}
              </button>
            )
          })}
        </div>
      ))}
    </nav>
  )
}
