import { useMutation } from '@tanstack/react-query'
import { ApiError } from '@/api/client'
import { ActionButton } from '@/components/ui/ActionButton'
import { cloneDemo } from '@/scenario/demos'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useViewerStore } from '@/stores/viewerStore'
import type { DemoCatalogEntry } from '@/types/api'

/**
 * Hardening PR-2 H4 — the CONTROLS column while a baked demo is open
 * (demo mode = viewer-only): no generation controls, no "Reset from here";
 * the demo's identity and its DEMO / SYNTHETIC labels, the Auto tour toggle
 * (camera presets cycle) and the ONE action, "Clone to edit", which creates
 * an ordinary saved scenario from the demo document. 3D / 4D / Walk, Analysis
 * and Export stay available; the backend refuses every write to the demo
 * itself (409 DEMO_READ_ONLY), so the hidden controls are a presentation of
 * that contract, never its only enforcement.
 */
export function DemoPanel() {
  const demo = useScenarioStore((s) => s.demo)
  const tour = useViewerStore((s) => s.demoTour)
  const setTour = useViewerStore((s) => s.setDemoTour)
  const setStage = useViewerStore((s) => s.setStage)
  const clone = useMutation({
    mutationFn: cloneDemo,
    onSuccess: () => setStage('METHOD'),
  })
  if (!demo) return null
  const err = clone.error
  return (
    <DemoPanelBody
      demo={demo}
      tour={tour}
      onTour={setTour}
      cloning={clone.isPending}
      cloneError={err instanceof ApiError ? `${err.code}: ${err.message}` : err ? err.message : null}
      onClone={() => clone.mutate(demo)}
    />
  )
}

/** pure presentation of demo mode (tested as static markup) */
export function DemoPanelBody({
  demo,
  tour,
  onTour,
  cloning,
  cloneError,
  onClone,
}: {
  demo: DemoCatalogEntry
  tour: boolean
  onTour: (on: boolean) => void
  cloning: boolean
  cloneError: string | null
  onClone: () => void
}) {
  return (
    <section className="border-b border-rock-700 px-4 py-3" data-testid="demo-panel">
      <div className="mb-1 flex flex-wrap gap-1" aria-label="demo labels">
        {demo.labels.map((l) => (
          <span
            key={l}
            className="plate rounded-sm border border-lamp/60 px-1.5 py-0.5 text-[10px] text-lamp"
          >
            {l}
          </span>
        ))}
      </div>
      <h3 className="text-[13px] text-chalk">{demo.title}</h3>
      <p className="mt-1 text-[11px] leading-relaxed text-chalk-dim">{demo.description}</p>
      <dl className="readout mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[10px] text-mute">
        <dt>Orebody</dt>
        <dd className="text-chalk-dim">{demo.orebodyType}</dd>
        <dt>Method</dt>
        <dd className="text-chalk-dim">{demo.miningMethod}</dd>
        <dt>Seed</dt>
        <dd className="text-chalk-dim">
          {demo.preset} · {demo.seed}
        </dd>
        <dt>Baked stages</dt>
        <dd className="text-chalk-dim">{demo.stages.join(' → ')}</dd>
      </dl>
      <p className="mt-2 text-[11px] leading-relaxed text-mute" data-testid="demo-viewer-only">
        Viewer-only demo: generation and reset are disabled here — a synthetic sandbox mine,
        never a measured, estimated or imported orebody. Explore it in 3D, 4D and Walk, open
        Analysis or export it; clone it to edit.
      </p>
      <label className="mt-2 flex items-center gap-1.5 text-[11px] text-chalk-dim">
        <input
          type="checkbox"
          checked={tour}
          onChange={(e) => onTour(e.target.checked)}
          data-testid="demo-auto-tour"
        />
        Auto tour (cycle the camera presets)
      </label>
      <div className="mt-2">
        <ActionButton
          variant="primary"
          disabled={cloning}
          onClick={onClone}
          title="Create a saved, editable scenario from this demo's document; its world is regenerated from the same seed"
        >
          {cloning ? 'Cloning…' : 'Clone to edit'}
        </ActionButton>
      </div>
      {cloneError ? (
        <p role="alert" className="mt-1.5 break-words text-[11px] text-danger">
          {cloneError}
        </p>
      ) : null}
    </section>
  )
}
