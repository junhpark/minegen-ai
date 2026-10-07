import { TimelineControl } from '@/components/timeline/TimelineControl'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { artifactTone } from '@/components/ui/presentation'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useViewerStore } from '@/stores/viewerStore'

/**
 * Hardening H1 §4.2 — the status bar: World · Ramp · Levels · Network ·
 * Timeline chips (a presentation of the scene manifest, `StatusBadge`
 * semantics), and the 4D playback control while the 4D view is active.
 */
export function BottomBar() {
  const scene = useScenarioStore((s) => s.scene)
  const scenario = useScenarioStore((s) => s.scenario)
  const fourD = useViewerStore((s) => s.mode) === '4D'
  const chips = [
    {
      label: 'World',
      tone: scene ? ('READY' as const) : ('NOT_GENERATED' as const),
      text: scene ? 'ready' : scenario ? 'not generated' : 'no mine',
    },
    {
      label: 'Ramp',
      tone: scene?.rampSource.available ? ('READY' as const) : ('NOT_GENERATED' as const),
      text: scene?.rampSource.available
        ? scene.rampSource.activeSource === 'LAYOUT_V2'
          ? (scene.rampSource.candidateId ?? 'layout')
          : 'legacy'
        : 'none',
    },
    { label: 'Levels', tone: artifactTone(scene?.levels), text: chipText(scene?.levels) },
    { label: 'Network', tone: artifactTone(scene?.network), text: chipText(scene?.network) },
    { label: 'Timeline', tone: artifactTone(scene?.timeline), text: chipText(scene?.timeline) },
  ]
  return (
    <footer
      className={`shrink-0 border-t border-rock-700 bg-rock-800 ${fourD ? 'h-24' : 'h-8'}`}
      data-testid="status-bar"
    >
      <div className="flex h-8 items-center gap-4 px-3">
        {chips.map((c) => (
          <div key={c.label} className="flex items-center gap-1.5 text-[11px]" data-chip={c.label}>
            <span className="readout text-[10px] text-mute">{c.label}</span>
            <StatusBadge tone={c.tone} label={c.text} />
          </div>
        ))}
        {!fourD ? (
          <span className="ml-auto text-[11px] text-mute">
            {scene?.timeline?.status === 'SUCCESS'
              ? 'Switch to the 4D view to play the schedule'
              : 'Schedule the mine development to enable 4D playback'}
          </span>
        ) : null}
      </div>
      {fourD ? (
        <div className="h-16 border-t border-rock-700">
          <TimelineControl />
        </div>
      ) : null}
    </footer>
  )
}

function chipText(a: { status: string } | null | undefined): string {
  if (a == null) return 'none'
  return a.status === 'SUCCESS' ? 'ready' : 'failed'
}
