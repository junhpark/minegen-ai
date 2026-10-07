import { useState } from 'react'
import { PanelSection } from '@/components/layout/PanelSection'
import { LayerTree, SliceControls } from '@/components/panels/LayerPanel'
import { useViewerStore } from '@/stores/viewerStore'

const PRESETS = [
  { kind: 'ISO', label: 'Iso', title: 'Isometric view of the orebody' },
  { kind: 'TOP', label: 'Top', title: 'Plan view from above' },
  { kind: 'FIT', label: 'Fit', title: 'Fit the whole world' },
] as const

/**
 * Hardening H1 §4.2 — the VIEW panel (right column, below the results):
 * camera presets, the Visibility tree and the field-slice controls. Pure
 * viewer-local presentation: it never touches a scenario or an artifact.
 * `SliceControls` stays mounted while the section is collapsed so the slice
 * fetch keeps running independently of visibility.
 */
export function ViewPanel() {
  const [open, setOpen] = useState(true)
  const requestCameraPreset = useViewerStore((s) => s.requestCameraPreset)
  const walkthrough = useViewerStore((s) => s.cameraMode) === 'walkthrough'
  return (
    <>
      <PanelSection
        title="View"
        collapsible
        open={open}
        onToggle={() => setOpen((v) => !v)}
        actions={
          <div className="flex gap-0.5" aria-label="camera presets">
            {PRESETS.map((p) => (
              <button
                key={p.kind}
                type="button"
                disabled={walkthrough}
                title={p.title}
                onClick={() => requestCameraPreset(p.kind)}
                className="readout rounded-sm border border-rock-700 px-1.5 py-0.5 text-[10px] text-chalk-dim hover:border-lamp hover:text-chalk disabled:opacity-40"
              >
                {p.label}
              </button>
            ))}
          </div>
        }
      >
        <LayerTree />
      </PanelSection>
      <SliceControls active={open} />
    </>
  )
}
