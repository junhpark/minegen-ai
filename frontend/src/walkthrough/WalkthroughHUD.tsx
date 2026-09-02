import { NAVIGATION_MODES, type WalkthroughNavigationMode } from './navigation'
import type { TeleportTarget } from './teleport'

/**
 * Compact walkthrough overlay (Phase 16 §31–34): center crosshair, a
 * pointer-enabled mode selector (1/2/3 keys mirror it), a per-mode
 * keyboard legend bottom-left, temporal snapshot info top-right and the
 * DEV perf readout bottom-right. Mode/speed and the minimap live in the
 * separate MinimapOverlay (top-left).
 */
const LEGENDS: Record<WalkthroughNavigationMode, [string, string][]> = {
  PERSON: [
    ['WASD', 'Move'],
    ['IJKL', 'Look'],
    ['Shift', 'Run'],
    ['R', 'Reset'],
  ],
  VEHICLE: [
    ['W/S', 'Drive'],
    ['A/D', 'Steer'],
    ['IJKL', 'Look'],
    ['Shift', 'Boost'],
    ['R', 'Reset'],
  ],
  DRONE: [
    ['WASD', 'Move'],
    ['IJKL', 'Look'],
    ['Space', 'Up'],
    ['C', 'Down'],
    ['Shift', 'Boost'],
    ['R', 'Reset'],
  ],
}

export function WalkthroughHUD({
  focusedKind,
  snapshotDay = null,
  navigationMode,
  onNavigationMode,
  teleportTargets = [],
  onTeleport,
  perfRef,
}: {
  focusedKind: 'MESH_ROUTER' | 'GAS_SENSOR' | null
  snapshotDay?: number | null
  navigationMode: WalkthroughNavigationMode
  onNavigationMode: (mode: WalkthroughNavigationMode) => void
  /** decline stations for the level-teleport select (hotfix 2) */
  teleportTargets?: readonly TeleportTarget[]
  onTeleport?: (chainageM: number) => void
  perfRef?: { current: HTMLDivElement | null }
}) {
  const temporal = snapshotDay !== null
  const cross = focusedKind ? 'bg-lamp' : 'bg-chalk/50'
  return (
    <div className="pointer-events-none absolute inset-0">
      <div className="absolute left-1/2 top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2">
        <div className={`absolute left-1/2 top-0 h-full w-px -translate-x-1/2 ${cross}`} />
        <div className={`absolute left-0 top-1/2 h-px w-full -translate-y-1/2 ${cross}`} />
      </div>
      {focusedKind ? (
        <div className="readout absolute left-1/2 top-1/2 -translate-x-1/2 translate-y-4 rounded-sm bg-rock-900/80 px-2 py-1 text-center text-[11px] text-lamp">
          <div>{focusedKind}</div>
          <div className="text-chalk-dim">E Inspect</div>
        </div>
      ) : null}
      <div className="pointer-events-auto absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-1">
        {teleportTargets.length > 0 && onTeleport ? (
          <select
            aria-label="Teleport to level"
            className="plate rounded-sm bg-rock-900/80 px-1.5 py-0.5 text-[11px] text-chalk-dim"
            value=""
            onChange={(e) => {
              const t = teleportTargets.find((x) => x.id === e.target.value)
              if (t) onTeleport(t.chainageM)
              e.target.value = ''
            }}
          >
            <option value="" disabled>
              Go to…
            </option>
            {teleportTargets.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label} · CH {t.chainageM.toFixed(0)} m
              </option>
            ))}
          </select>
        ) : null}
        {NAVIGATION_MODES.map((m, i) => (
          <button
            key={m}
            type="button"
            onClick={() => onNavigationMode(m)}
            aria-pressed={m === navigationMode}
            className={[
              'plate rounded-sm px-2 py-0.5 text-[11px]',
              m === navigationMode
                ? 'bg-rock-700 text-lamp shadow-[inset_0_-2px_0_0_var(--color-lamp)]'
                : 'bg-rock-900/70 text-chalk-dim hover:bg-rock-700/60',
            ].join(' ')}
          >
            {i + 1} {m}
          </button>
        ))}
      </div>
      {temporal ? (
        <div className="readout absolute right-3 top-3 rounded-sm bg-rock-900/80 px-3 py-2 text-right text-[11px] leading-relaxed">
          <div className="text-lamp">Day {snapshotDay.toFixed(1)}</div>
          <div className="text-chalk-dim">Timeline snapshot</div>
          <div className="text-chalk-dim">Completed decline only</div>
          <div className="mt-1 text-mute">Return to 4D to change time</div>
        </div>
      ) : null}
      {import.meta.env.DEV ? (
        <div
          ref={perfRef}
          className="readout absolute bottom-3 right-3 whitespace-pre rounded-sm bg-rock-900/70 px-2 py-1 text-[10px] text-chalk-dim"
        />
      ) : null}
      <div className="readout absolute bottom-3 left-3 rounded-sm bg-rock-900/70 px-3 py-2 text-[11px] leading-relaxed text-chalk-dim">
        {LEGENDS[navigationMode].map(([k, v]) => (
          <div key={k}>
            {k}&ensp;{v}
          </div>
        ))}
        {temporal ? null : <div>E&ensp;Inspect</div>}
      </div>
    </div>
  )
}
